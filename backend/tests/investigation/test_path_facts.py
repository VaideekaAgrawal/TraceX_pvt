"""
`investigation.path_facts.compute_path_recommendation_facts` -- Investigation
Path Recommendation data plumbing (ROADMAP Phase 7). No route calls this;
these are unit tests of the pure internal assembly function. Reuses
`investigation.graph_filters.get_filtered_ego_graph` (fund-flow + prior-SAR
adjacency) and `investigation.relationship_graph.build_case_relationship_graph`
(shared-attribute adjacency) -- this module owns no computation of its own.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from db.enums import (
    ActorType,
    CaseLevel,
    CaseResolution,
    CaseStatus,
    Channel,
    DetectionType,
    EntityType,
    Priority,
    RiskLevel,
)
from db.repositories.detection import AlertRepository
from db.repositories.investigation import CaseAccountRepository, CaseRepository
from db.repositories.orchestration import RelationshipRepository
from db.repositories.reference import AccountRepository, CustomerRepository, TransactionRepository
from investigation.path_facts import compute_path_recommendation_facts

TS = datetime(2026, 1, 1, tzinfo=UTC)


def _seed_txn(session: Session, txn_id: str, source: str, dest: str, amount: float) -> None:
    TransactionRepository(session).create(
        txn_id=txn_id, timestamp=TS, source_account=source, dest_account=dest,
        amount=amount, channel=Channel.NEFT, is_laundering=0, ingested_at=TS,
        actor_type=ActorType.SYSTEM, actor_id=None,
    )


def _seed_customer(session: Session, customer_id: str, name: str) -> None:
    CustomerRepository(session).create(
        customer_id=customer_id, name=name, entity_type=EntityType.INDIVIDUAL,
        risk_rating=RiskLevel.MEDIUM, actor_type=ActorType.SYSTEM, actor_id=None,
    )


def _seed_case(
    session: Session, case_id: str, primary_account_id: str, account_ids: list[str]
) -> None:
    CaseRepository(session).create(
        case_id=case_id, primary_account_id=primary_account_id, status=CaseStatus.IN_PROGRESS,
        level=CaseLevel.L2, priority=Priority.P1, actor_type=ActorType.SYSTEM, actor_id=None,
    )
    for account_id in account_ids:
        CaseAccountRepository(session).add_account(
            case_id=case_id, account_id=account_id, actor_type=ActorType.SYSTEM, actor_id=None
        )


def test_compute_path_recommendation_facts_full_scenario(session: Session) -> None:
    for account_id, customer_id in (("SRC", "CUST_SRC"), ("MULE", None), ("SINK", "CUST_SINK")):
        AccountRepository(session).create(
            account_id=account_id, customer_id=customer_id,
            actor_type=ActorType.SYSTEM, actor_id=None,
        )
    _seed_customer(session, "CUST_SRC", "Source Customer")
    _seed_customer(session, "CUST_SINK", "Sink Customer")
    _seed_customer(session, "CUST_HIDDEN", "Hidden Linked Customer")
    RelationshipRepository(session).create(
        entity_a="CUST_HIDDEN", entity_b="CUST_SRC", shared_attribute="pan",
        value_hash="deadbeef", confidence=0.95, method="shared_attribute_v1",
        actor_type=ActorType.SYSTEM, actor_id=None,
    )

    # Prior, closed TRUE_POSITIVE_SAR case sharing SINK -- network-wide
    # prior-SAR signal.
    CaseRepository(session).create(
        case_id="OLD_CASE", primary_account_id="SINK", status=CaseStatus.CLOSED_TP,
        level=CaseLevel.L1, priority=Priority.P1, actor_type=ActorType.SYSTEM, actor_id=None,
    )
    CaseRepository(session).update(
        "OLD_CASE", resolution=CaseResolution.TRUE_POSITIVE_SAR,
        actor_type=ActorType.SYSTEM, actor_id=None,
    )
    AlertRepository(session).create(
        alert_id="OLD_ALERT", detection_type=DetectionType.round_trip,
        primary_account_id="SINK", account_ids=["SINK"], score=0.9, risk_score=95.0,
        severity=RiskLevel.CRITICAL, priority=Priority.P1, status="closed", source="pipeline",
        case_id="OLD_CASE", actor_type=ActorType.SYSTEM, actor_id=None,
    )

    _seed_txn(session, "T1", "SRC", "MULE", 100.0)
    _seed_txn(session, "T2", "MULE", "SINK", 90.0)

    _seed_case(session, "CASE1", "SRC", ["SRC", "MULE", "SINK"])
    session.commit()

    facts = compute_path_recommendation_facts(session, "CASE1")

    assert facts.case_id == "CASE1"
    assert facts.primary_account_id == "SRC"

    # radius=1 around SRC: only the SRC->MULE edge is within reach.
    beneficiaries = {f.account_id: f for f in facts.fund_flow if f.direction == "beneficiary"}
    assert beneficiaries["MULE"].total_amount == 100.0
    assert beneficiaries["MULE"].pct_of_total == 100.0
    assert all(f.direction != "source" for f in facts.fund_flow)  # SRC has no inflow

    assert len(facts.shared_attribute_adjacency) == 1
    adjacency = facts.shared_attribute_adjacency[0]
    assert {adjacency.entity_a, adjacency.entity_b} == {"CUST_HIDDEN", "CUST_SRC"}
    assert adjacency.shared_attribute == "pan"

    # SINK (prior TP-SAR) is 2 hops from SRC -- outside radius=1, so it must
    # NOT appear in the prior_sar_adjacency computed at this radius; MULE
    # (1 hop, no prior SAR of its own) must.
    prior_sar_by_id = {f.account_id: f for f in facts.prior_sar_adjacency}
    assert "SINK" not in prior_sar_by_id
    assert prior_sar_by_id["MULE"].has_prior_sar is False
    assert prior_sar_by_id["SRC"].hop_distance == 0
    assert prior_sar_by_id["MULE"].hop_distance == 1


def test_compute_path_recommendation_facts_zero_transaction_primary_account(
    session: Session,
) -> None:
    """No crash/div-by-zero on a case-linked primary account with zero
    transactions anywhere in the case's transaction set (the same edge case
    Phase 6's `_synthesize_center_node` fix handles for the N-hop route)."""
    AccountRepository(session).create(
        account_id="LONE", actor_type=ActorType.SYSTEM, actor_id=None
    )
    _seed_case(session, "CASE2", "LONE", ["LONE"])
    session.commit()

    facts = compute_path_recommendation_facts(session, "CASE2")

    assert facts.fund_flow == []
    assert facts.shared_attribute_adjacency == []
    assert len(facts.prior_sar_adjacency) == 1
    assert facts.prior_sar_adjacency[0].account_id == "LONE"
    assert facts.prior_sar_adjacency[0].has_prior_sar is False


def test_compute_path_recommendation_facts_raises_on_unknown_case(session: Session) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        compute_path_recommendation_facts(session, "NOPE")
