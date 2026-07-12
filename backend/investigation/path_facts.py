"""
Investigation Path Recommendation -- data plumbing only (ROADMAP Phase 7,
`SYSTEM_DEVELOPMENT_PLAN.md` §4.1). Plain dataclasses, no Pydantic model,
no router import: Phase 8 (LLM gateway/tool layer) and Phase 9
(Recommendation Engine) don't exist yet to consume this as an HTTP-callable
tool -- `compute_path_recommendation_facts` is a pure internal module those
later phases will import directly, not a route.

Reuses existing computation only (`CLAUDE.md` "reuse before rebuild"),
assembling three fact groups:

  - **Fund-flow %**: `investigation.case_graph.shape_money_flow` +
    `add_flow_percentages`, centered on `case.primary_account_id`,
    radius=1 -- the same convention `GET .../money-flow` already uses.
  - **Shared-attribute adjacency**: `investigation.relationship_graph.
    build_case_relationship_graph`'s edges, passed through unchanged --
    this phase's own Relationship Explorer output, no new computation.
  - **Prior-SAR adjacency**: `investigation.graph_filters.annotate_nodes`'s
    `has_prior_sar`/`hop_distance` per node (ROADMAP Phase 6, already
    batched/perf-fixed).

Rather than calling `build_case_graph_store` + `get_ego_graph` +
`annotate_nodes` directly (which would skip the center-node-synthesis and
NaN-sanitization fixes Phase 6's code review already had to add once),
this module calls `graph_filters.get_filtered_ego_graph` -- the existing
public assembly function -- once, and derives BOTH the fund-flow edges and
the prior-SAR-annotated nodes from that single call. This avoids
re-deriving a pipeline whose edge cases were already found and fixed once.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy.orm import Session

from db.repositories.investigation import CaseAccountRepository, CaseRepository
from investigation.case_graph import add_flow_percentages, shape_money_flow
from investigation.graph_filters import GraphFilters, get_filtered_ego_graph
from investigation.relationship_graph import build_case_relationship_graph


@dataclass
class FundFlowFact:
    account_id: str
    direction: Literal["source", "beneficiary"]
    total_amount: float
    txn_count: int
    #: `pct_of_inflow` for a `"source"`, `pct_of_outflow` for a
    #: `"beneficiary"` (`investigation.case_graph.add_flow_percentages`).
    pct_of_total: float


@dataclass
class SharedAttributeAdjacencyFact:
    id: int
    entity_a: str
    entity_b: str
    shared_attribute: str
    confidence: float
    method: str
    discovered_at: datetime


@dataclass
class PriorSarAdjacencyFact:
    account_id: str
    has_prior_sar: bool
    hop_distance: int | None


@dataclass
class PathRecommendationFacts:
    case_id: str
    primary_account_id: str
    fund_flow: list[FundFlowFact]
    shared_attribute_adjacency: list[SharedAttributeAdjacencyFact]
    prior_sar_adjacency: list[PriorSarAdjacencyFact]


def compute_path_recommendation_facts(session: Session, case_id: str) -> PathRecommendationFacts:
    """Raises `ValueError` if `case_id` doesn't exist (matches this
    codebase's existing convention, e.g. `investigation.fsm.
    transition_case`). No route calls this -- pure internal module Phase 9
    will import directly later."""
    case = CaseRepository(session).get(case_id)
    if case is None:
        raise ValueError(f"case {case_id!r} does not exist")

    account_ids = CaseAccountRepository(session).list_account_ids_for_case(case_id)
    ego = get_filtered_ego_graph(
        session,
        case_id,
        case.primary_account_id,
        radius=1,
        filters=GraphFilters(),
        case_account_ids=account_ids,
    )

    shaped = add_flow_percentages(shape_money_flow(ego, case.primary_account_id))
    fund_flow = [
        FundFlowFact(
            account_id=source["account_id"],
            direction="source",
            total_amount=source["total_amount"],
            txn_count=source["txn_count"],
            pct_of_total=source["pct_of_inflow"],
        )
        for source in shaped["sources"]
    ] + [
        FundFlowFact(
            account_id=beneficiary["account_id"],
            direction="beneficiary",
            total_amount=beneficiary["total_amount"],
            txn_count=beneficiary["txn_count"],
            pct_of_total=beneficiary["pct_of_outflow"],
        )
        for beneficiary in shaped["beneficiaries"]
    ]

    relationship_graph = build_case_relationship_graph(session, case_id, account_ids)
    shared_attribute_adjacency = [
        SharedAttributeAdjacencyFact(
            id=edge["id"],
            entity_a=edge["entity_a"],
            entity_b=edge["entity_b"],
            shared_attribute=edge["shared_attribute"],
            confidence=edge["confidence"],
            method=edge["method"],
            discovered_at=edge["discovered_at"],
        )
        for edge in relationship_graph["edges"]
    ]

    prior_sar_adjacency = [
        PriorSarAdjacencyFact(
            account_id=node["account_id"],
            has_prior_sar=node["has_prior_sar"],
            hop_distance=node["hop_distance"],
        )
        for node in ego["nodes"]
    ]

    return PathRecommendationFacts(
        case_id=case_id,
        primary_account_id=case.primary_account_id,
        fund_flow=fund_flow,
        shared_attribute_adjacency=shared_attribute_adjacency,
        prior_sar_adjacency=prior_sar_adjacency,
    )
