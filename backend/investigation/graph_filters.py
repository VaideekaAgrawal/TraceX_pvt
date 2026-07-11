"""
N-hop graph exploration + filter engine (ROADMAP Phase 6 -- L2 deep
investigation, `SYSTEM_DEVELOPMENT_PLAN.md` §4.2 "Full Network Graph
Exploration"/"Graph Filters"). `NetworkXGraphStore.get_ego_graph` already
supports N-hop BFS (`radius`, `time_window`) but does ZERO filtering --
every filter in the spec (suspicious-only, risk/amount threshold, time
window, channel, direction, source/mule/sink role, prior-SAR) is applied
here, over the ego-subgraph the store returns. Pure-function-first
(testable without HTTP, ROADMAP plan): `apply_filters` is a pure function
over already-fetched nodes/edges; `build_subgraph_store`/`annotate_nodes`/
`get_filtered_ego_graph` are the DB-touching assembly layer around it,
mirroring `investigation.case_graph`'s own store-vs-shaping split.

**"International" filter is explicitly deferred, not faked.** No
country/jurisdiction field exists anywhere on `Account`/`Customer`
(confirmed via full grep of `db/models/reference.py`) -- fabricating a
proxy (e.g. `from_bank != to_bank` meaning "different bank," not
"international") would silently misrepresent a real AML signal as
present when it isn't. `channels=["UPI"]`/`["branch_cash"]` directly cover
the "UPI-only"/"cash-only" filters the spec also names.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

import pandas as pd
from sqlalchemy.orm import Session

from db.enums import CaseResolution
from db.repositories.detection import AlertRepository
from db.repositories.investigation import CaseRepository
from db.repositories.reference import AccountRepository, CustomerRepository
from detection.graph.networkx_store import NetworkXGraphStore
from detection.scoring.ensemble import RoleClassifier
from investigation.case_graph import build_case_graph_store

#: Safety valve -- `NetworkXGraphStore.get_ego_graph` has no built-in upper
#: bound on `radius` (plain BFS); an unbounded radius on a hub account can
#: balloon the walked subgraph fast even within one case's scope. Not
#: derived from any formula -- a judgment call, documented, same posture as
#: `investigation.network_risk`'s weights (no calibration data exists to
#: derive one from).
MAX_RADIUS = 4

#: Mirrors `investigation.case_graph`'s own `_TRANSACTION_COLUMNS`/account
#: column shape exactly -- `ego["edges"]`/`ego["nodes"]` are drawn straight
#: from a store built with those columns (`build_case_graph_store`), so a
#: throwaway store built from just the ego-subgraph must use the same shape
#: for `NetworkXGraphStore` to behave identically on the smaller input.
_TRANSACTION_COLUMNS = [
    "txn_id", "source_account", "dest_account", "amount", "timestamp",
    "channel", "is_laundering", "from_bank", "to_bank",
]
_ACCOUNT_COLUMNS = [
    "account_id", "branch_city", "declared_annual_income", "occupation", "income_bracket",
]


@dataclass
class GraphFilters:
    """Every filter in the L2 spec, ANDed together by `apply_filters`. All
    optional/falsy-default so "no filters" (every field at its default)
    reproduces the raw `get_ego_graph` output exactly, modulo the
    denormalized annotations `annotate_nodes` always adds."""

    suspicious_only: bool = False
    min_risk_score: float | None = None
    min_amount: float | None = None
    max_amount: float | None = None
    start: datetime | None = None
    end: datetime | None = None
    channels: list[str] | None = None
    direction: Literal["in", "out"] | None = None
    roles: list[str] | None = None
    prior_sar_only: bool = False


def build_subgraph_store(ego: dict[str, Any]) -> NetworkXGraphStore:
    """Throwaway `NetworkXGraphStore` built from just `ego`'s own
    nodes/edges -- NOT the whole case graph -- mirroring
    `investigation.case_graph.build_case_graph_store`'s df-shape convention
    but scoped to one ego-subgraph, so role classification (`annotate_nodes`)
    runs over exactly the radius the caller asked for, not the full case."""
    edges = ego.get("edges", [])
    transactions_df = pd.DataFrame(edges, columns=_TRANSACTION_COLUMNS)
    if not transactions_df.empty:
        transactions_df["timestamp"] = pd.to_datetime(transactions_df["timestamp"])

    nodes = ego.get("nodes", [])
    if nodes:
        accounts_df = pd.DataFrame(nodes)
        for col in _ACCOUNT_COLUMNS:
            if col not in accounts_df.columns:
                accounts_df[col] = None
    else:
        accounts_df = pd.DataFrame(columns=_ACCOUNT_COLUMNS)
    return NetworkXGraphStore(accounts_df, transactions_df)


def _compute_hop_distances(edges: list[dict[str, Any]], center: str) -> dict[str, int]:
    """BFS hop distance from `center` over `edges`, treated as undirected
    (matches `NetworkXGraphStore.get_ego_graph`'s own BFS, which walks a
    node's transactions regardless of source/dest side). A self-loop
    contributes no adjacency. `center` is always distance 0, even if it has
    no edges."""
    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        src, dst = edge.get("source_account"), edge.get("dest_account")
        if src is None or dst is None or src == dst:
            continue
        adjacency[src].add(dst)
        adjacency[dst].add(src)

    distances: dict[str, int] = {center: 0}
    frontier = [center]
    while frontier:
        next_frontier: list[str] = []
        for node in frontier:
            for neighbor in adjacency.get(node, ()):
                if neighbor not in distances:
                    distances[neighbor] = distances[node] + 1
                    next_frontier.append(neighbor)
        frontier = next_frontier
    return distances


def annotate_nodes(session: Session, ego: dict[str, Any], case_id: str) -> list[dict[str, Any]]:
    """Denormalized-rich per-node dicts for the N-hop graph response --
    "UI consumes later" (ROADMAP plan) means no follow-up round-trip should
    be required, so role/risk/prior-SAR/hop-distance are all inline:

      - `role`/`role_confidence`: `RoleClassifier.classify_all` run over a
        THROWAWAY store scoped to just this ego-subgraph (`build_subgraph_
        store`), not the case-wide graph `investigation.network_risk` uses
        -- role is legitimately different at different radii/subgraphs
        (an account can look like a MULE within a tight 1-hop neighborhood
        and NORMAL once a wider radius dilutes its in/out flow ratio); this
        is a second, radius-scoped role computation distinct from (and not
        a replacement for) that case-wide one, both valid for different
        questions.
      - `current_risk_score`: `Account.current_risk_score`, batch-fetched.
      - `has_prior_sar`: reuses `investigation.previous_alerts`'s
        `AlertRepository.list_for_primary_account` -> `Case.resolution ==
        TRUE_POSITIVE_SAR` pattern, but extended here to EVERY node in the
        ego-graph rather than just the case's own accounts -- exactly the
        network-wide reach `previous_alerts.py`'s own docstring defers to
        Phase 6 ("Previous Alert & Case History (network-wide)"). Uses
        `AlertRepository.list_for_primary_accounts` (batched, one `IN`
        query for every node) rather than looping `list_for_primary_
        account` once per node (code-review finding, Phase 6: the
        per-node loop was hundreds of sequential round-trips at radius=4
        on a real hub account -- 325ms vs. 6-13ms for every other L2
        endpoint).
      - `hop_distance`: BFS distance from `ego["center"]` (see
        `_compute_hop_distances`).
    """
    center: str = ego["center"]
    sub_store = build_subgraph_store(ego)
    roles = RoleClassifier().classify_all(sub_store)
    hop_distances = _compute_hop_distances(ego.get("edges", []), center)

    nodes = ego.get("nodes", [])
    account_ids = [n["account_id"] for n in nodes if n.get("account_id") is not None]
    accounts = {a.account_id: a for a in AccountRepository(session).list_by_ids(account_ids)}

    case_repo = CaseRepository(session)
    per_account_prior_case_ids: dict[str, set[str]] = defaultdict(set)
    all_prior_case_ids: set[str] = set()
    # Batched alert lookup (code-review finding, Phase 6 -- see the
    # `has_prior_sar` docstring bullet above): one `IN` query for every
    # node's alerts instead of one query per node.
    for alert in AlertRepository(session).list_for_primary_accounts(account_ids):
        if alert.case_id is None or alert.case_id == case_id:
            continue
        per_account_prior_case_ids[alert.primary_account_id].add(alert.case_id)
        all_prior_case_ids.add(alert.case_id)
    # Batched case lookup (same "no per-id round trip" idiom
    # `investigation.network_risk` uses for the same prior-SAR pattern).
    prior_cases = {c.case_id: c for c in case_repo.list_by_ids(list(all_prior_case_ids))}

    annotated: list[dict[str, Any]] = []
    for node in nodes:
        account_id = node.get("account_id")
        account = accounts.get(account_id)
        role_info = roles.get(account_id, {})
        has_prior_sar = any(
            prior_cases[cid].resolution == CaseResolution.TRUE_POSITIVE_SAR
            for cid in per_account_prior_case_ids.get(account_id, set())
            if cid in prior_cases
        )
        annotated.append(
            {
                "account_id": account_id,
                "branch_city": node.get("branch_city"),
                "role": role_info.get("role", "UNKNOWN"),
                "role_confidence": role_info.get("confidence", 0.0),
                "current_risk_score": (
                    float(account.current_risk_score)
                    if account is not None and account.current_risk_score is not None
                    else None
                ),
                "has_prior_sar": has_prior_sar,
                "hop_distance": hop_distances.get(account_id),
            }
        )
    return annotated


def apply_filters(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    center: str,
    filters: GraphFilters,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """ANDs every provided filter. Order matters (ROADMAP plan, verbatim):

      1. Edge-level filters (amount/date/channel/`suspicious_only`=
         `is_laundering==1`/`direction`) run first, over `edges`.
      2. Nodes are pruned to those touched by a surviving edge --
         `center` always survives THIS step (an isolated center, with every
         incident edge filtered out, must still appear in the response --
         it's the account being explored).
      3. Node-level filters (risk/role/prior-SAR) narrow further -- `center`
         is NOT exempt here; a `min_risk_score`/`roles`/`prior_sar_only`
         filter that excludes it excludes it, same as any other node.
      4. Any edge whose both endpoints got pruned by step 3 is dropped too.

    `direction` is well-defined only for edges touching `center` directly
    (`source_account == center` for `"out"`, `dest_account == center` for
    `"in"`) -- an edge 2+ hops away, not touching `center` at all, passes
    through unfiltered by `direction` (documented, not a bug: this filter
    has no meaningful "direction relative to center" for an edge that
    doesn't touch it). A self-loop ON `center` (`source_account ==
    dest_account == center`) is simultaneously incoming and outgoing to
    itself, so it passes EITHER `direction` filter (code-review finding,
    Phase 6: checking the `"out"` and `"in"` conditions sequentially, as if
    they were mutually exclusive, meant a self-loop tripped whichever
    condition ran second regardless of which `direction` was requested --
    unconditionally excluded either way, not "keep under at least one").
    """
    filtered_edges: list[dict[str, Any]] = []
    for edge in edges:
        if filters.suspicious_only and not edge.get("is_laundering"):
            continue
        amount = edge.get("amount")
        if filters.min_amount is not None and (amount is None or amount < filters.min_amount):
            continue
        if filters.max_amount is not None and (amount is None or amount > filters.max_amount):
            continue
        timestamp = edge.get("timestamp")
        if timestamp is not None:
            if filters.start is not None and timestamp < filters.start:
                continue
            if filters.end is not None and timestamp > filters.end:
                continue
        if filters.channels and str(edge.get("channel")) not in filters.channels:
            continue
        if filters.direction is not None:
            src, dst = edge.get("source_account"), edge.get("dest_account")
            if src == center and dst == center:
                pass  # self-loop on center satisfies both directions -- never filtered
            elif src == center and filters.direction != "out":
                continue
            elif dst == center and filters.direction != "in":
                continue
            # Neither endpoint is `center` -- passes through unfiltered by
            # `direction` (see docstring).
        filtered_edges.append(edge)

    touched_by_edge: set[Any] = {center}
    for edge in filtered_edges:
        touched_by_edge.add(edge.get("source_account"))
        touched_by_edge.add(edge.get("dest_account"))
    step2_nodes = [n for n in nodes if n.get("account_id") in touched_by_edge]

    filtered_nodes: list[dict[str, Any]] = []
    for node in step2_nodes:
        if filters.min_risk_score is not None:
            risk = node.get("current_risk_score")
            if risk is None or risk < filters.min_risk_score:
                continue
        if filters.roles and node.get("role") not in filters.roles:
            continue
        if filters.prior_sar_only and not node.get("has_prior_sar"):
            continue
        filtered_nodes.append(node)

    surviving_ids = {n.get("account_id") for n in filtered_nodes}
    final_edges = [
        edge
        for edge in filtered_edges
        if edge.get("source_account") in surviving_ids and edge.get("dest_account") in surviving_ids
    ]
    return filtered_nodes, final_edges


def _synthesize_center_node(session: Session, account_id: str) -> dict[str, Any]:
    """A minimal node entry for `center` when `NetworkXGraphStore.
    get_ego_graph` returns it with zero nodes -- happens when `center` is a
    case-linked account with no transactions anywhere in the case's
    transaction set. `NetworkXGraphStore._build()` only seeds isolated
    accounts-df nodes as a fallback when the WHOLE case's transaction set is
    empty (see that method's docstring); it does NOT seed a per-account
    isolated node when other case-linked accounts DO have transactions but
    this one doesn't, so `account_id not in self._G` is true and
    `get_ego_graph` returns `{"nodes": [], "edges": [], "center":
    account_id}` (code-review finding, Phase 6: this silently dropped the
    center account from the N-hop graph response entirely, breaking
    `apply_filters`' documented "`center` always survives" guarantee).

    Mirrors `NetworkXGraphStore._account_nodes`'s own shape exactly (the
    full account/customer-joined row when available, else a bare
    `{"account_id": ...}` placeholder matching that method's own fallback
    for an account_id with no matching `accounts` row) so `build_subgraph_
    store`/`annotate_nodes` treat this node identically to one the graph
    store itself would have produced."""
    account = AccountRepository(session).get(account_id)
    if account is None:
        return {"account_id": account_id}
    customer = (
        CustomerRepository(session).get(account.customer_id)
        if account.customer_id is not None
        else None
    )
    return {
        "account_id": account.account_id,
        "branch_city": account.branch_city,
        "declared_annual_income": (
            float(customer.declared_annual_income)
            if customer is not None and customer.declared_annual_income is not None
            else None
        ),
        "occupation": customer.occupation if customer is not None else None,
        "income_bracket": customer.income_bracket if customer is not None else None,
    }


def get_filtered_ego_graph(
    session: Session,
    case_id: str,
    account_id: str,
    *,
    radius: int,
    filters: GraphFilters,
    case_account_ids: list[str],
) -> dict[str, Any]:
    """Assemble the case-scoped graph store, extract the `radius`-hop
    ego-subgraph around `account_id`, annotate every node
    (`annotate_nodes`), apply `filters` (`apply_filters`), and return the
    denormalized-rich response shape. `radius` is clamped to `MAX_RADIUS`
    here too (defense-in-depth -- the real clamp is `api.routes.l2`'s route,
    but this function is also directly unit-testable/callable without going
    through HTTP, matching `orchestration.account_explanation.
    explain_account`'s "repeat the boundary check" precedent).

    If `account_id` has zero transactions anywhere in the case's
    transaction set, `get_ego_graph` returns it with an empty `nodes` list
    (see `_synthesize_center_node`'s docstring) -- synthesized here so
    `center` always appears in the response, even then."""
    radius = min(radius, MAX_RADIUS)
    graph = build_case_graph_store(session, case_account_ids)
    ego = graph.get_ego_graph(account_id, radius=radius)
    if not ego.get("nodes"):
        ego = {**ego, "nodes": [_synthesize_center_node(session, account_id)]}
    annotated_nodes = annotate_nodes(session, ego, case_id)
    filtered_nodes, filtered_edges = apply_filters(
        annotated_nodes, ego.get("edges", []), account_id, filters
    )
    return {
        "center": account_id,
        "radius": radius,
        "nodes": filtered_nodes,
        "edges": filtered_edges,
    }
