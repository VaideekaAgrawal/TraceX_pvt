"""
Fixed tool catalog (ROADMAP Phase 8) -- 9 thin wrappers, each a
`@register_tool(...)`-decorated function over an existing, already-tested
`investigation/*` function. This module computes NOTHING itself; every real
computation is reuse of Phase 5-7 work (`CLAUDE.md` "reuse before
rebuild").

**Scope boundary convention**: a wrapped function that already validates
its own case/account scope (documented per-tool below, "self-validating")
is called as-is. A wrapped function that does NOT validate scope itself
(`get_filtered_ego_graph`'s arbitrary `account_id`, `previous_alerts.
summarize`'s deliberately cross-case reach, a bare `TransactionRepository`
call) gets an explicit `account_id in case_account_ids` check added HERE,
in the wrapper -- the wrapper is the scope boundary for those, not the
callee.

Deliberately excludes `timeline`, `behavior_analysis.analyze`, `case_graph.
shape_money_flow` -- trivial future additions, not required for what
Phase 9 needs per the ROADMAP (graph metrics, fund-flow %, txn aggregates,
prior-SAR/shared-entity lookups), and out of this phase's scope to add
speculatively.

**JSON-safety** (code-review finding: `AiInteraction.facts` is a JSON
column, so any tool output a future caller folds into `facts=` must
actually be `json.dumps`-able, not just "looks like a dict"): every tool
whose underlying return value carries a raw `datetime`/enum member --
`similar_cases` (`SimilarCase.computed_at`/`.outcome`),
`path_recommendation_facts` (`SharedAttributeAdjacencyFact.discovered_at`,
nested inside the dataclass `asdict()` doesn't stringify), and
`relationship_graph` (`Relationship.discovered_at` inside its dict output)
-- is run through `db.repositories._audit.to_jsonable` before returning
(the same recursive Decimal/datetime/Enum-to-JSON-native converter the
audit hash-chain already relies on -- reused here rather than writing a
second one, per this codebase's own reuse-before-rebuild posture).
"""
from __future__ import annotations

import dataclasses
from typing import Any

from sqlalchemy.orm import Session

from db.enums import ActorType
from db.repositories._audit import to_jsonable
from db.repositories.investigation import CaseAccountRepository, CaseRepository
from db.repositories.reference import TransactionRepository
from investigation.account_facts import transaction_stats
from investigation.case_graph import CASE_SCOPE_TRANSACTION_LIMIT
from investigation.customer_profile import build_customer_profile
from investigation.graph_filters import GraphFilters, get_filtered_ego_graph
from investigation.network_risk import compute_network_risk
from investigation.path_facts import compute_path_recommendation_facts
from investigation.previous_alerts import summarize as previous_alerts_summarize
from investigation.relationship_graph import build_case_relationship_graph
from investigation.similar_cases import find_similar_cases
from investigation.transaction_search import search as transaction_search
from orchestration.tools.registry import register_tool


def _require_account_in_case_scope(session: Session, case_id: str, account_id: str) -> list[str]:
    """Shared scope-boundary check for the wrappers whose underlying
    function does NOT validate this itself -- mirrors `orchestration.
    account_explanation.explain_account`'s existing
    `account_id not in case_account_ids -> ValueError` precedent exactly.

    Returns the case's scoped account-id list (not just `None`) so a caller
    that also needs that list right after the check (e.g. `_ego_graph_tool`,
    which passes it into `get_filtered_ego_graph`) doesn't have to issue a
    second, redundant `list_account_ids_for_case` query -- code-review
    finding: this wrapper used to duplicate this exact check inline instead
    of calling the shared helper, specifically to get this return value."""
    case_account_ids = CaseAccountRepository(session).list_account_ids_for_case(case_id)
    if account_id not in case_account_ids:
        raise ValueError(f"account {account_id!r} is not in case {case_id!r}'s scope")
    return case_account_ids


@register_tool(
    "similar_cases",
    "Top-k most similar resolved cases to this case, by cosine similarity "
    "over the RL bandit's 16-dim case feature vector.",
)
def _similar_cases_tool(
    session: Session,
    case_id: str,
    *,
    actor_type: ActorType,
    actor_id: str | None,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Self-validating -- `find_similar_cases` raises `ValueError` on an
    unknown `case_id` itself. Converted to a list of JSON-safe dicts --
    `SimilarCase.computed_at` is a raw `datetime` and `.outcome` a raw
    `CaseResolution` enum member, neither JSON-serializable as-is
    (code-review finding: the previous version returned the raw dataclass
    list, which would crash `session.flush()` if ever folded into an
    `AiInteraction.facts` JSON column)."""
    results = find_similar_cases(
        session, case_id, top_k=top_k, actor_type=actor_type, actor_id=actor_id
    )
    return [to_jsonable(dataclasses.asdict(r)) for r in results]


@register_tool(
    "path_recommendation_facts",
    "Fund-flow %, shared-attribute adjacency, and prior-SAR adjacency facts "
    "for this case's primary account -- the raw signal an investigation "
    "path recommendation would reason over.",
)
def _path_recommendation_facts_tool(
    session: Session, case_id: str, *, actor_type: ActorType, actor_id: str | None
) -> dict[str, Any]:
    """Self-validating -- `compute_path_recommendation_facts` raises
    `ValueError` on an unknown `case_id` itself. `dataclasses.asdict(...)`
    alone is NOT sufficient for JSON-safety here (code-review finding): it
    doesn't stringify a raw `datetime` nested inside the result
    (`SharedAttributeAdjacencyFact.discovered_at`) -- `to_jsonable` runs
    over the whole `asdict()` output afterward to fix that."""
    facts = compute_path_recommendation_facts(session, case_id)
    return to_jsonable(dataclasses.asdict(facts))


@register_tool(
    "relationship_graph",
    "The case's shared-attribute relationship graph (Relationship "
    "Explorer v1) -- this case's own customers plus one hop out to any "
    "customer sharing a discovered PAN/name/income-bracket/branch match.",
)
def _relationship_graph_tool(
    session: Session, case_id: str, *, actor_type: ActorType, actor_id: str | None
) -> dict[str, Any]:
    """Self-validating -- `build_case_relationship_graph` raises
    `ValueError` on an unknown `case_id` itself. Fetches `case_account_ids`
    itself via `CaseAccountRepository.list_account_ids_for_case`. Run
    through `to_jsonable` before returning -- the result's `edges` carry a
    raw `Relationship.discovered_at` `datetime` (code-review finding, same
    class of gap as `path_recommendation_facts`)."""
    case_account_ids = CaseAccountRepository(session).list_account_ids_for_case(case_id)
    return to_jsonable(build_case_relationship_graph(session, case_id, case_account_ids))


@register_tool(
    "ego_graph",
    "N-hop filtered ego-subgraph around a case-scoped account -- role/risk/"
    "prior-SAR-annotated nodes and edges.",
)
def _ego_graph_tool(
    session: Session,
    case_id: str,
    *,
    actor_type: ActorType,
    actor_id: str | None,
    account_id: str,
    radius: int = 1,
    filters: GraphFilters | None = None,
) -> dict[str, Any]:
    """NOT self-validating -- `get_filtered_ego_graph` accepts an arbitrary
    `account_id` with no scope check of its own (it's designed to be called
    from an already-scope-checked HTTP route dependency), so this wrapper
    IS the scope boundary here."""
    case_account_ids = _require_account_in_case_scope(session, case_id, account_id)
    return get_filtered_ego_graph(
        session,
        case_id,
        account_id,
        radius=radius,
        filters=filters if filters is not None else GraphFilters(),
        case_account_ids=case_account_ids,
    )


@register_tool(
    "network_risk",
    "This case's network risk score (0-100) and its contributing reasons "
    "(mule-linked accounts, prior SARs, sanctioned/PEP entities, cycles, "
    "high-centrality accounts). Lazy-computes and persists on first read "
    "or when force=True.",
    write=True,
)
def _network_risk_tool(
    session: Session,
    case_id: str,
    *,
    actor_type: ActorType,
    actor_id: str | None,
    force: bool = False,
) -> dict[str, Any]:
    """Validates the case exists first (raises `ValueError` otherwise --
    `compute_network_risk` would eventually raise too, via `CaseRepository.
    update`, but only after doing the expensive graph work first; checking
    up front avoids that wasted work on an unknown `case_id`). Lazy-fill:
    if `case.network_risk_score` is `None`, or `force=True`, recomputes and
    persists (does NOT commit -- caller owns the transaction boundary,
    same convention as every other write in this codebase); otherwise reads
    the already-computed score straight off the loaded `Case` row."""
    case_repo = CaseRepository(session)
    case = case_repo.get(case_id)
    if case is None:
        raise ValueError(f"case {case_id!r} does not exist")

    if force or case.network_risk_score is None:
        case = compute_network_risk(session, case_id, actor_type=actor_type, actor_id=actor_id)

    return {
        "network_risk_score": case.network_risk_score,
        "network_risk_reasons": case.network_risk_reasons,
    }


@register_tool(
    "previous_alerts_summary",
    "Prior alert/SAR/false-positive history for a case-scoped account, "
    "across every OTHER case (network-wide reach) -- excludes this case's "
    "own alerts.",
)
def _previous_alerts_summary_tool(
    session: Session,
    case_id: str,
    *,
    actor_type: ActorType,
    actor_id: str | None,
    account_id: str,
) -> dict[str, Any]:
    """NOT self-validating -- `previous_alerts.summarize` is deliberately
    cross-case (it walks EVERY alert for `account_id`, not just this case's)
    and has no case-scope check of its own; this wrapper adds the check
    that `account_id` itself is in `case_id`'s scope before running that
    cross-case lookup."""
    _require_account_in_case_scope(session, case_id, account_id)
    return previous_alerts_summarize(session, account_id, exclude_case_id=case_id)


@register_tool(
    "account_transaction_stats",
    "Aggregated transaction stats (total in/out, txn count, counterparty "
    "count, channel breakdown) for a case-scoped account.",
)
def _account_transaction_stats_tool(
    session: Session,
    case_id: str,
    *,
    actor_type: ActorType,
    actor_id: str | None,
    account_id: str,
) -> dict[str, Any]:
    """NOT self-validating -- mirrors `orchestration.account_explanation.
    _assemble_facts`'s own pattern exactly: scope-check first, then a
    plain `TransactionRepository` read + the pure `transaction_stats`
    reduction (no case-scope awareness of its own)."""
    _require_account_in_case_scope(session, case_id, account_id)
    txns = TransactionRepository(session).list_for_account_in_window(
        account_id, limit=CASE_SCOPE_TRANSACTION_LIMIT
    )
    return transaction_stats(txns, account_id)


@register_tool(
    "customer_profile",
    "Complete L2 customer profile for a case-scoped account -- KYC/risk "
    "fields, sibling accounts, prior-SAR count, expected-vs-actual monthly "
    "volume variance.",
)
def _customer_profile_tool(
    session: Session,
    case_id: str,
    *,
    actor_type: ActorType,
    actor_id: str | None,
    account_id: str,
) -> dict[str, Any]:
    """Self-validating -- `build_customer_profile` raises `ValueError` if
    `account_id` isn't in `case_id`'s scope itself."""
    return build_customer_profile(session, case_id, account_id)


@register_tool(
    "search_transactions",
    "Filtered, paginated transaction search scoped to this case's linked "
    "accounts (or a single case-scoped account, if given).",
)
def _search_transactions_tool(
    session: Session,
    case_id: str,
    *,
    actor_type: ActorType,
    actor_id: str | None,
    account_id: str | None = None,
    min_amount: float | None = None,
    max_amount: float | None = None,
    limit: int = 200,
    offset: int = 0,
    sort: str = "timestamp_desc",
) -> dict[str, Any]:
    """Self-scoping via `investigation.transaction_search.search`'s own
    established invariant (Phase 6): the `account_ids` it ultimately
    queries are always derived from `case_id`'s own scoped accounts (or
    narrowed to `[account_id]` only if `account_id` actually is one of
    them) -- never a caller-supplied free list."""
    return transaction_search(
        session,
        case_id,
        account_id=account_id,
        min_amount=min_amount,
        max_amount=max_amount,
        limit=limit,
        offset=offset,
        sort=sort,
    )
