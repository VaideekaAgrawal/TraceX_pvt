"""
`investigation.network_risk.compute_network_risk` -- rather than hardcoding
brittle expectations about exactly which accounts `RoleClassifier` calls
"MULE" or which nodes clear the centrality thresholds (both are pre-existing,
separately-tested Phase 3 ported components), these tests independently
recompute the same signals the function under test reads (roles, cycles,
centrality) from the same case-scoped graph, then assert
`compute_network_risk`'s output matches those signals run through the
documented formula. This verifies the aggregation/persistence logic this
module actually owns, without duplicating Phase 3's own role-classification
test coverage (`tests/detection/scoring/test_ensemble.py`).
"""
from __future__ import annotations

from datetime import UTC, datetime

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
from db.repositories.reference import AccountRepository, CustomerRepository, TransactionRepository
from detection.scoring.ensemble import (
    HIGH_BETWEENNESS_THRESHOLD,
    HIGH_PAGERANK_THRESHOLD,
    RoleClassifier,
)
from investigation.case_graph import build_case_graph_store
from investigation.network_risk import compute_network_risk


def _seed_txn(
    session: Session, txn_id: str, source: str, dest: str, amount: float, ts: datetime
) -> None:
    TransactionRepository(session).create(
        txn_id=txn_id,
        timestamp=ts,
        source_account=source,
        dest_account=dest,
        amount=amount,
        channel=Channel.NEFT,
        is_laundering=0,
        ingested_at=ts,
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )


def _seed_case_with_accounts(
    session: Session, case_id: str, primary_account_id: str, account_ids: list[str]
) -> None:
    CaseRepository(session).create(
        case_id=case_id,
        primary_account_id=primary_account_id,
        status=CaseStatus.IN_PROGRESS,
        level=CaseLevel.L1,
        priority=Priority.P2,
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    for account_id in account_ids:
        CaseAccountRepository(session).add_account(
            case_id=case_id,
            account_id=account_id,
            actor_type=ActorType.SYSTEM,
            actor_id=None,
        )


def test_compute_network_risk_matches_formula_and_persists(session: Session) -> None:
    account_repo = AccountRepository(session)
    for account_id in ("A", "B", "C"):
        account_repo.create(account_id=account_id, actor_type=ActorType.SYSTEM, actor_id=None)

    # A sanctioned customer linked to account A.
    CustomerRepository(session).create(
        customer_id="CUST_A",
        name="Sanctioned Co",
        entity_type=EntityType.BUSINESS,
        risk_rating=RiskLevel.CRITICAL,
        sanction_status=True,
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    account_repo.update("A", customer_id="CUST_A", actor_type=ActorType.SYSTEM, actor_id=None)
    session.commit()

    # 3-node round-trip cycle among the case's linked accounts.
    ts = datetime(2026, 1, 1, tzinfo=UTC)
    _seed_txn(session, "T1", "A", "B", 100_000.0, ts)
    _seed_txn(session, "T2", "B", "C", 95_000.0, ts)
    _seed_txn(session, "T3", "C", "A", 90_000.0, ts)
    session.commit()

    # A prior, already-closed TRUE_POSITIVE_SAR case with an alert whose
    # primary account (B) is also linked to the case under test.
    CaseRepository(session).create(
        case_id="OLD_CASE",
        primary_account_id="B",
        status=CaseStatus.CLOSED_TP,
        level=CaseLevel.L1,
        priority=Priority.P1,
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    CaseRepository(session).update(
        "OLD_CASE",
        resolution=CaseResolution.TRUE_POSITIVE_SAR,
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    AlertRepository(session).create(
        alert_id="OLD_ALERT",
        detection_type=DetectionType.round_trip,
        primary_account_id="B",
        account_ids=["B"],
        score=0.9,
        risk_score=95.0,
        severity=RiskLevel.CRITICAL,
        priority=Priority.P1,
        status="closed",
        source="pipeline",
        case_id="OLD_CASE",
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    session.commit()

    _seed_case_with_accounts(session, "CASE1", "A", ["A", "B", "C"])
    session.commit()

    case = compute_network_risk(
        session, "CASE1", actor_type=ActorType.INVESTIGATOR, actor_id="U1"
    )
    session.commit()

    # Independently recompute the same underlying signals from the same
    # case-scoped graph, then run them through the documented formula.
    graph = build_case_graph_store(session, ["A", "B", "C"])
    roles = RoleClassifier().classify_all(graph)
    expected_mule = sum(1 for r in roles.values() if r["role"] == "MULE")
    expected_cycles = len(graph.detect_cycles(max_length=8, max_cycles=50))
    centrality = graph.compute_centrality()
    expected_high_centrality = sum(
        1
        for account_id in ("A", "B", "C")
        if centrality["pagerank"].get(account_id, 0.0) > HIGH_PAGERANK_THRESHOLD
        or centrality["betweenness"].get(account_id, 0.0) > HIGH_BETWEENNESS_THRESHOLD
    )
    expected_sanctioned = 1
    expected_pep = 0
    expected_prior_sars = 1

    expected_mule_score = min(expected_mule * 6, 40)
    expected_sar_score = min(expected_prior_sars * 12, 30)
    expected_sanction_score = min(expected_sanctioned * 10 + expected_pep * 4, 20)
    expected_graph_score = min(expected_cycles * 8 + expected_high_centrality * 3, 20)
    expected_total = min(
        100.0,
        expected_mule_score + expected_sar_score + expected_sanction_score + expected_graph_score,
    )

    assert case.network_risk_score == expected_total
    reasons = case.network_risk_reasons
    assert reasons is not None
    assert reasons["mule_linked_accounts"] == expected_mule
    assert reasons["previous_sars"] == expected_prior_sars
    assert reasons["sanctioned_entities"] == expected_sanctioned
    assert reasons["pep_entities"] == expected_pep
    assert reasons["cycles_detected"] == expected_cycles
    assert reasons["high_centrality_accounts"] == expected_high_centrality
    assert "1 sanctioned entities" in reasons["summary"]
    assert "1 previous SARs" in reasons["summary"]

    # Persisted -- a fresh fetch sees the same values, not just the
    # in-memory return value.
    refetched = CaseRepository(session).get("CASE1")
    assert refetched is not None
    assert refetched.network_risk_score == expected_total
    assert refetched.network_risk_reasons == reasons


def test_compute_network_risk_all_zero_signals_gives_fallback_summary(session: Session) -> None:
    account_repo = AccountRepository(session)
    account_repo.create(account_id="A", actor_type=ActorType.SYSTEM, actor_id=None)
    session.commit()
    _seed_case_with_accounts(session, "CASE2", "A", ["A"])
    session.commit()

    case = compute_network_risk(
        session, "CASE2", actor_type=ActorType.SYSTEM, actor_id=None
    )
    session.commit()

    assert case.network_risk_score == 0.0
    assert case.network_risk_reasons is not None
    assert case.network_risk_reasons["summary"] == "No elevated network risk signals detected"
