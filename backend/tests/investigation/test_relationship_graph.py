"""
`investigation.relationship_graph.build_case_relationship_graph` -- pure
read over already-discovered `relationships` rows, scoped to a case's own
customers plus one hop out (ROADMAP Phase 7). Never runs discovery itself
-- rows are hand-seeded directly via `RelationshipRepository.create` here,
exercising only the read/assembly path.
"""
from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from db.enums import ActorType, CaseLevel, CaseStatus, EntityType, Priority, RiskLevel
from db.repositories.investigation import CaseRepository
from db.repositories.orchestration import RelationshipRepository
from db.repositories.reference import AccountRepository, CustomerRepository
from investigation.relationship_graph import build_case_relationship_graph


def _make_customer(session: Session, customer_id: str, name: str) -> None:
    CustomerRepository(session).create(
        customer_id=customer_id,
        name=name,
        entity_type=EntityType.INDIVIDUAL,
        risk_rating=RiskLevel.MEDIUM,
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )


def _make_account(session: Session, account_id: str, customer_id: str | None) -> None:
    AccountRepository(session).create(
        account_id=account_id, customer_id=customer_id,
        actor_type=ActorType.SYSTEM, actor_id=None,
    )


def _make_case(session: Session, case_id: str, primary_account_id: str) -> None:
    CaseRepository(session).create(
        case_id=case_id, primary_account_id=primary_account_id, status=CaseStatus.NEW,
        level=CaseLevel.L1, priority=Priority.P2, actor_type=ActorType.SYSTEM, actor_id=None,
    )


def test_returns_case_customers_and_one_hop_neighbors_with_edges(session: Session) -> None:
    _make_customer(session, "CUST_A", "Customer A")
    _make_customer(session, "CUST_B_HIDDEN", "Hidden Customer B")
    _make_customer(session, "CUST_C_UNRELATED", "Unrelated Customer C")
    _make_account(session, "ACC_A", "CUST_A")
    _make_case(session, "CASE1", "ACC_A")
    RelationshipRepository(session).create(
        entity_a="CUST_A", entity_b="CUST_B_HIDDEN", shared_attribute="pan",
        value_hash="hash1", confidence=0.95, method="shared_attribute_v1",
        actor_type=ActorType.SYSTEM, actor_id=None,
    )
    session.commit()

    result = build_case_relationship_graph(session, "CASE1", ["ACC_A"])

    assert result["case_id"] == "CASE1"
    nodes_by_id = {n["customer_id"]: n for n in result["nodes"]}
    assert nodes_by_id["CUST_A"]["in_case_scope"] is True
    assert nodes_by_id["CUST_B_HIDDEN"]["in_case_scope"] is False
    assert "CUST_C_UNRELATED" not in nodes_by_id

    assert len(result["edges"]) == 1
    edge = result["edges"][0]
    assert edge["shared_attribute"] == "pan"
    assert edge["confidence"] == 0.95
    assert "value_hash" not in edge  # never leaves this function


def test_no_discovered_relationships_returns_only_case_customers(session: Session) -> None:
    _make_customer(session, "CUST_SOLO", "Solo Customer")
    _make_account(session, "ACC_SOLO", "CUST_SOLO")
    _make_case(session, "CASE2", "ACC_SOLO")
    session.commit()

    result = build_case_relationship_graph(session, "CASE2", ["ACC_SOLO"])

    assert result["edges"] == []
    assert [n["customer_id"] for n in result["nodes"]] == ["CUST_SOLO"]
    assert result["nodes"][0]["in_case_scope"] is True


def test_account_with_no_customer_id_contributes_no_node(session: Session) -> None:
    _make_account(session, "ACC_NO_CUSTOMER", None)
    _make_case(session, "CASE3", "ACC_NO_CUSTOMER")
    session.commit()

    result = build_case_relationship_graph(session, "CASE3", ["ACC_NO_CUSTOMER"])

    assert result["nodes"] == []
    assert result["edges"] == []


def test_unknown_case_id_raises(session: Session) -> None:
    """Regression test (code-review finding, Phase 7): `build_case_
    relationship_graph` used to be the one sibling module (of three new
    Phase 7 modules) that silently returned an empty graph for an unknown
    `case_id` instead of raising, like `investigation.similar_cases.
    find_similar_cases`/`investigation.path_facts.
    compute_path_recommendation_facts` both do."""
    with pytest.raises(ValueError, match="does not exist"):
        build_case_relationship_graph(session, "NOPE", [])
