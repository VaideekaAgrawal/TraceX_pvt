"""
Relationship Explorer v1 -- read-only case-scoped view over already-
discovered `relationships` rows (ROADMAP Phase 7, `SYSTEM_DEVELOPMENT_
PLAN.md` §4.2). Pure read: this module never runs discovery itself (that's
`investigation.relationship_discovery`'s job, invoked as a separate global
batch); it only assembles the "hidden mule network" view for one case from
whatever the discovery job has already written.

Scoped to the case's own customers PLUS one hop out -- the whole point of
Relationship Explorer is surfacing a customer NOT otherwise linked to this
case (no shared transaction, no `case_accounts` row) but sharing a PAN/
name/income-bracket/branch with one who is. Those 1-hop customers are
intentionally outside `case_accounts`' normal RBAC boundary -- documented as
the feature working as designed (same posture as `graph_filters.
annotate_nodes`'s network-wide `has_prior_sar` reach, ROADMAP Phase 6), not
a scope leak: a relationship discovered between a case's own customer and
someone else is exactly the fact this feature exists to reveal.

`value_hash` never leaves `build_case_relationship_graph` -- it's a
one-way hash of a PII value, useless to a client and not part of this
function's return shape.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from db.repositories.investigation import CaseRepository
from db.repositories.orchestration import RelationshipRepository
from db.repositories.reference import AccountRepository, CustomerRepository


def build_case_relationship_graph(
    session: Session, case_id: str, case_account_ids: list[str]
) -> dict[str, Any]:
    """`case_account_ids` -- the case-scoping id set (e.g. `CaseAccount
    Repository.list_account_ids_for_case(case_id)`, same as every other
    case-scoped assembly function in this package) -- is resolved to its
    customers, every already-discovered relationship touching any of them
    is pulled (`RelationshipRepository.list_for_entities`), and the 1-hop
    customers those relationships reach are unioned in. Returns:

        {
            "case_id": ...,
            "nodes": [{"customer_id", "name", "in_case_scope"}, ...],
            "edges": [{"id", "entity_a", "entity_b", "shared_attribute",
                       "confidence", "method", "discovered_at"}, ...],
        }

    Raises `ValueError` if `case_id` doesn't exist -- matches the same
    contract `investigation.similar_cases.find_similar_cases`/`investigation.
    path_facts.compute_path_recommendation_facts` already establish for an
    unknown case_id (code-review finding, Phase 7: this function used to be
    the one sibling module that silently returned an empty graph instead)."""
    if CaseRepository(session).get(case_id) is None:
        raise ValueError(f"case {case_id!r} does not exist")

    accounts = AccountRepository(session).list_by_ids(case_account_ids)
    case_customer_ids = {a.customer_id for a in accounts if a.customer_id is not None}

    relationships = RelationshipRepository(session).list_for_entities(list(case_customer_ids))

    one_hop_customer_ids: set[str] = set()
    for rel in relationships:
        one_hop_customer_ids.add(rel.entity_a)
        one_hop_customer_ids.add(rel.entity_b)

    all_customer_ids = case_customer_ids | one_hop_customer_ids
    customers = CustomerRepository(session).list_by_ids(list(all_customer_ids))

    nodes = [
        {
            "customer_id": customer.customer_id,
            "name": customer.name,
            "in_case_scope": customer.customer_id in case_customer_ids,
        }
        for customer in customers
    ]
    edges = [
        {
            "id": rel.id,
            "entity_a": rel.entity_a,
            "entity_b": rel.entity_b,
            "shared_attribute": rel.shared_attribute,
            "confidence": rel.confidence,
            "method": rel.method,
            "discovered_at": rel.discovered_at,
        }
        for rel in relationships
    ]

    return {"case_id": case_id, "nodes": nodes, "edges": edges}
