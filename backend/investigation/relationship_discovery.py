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
| income_bracket   | exact, both non-null                           | 0.35            |
| branch           | exact on `Account.branch_city`, >=1 shared city| 0.25            |

`value_hash` is an HMAC-SHA256 (`foundation.hashing.hmac_sha256_hex`, keyed
by `Settings.pii_hmac_secret`) of the normalized value (pan/income_bracket/
branch); for `name`, of the normalized-and-sorted pair (`f"{min(a,b)}::
{max(a,b)}"`) since there's no single shared literal value. `method =
"shared_attribute_v1"` on every row.

**HMAC, not a bare hash** (ROADMAP Phase 8 fix, code-review finding, Phase
7): `value_hash` used to be an unsalted `hashlib.sha256(value)` -- for
low-entropy PII like a 10-character PAN, that's brute-forceable/rainbow-
tableable if the DB ever leaks. Keying the hash with an application secret
(`secret`, required, no default -- see `discover_relationships`) makes that
infeasible without also compromising the secret. Because `Relationship`
rows are immutable-by-design (`RelationshipRepository` has no `update`/
`delete`), switching the hash function is a one-time reconciliation, not an
in-place migration: `scripts/reconcile_relationship_hashes.py` clears every
existing row and reruns discovery under the new HMAC.
"""
from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from itertools import combinations

from sqlalchemy.orm import Session

from db.enums import ActorType
from db.models.reference import Customer
from db.repositories.orchestration import RelationshipRepository
from db.repositories.reference import AccountRepository, CustomerRepository
from foundation.hashing import hmac_sha256_hex

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
_INCOME_BRACKET_CONFIDENCE = 0.35
_BRANCH_CONFIDENCE = 0.25


@dataclass
class DiscoveryStats:
    candidate_pool_size: int
    pairs_compared: int
    relationships_created: int
    relationships_skipped_existing: int


def _value_hash(value: str, *, secret: str) -> str:
    return hmac_sha256_hex(value, secret=secret)


def _name_pair_hash(name_a: str, name_b: str, *, secret: str) -> str:
    lo, hi = sorted((name_a, name_b))
    return _value_hash(f"{lo}::{hi}", secret=secret)


def _branch_cities(session: Session, customer_ids: list[str]) -> dict[str, set[str]]:
    """`customer_id -> {non-null Account.branch_city, ...}` for every
    customer in the (bounded, safety-valved) candidate pool. One batched
    `AccountRepository.list_by_customer_ids` query, not a per-customer loop
    (code-review finding, Phase 7: this used to call `get_by_customer` once
    per candidate-pool customer -- the same N+1 shape already fixed once
    elsewhere in this codebase, `graph_filters.annotate_nodes`'s Phase 6
    fix)."""
    result: dict[str, set[str]] = {cid: set() for cid in customer_ids}
    for account in AccountRepository(session).list_by_customer_ids(customer_ids):
        if account.branch_city and account.customer_id is not None:
            result.setdefault(account.customer_id, set()).add(account.branch_city)
    return result


def _matches_for_pair(
    a: Customer, b: Customer, branch_cities: dict[str, set[str]], *, secret: str
) -> list[tuple[str, str, float]]:
    """Every `(shared_attribute, value_hash, confidence)` this pair matches
    on -- zero, one, or several (a pair can match on more than one
    attribute type; each gets its own row, per the confidence-scheme
    docstring above)."""
    matches: list[tuple[str, str, float]] = []

    if a.pan and b.pan:
        norm_a, norm_b = a.pan.strip().upper(), b.pan.strip().upper()
        if norm_a == norm_b:
            matches.append(("pan", _value_hash(norm_a, secret=secret), _PAN_CONFIDENCE))

    ratio = SequenceMatcher(None, a.name, b.name).ratio()
    if ratio >= _NAME_MATCH_THRESHOLD:
        matches.append(
            ("name", _name_pair_hash(a.name, b.name, secret=secret), round(ratio, 2))
        )

    if a.income_bracket and b.income_bracket and a.income_bracket == b.income_bracket:
        matches.append(
            (
                "income_bracket",
                _value_hash(a.income_bracket, secret=secret),
                _INCOME_BRACKET_CONFIDENCE,
            )
        )

    shared_cities = branch_cities.get(a.customer_id, set()) & branch_cities.get(
        b.customer_id, set()
    )
    if shared_cities:
        # Multiple shared cities are possible in principle but not expected
        # at demo/current-data scale -- one row per attribute TYPE (not per
        # matched value), hashing the lexicographically-first shared city
        # so the result is deterministic regardless of set iteration order.
        matches.append(
            ("branch", _value_hash(sorted(shared_cities)[0], secret=secret), _BRANCH_CONFIDENCE)
        )

    return matches


def discover_relationships(
    session: Session, *, actor_type: ActorType, actor_id: str | None, secret: str
) -> DiscoveryStats:
    """The batch discovery job: pulls the gated candidate pool
    (`CustomerRepository.list_relationship_candidate_pool`), does the
    pairwise comparison (PAN/income/branch exact + name fuzzy), writes new
    `Relationship` rows via `find_existing`-guarded `create()` so a rerun
    is idempotent (zero new rows for a pair/attribute combination already
    discovered).

    `secret` (required, keyword-only, no default) keys every `value_hash`
    via `foundation.hashing.hmac_sha256_hex` -- see module docstring for why
    this is an HMAC and not a bare hash. Every real caller passes `Settings.
    pii_hmac_secret`.

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

    branch_cities = _branch_cities(session, [c.customer_id for c in pool])

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
            a, b, branch_cities, secret=secret
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
