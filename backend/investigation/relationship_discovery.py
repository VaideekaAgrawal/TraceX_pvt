"""
Relationship Explorer v1 discovery job (ROADMAP Phase 7, `SYSTEM_
DEVELOPMENT_PLAN.md` §4.2). Locked v1 scope (`docs/DATA_SCHEMA.md`, exact
quote): "v1 (Phase 7) only populates name/branch/income/PAN; device/IP/
nominee/introducer wait on data." Four signals compared here: fuzzy-name,
`Account.branch_city`, `Customer.income_bracket`, `Customer.pan`.

**Global batch job, not lazy-fill-per-case** (unlike Network Risk Score --
approved plan, "Persistence model" decision): Network Risk Score's
lazy-fill fits because its expensive step is itself case-scoped (a
different ego-graph per case); this discovery job's expensive step (the
pairwise candidate-pool comparison) is global and case-independent, so
running it per-case-view would mean redundantly re-running the same
whole-pool comparison on every case's first view. Correct analog: "compute
once, globally, read cheaply many times per case." Consequence: no
HTTP-triggered discovery in this phase -- invoked via `scripts.
discover_relationships` (CLI) and `demo_data.seed`'s 5th marker-gated stage
only. An admin-triggered `POST .../relationships/discover` is a reasonable
future addition once an admin-routes surface exists (deferred, not built).

**Candidate-pool bound (the real-data scale problem):** 166,207 real
ingested customers vs. ~200 Phase-1B demo KYC customers -- an unbounded
pairwise comparison is ~2.8x10^10 pairs, never happening.
`CustomerRepository.list_relationship_candidate_pool` gates the pool on
`pan IS NOT NULL OR income_bracket IS NOT NULL` (see that method's
docstring for the full reasoning) -- expected pool size is on the order of
the ~200 demo customers (+ any real customer that happens to have these
populated), where a full O(n^2) pass including `difflib.SequenceMatcher`
fuzzy-name comparison is genuinely cheap (seconds, not minutes).
`MAX_CANDIDATE_POOL_SIZE` below is a safety valve, not the primary
mechanism -- if the gated pool ever exceeds it, this module RAISES rather
than silently truncating (this codebase's "flag, don't fake" posture, e.g.
the deferred "International" graph filter in `investigation.
graph_filters`).

**Confidence scheme** (fixed judgment-call constants, no cross-signal
weighting -- one `relationships` row per matching attribute TYPE, not a
merged row, matching the schema's one-value-per-row shape and Phase 1B's
existing one-cluster-one-attribute demo-data precedent):

| shared_attribute | match rule                                   | confidence      |
|------------------|-----------------------------------------------|-----------------|
| pan              | exact, normalized (`strip().upper()`)          | 0.95            |
| name             | `SequenceMatcher.ratio() >= 0.85`              | the ratio, 2dp  |

**`income_bracket` and `branch` were removed** (owner review): a shared income
bracket or branch city is a demographic commonality, not a coordination signal —
in a real bank every customer trivially shares a bracket (~6 buckets) and a city
with hundreds of others, which buried the genuine PAN/name links under thousands
of meaningless edges (a single case surfaced 97 "related" customers, all noise).
Only strong same-entity signals (shared PAN, near-identical name) remain.

`value_hash` is a **keyed HMAC-SHA256** of the normalized PAN value, keyed on
`Settings.pii_hmac_key`; for `name`, the HMAC
of the normalized-and-sorted pair (`f"{min(a,b)}::{max(a,b)}"`) since there's no
single shared literal value. `method = "shared_attribute_v1"` on every row.

Phase 8 (decision 9) changed this from a bare SHA256: a PAN is ten characters
from a known alphabet in a known layout, so an unsalted digest of one is
brute-forceable offline by anyone holding a leaked table. See `_value_hash`.
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from difflib import SequenceMatcher
from itertools import combinations

from sqlalchemy.orm import Session

from db.enums import ActorType
from db.models.reference import Customer
from db.repositories.orchestration import RelationshipRepository
from db.repositories.reference import CustomerRepository

#: Safety valve, not the primary mechanism -- see module docstring.
MAX_CANDIDATE_POOL_SIZE = 5000

#: `difflib.SequenceMatcher.ratio()` threshold for a fuzzy-name match --
#: below this, two names are "different people", not "same person,
#: reformatted/misspelled" (approved plan judgment call; no calibration
#: data exists anywhere in this codebase to derive a threshold from
#: instead, same posture as `investigation.network_risk`'s weights).
_NAME_MATCH_THRESHOLD = 0.85

_METHOD = "shared_attribute_v1"

_PAN_CONFIDENCE = 0.95


@dataclass
class DiscoveryStats:
    candidate_pool_size: int
    pairs_compared: int
    relationships_created: int
    relationships_skipped_existing: int


def _value_hash(value: str, *, hmac_key: str) -> str:
    """Keyed HMAC-SHA256 of a PII value (ROADMAP Phase 8, committed decision 9;
    resolves the item Session 11 deferred).

    **Why not a plain SHA256, which is what this was.** A hash only hides its
    input when the input is hard to guess, and these inputs are not: a PAN is ten
    characters from a known alphabet in a known layout, an Aadhaar is twelve
    digits, an Indian mobile is ten. An attacker with a leaked `relationships`
    table and a laptop can enumerate the entire space and match the digests back
    to the raw values offline. Unsalted SHA256 of a low-entropy identifier is not
    pseudonymisation; it is an encoding.

    Keying it with a secret the database does not contain removes that: without
    `pii_hmac_key`, the digests are useless even to someone holding the whole
    table.

    Refuses an empty key rather than quietly degrading to an unkeyed digest —
    a silently-unkeyed hash is precisely the bug this replaces, and it would be
    invisible in the data. Relationship rows are *derived*, so rotating the key
    is a regenerate via `scripts/discover_relationships.py`, not a migration."""
    if not hmac_key:
        raise ValueError(
            "pii_hmac_key is not set — refusing to write an unkeyed hash of a PII "
            "value (ROADMAP Phase 8, decision 9). Set PII_HMAC_KEY (see "
            "backend/.env.example)."
        )
    return hmac.new(hmac_key.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()


def _name_pair_hash(name_a: str, name_b: str, *, hmac_key: str) -> str:
    lo, hi = sorted((name_a, name_b))
    return _value_hash(f"{lo}::{hi}", hmac_key=hmac_key)


def _matches_for_pair(
    a: Customer, b: Customer, *, hmac_key: str
) -> list[tuple[str, str, float]]:
    """Every `(shared_attribute, value_hash, confidence)` this pair matches
    on -- zero, one, or several (a pair can match on more than one
    attribute type; each gets its own row, per the confidence-scheme
    docstring above)."""
    matches: list[tuple[str, str, float]] = []

    if a.pan and b.pan:
        norm_a, norm_b = a.pan.strip().upper(), b.pan.strip().upper()
        if norm_a == norm_b:
            matches.append(("pan", _value_hash(norm_a, hmac_key=hmac_key), _PAN_CONFIDENCE))

    ratio = SequenceMatcher(None, a.name, b.name).ratio()
    if ratio >= _NAME_MATCH_THRESHOLD:
        matches.append(
            ("name", _name_pair_hash(a.name, b.name, hmac_key=hmac_key), round(ratio, 2))
        )

    # NB: a shared income bracket or branch city is deliberately NOT a
    # relationship. In a real bank every customer trivially shares a bracket
    # (~6 buckets) and a city with hundreds of others, so those matches buried
    # the genuine coordination signals under thousands of meaningless edges — a
    # single case surfaced 97 "related" customers, all bracket/city noise. Only
    # a shared PAN (same tax id) or a near-identical name creates a relationship.
    return matches


def discover_relationships(
    session: Session, *, actor_type: ActorType, actor_id: str | None, hmac_key: str
) -> DiscoveryStats:
    """The batch discovery job: pulls the gated candidate pool
    (`CustomerRepository.list_relationship_candidate_pool`), does the
    pairwise comparison (PAN/income/branch exact + name fuzzy), writes new
    `Relationship` rows via `find_existing`-guarded `create()` so a rerun
    is idempotent (zero new rows for a pair/attribute combination already
    discovered).

    `hmac_key` (from `Settings.pii_hmac_key`) keys the `value_hash` HMAC --
    required, and empty is refused rather than degraded to an unkeyed digest;
    see `_value_hash`. Changing the key changes every hash, so a rotation means
    re-running this job: the rows are derived, not source.

    Raises `ValueError` if the gated pool exceeds `MAX_CANDIDATE_POOL_SIZE`
    -- see module docstring's "safety valve, not the primary mechanism"."""
    customer_repo = CustomerRepository(session)
    relationship_repo = RelationshipRepository(session)

    pool = customer_repo.list_relationship_candidate_pool(limit=MAX_CANDIDATE_POOL_SIZE + 1)
    if len(pool) > MAX_CANDIDATE_POOL_SIZE:
        raise ValueError(
            f"relationship candidate pool ({len(pool)} customers, gated on "
            f"pan IS NOT NULL OR income_bracket IS NOT NULL) exceeds "
            f"MAX_CANDIDATE_POOL_SIZE={MAX_CANDIDATE_POOL_SIZE} -- the O(n^2) "
            "pairwise comparison this job performs is not safe to run "
            "unbounded; raising rather than silently truncating the pool."
        )

    pairs_compared = 0
    relationships_created = 0
    relationships_skipped_existing = 0

    for a, b in combinations(pool, 2):
        pairs_compared += 1
        # `RelationshipRepository.create`/`find_existing` canonicalize
        # entity_a/entity_b (lexicographic sort) internally -- callers may
        # pass either ordering (code-review finding, Phase 7: this used to
        # be a caller-side responsibility via a local `_canonical_pair`
        # helper here, now centralized in the repository so it can't be
        # skipped by a future second writer).
        for shared_attribute, value_hash, confidence in _matches_for_pair(
            a, b, hmac_key=hmac_key
        ):
            if (
                relationship_repo.find_existing(a.customer_id, b.customer_id, shared_attribute)
                is not None
            ):
                relationships_skipped_existing += 1
                continue
            relationship_repo.create(
                entity_a=a.customer_id,
                entity_b=b.customer_id,
                shared_attribute=shared_attribute,
                value_hash=value_hash,
                confidence=confidence,
                method=_METHOD,
                actor_type=actor_type,
                actor_id=actor_id,
            )
            relationships_created += 1

    return DiscoveryStats(
        candidate_pool_size=len(pool),
        pairs_compared=pairs_compared,
        relationships_created=relationships_created,
        relationships_skipped_existing=relationships_skipped_existing,
    )
