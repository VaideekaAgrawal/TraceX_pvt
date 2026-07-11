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
from db.repositories.investigation import CaseRepository
from db.repositories.reference import AccountRepository, CustomerRepository, TransactionRepository
from investigation.customer_profile import build_customer_profile


def test_build_customer_profile_excludes_self_from_siblings(session: Session) -> None:
    CustomerRepository(session).create(
        customer_id="CUST1", name="Jane Doe", entity_type=EntityType.INDIVIDUAL,
        risk_rating=RiskLevel.MEDIUM, occupation="Trader", declared_annual_income=600_000.0,
        income_bracket="5-10L", actor_type=ActorType.SYSTEM, actor_id=None,
    )
    account_repo = AccountRepository(session)
    account_repo.create(
        account_id="A1", customer_id="CUST1", current_risk_score=40.0,
        actor_type=ActorType.SYSTEM, actor_id=None,
    )
    account_repo.create(
        account_id="A2", customer_id="CUST1", current_risk_score=10.0,
        actor_type=ActorType.SYSTEM, actor_id=None,
    )
    session.commit()

    CaseRepository(session).create(
        case_id="CASE1", primary_account_id="A1", status=CaseStatus.IN_PROGRESS,
        level=CaseLevel.L2, priority=Priority.P2, actor_type=ActorType.SYSTEM, actor_id=None,
    )
    session.commit()

    profile = build_customer_profile(session, "CASE1", "A1")

    assert profile["account_id"] == "A1"
    assert profile["name"] == "Jane Doe"
    sibling_ids = {s["account_id"] for s in profile["sibling_accounts"]}
    assert sibling_ids == {"A2"}  # A1 itself excluded


def test_build_customer_profile_documents_omitted_fields(session: Session) -> None:
    AccountRepository(session).create(
        account_id="A1", actor_type=ActorType.SYSTEM, actor_id=None
    )
    session.commit()
    CaseRepository(session).create(
        case_id="CASE1", primary_account_id="A1", status=CaseStatus.IN_PROGRESS,
        level=CaseLevel.L2, priority=Priority.P2, actor_type=ActorType.SYSTEM, actor_id=None,
    )
    session.commit()

    profile = build_customer_profile(session, "CASE1", "A1")

    # No customer row linked -- every customer-sourced field is None, not a
    # crash.
    assert profile["customer_id"] is None
    assert profile["name"] is None
    assert profile["sibling_accounts"] == []
    assert set(profile["omitted_fields"]) == {
        "beneficial_owner", "linked_cards", "linked_loans", "linked_deposits",
        "risk_score_trend",
    }


def test_build_customer_profile_variance_ratio_math(session: Session) -> None:
    AccountRepository(session).create(
        account_id="A1", expected_monthly_volume=1_000.0,
        actor_type=ActorType.SYSTEM, actor_id=None,
    )
    AccountRepository(session).create(account_id="A2", actor_type=ActorType.SYSTEM, actor_id=None)
    session.commit()
    ts = datetime(2026, 1, 15, tzinfo=UTC)
    TransactionRepository(session).create(
        txn_id="T1", timestamp=ts, source_account="A1", dest_account="A2", amount=3_000.0,
        channel=Channel.NEFT, is_laundering=0, ingested_at=ts,
        actor_type=ActorType.SYSTEM, actor_id=None,
    )
    session.commit()
    CaseRepository(session).create(
        case_id="CASE1", primary_account_id="A1", status=CaseStatus.IN_PROGRESS,
        level=CaseLevel.L2, priority=Priority.P2, actor_type=ActorType.SYSTEM, actor_id=None,
    )
    session.commit()

    profile = build_customer_profile(session, "CASE1", "A1")

    assert profile["expected_monthly_volume"] == 1_000.0
    assert profile["actual_monthly_volume_avg"] == 3_000.0  # one month, all outflow
    assert profile["expected_vs_actual_variance_ratio"] == 3.0


def test_build_customer_profile_prior_sar_count(session: Session) -> None:
    AccountRepository(session).create(account_id="A1", actor_type=ActorType.SYSTEM, actor_id=None)
    session.commit()

    CaseRepository(session).create(
        case_id="OLD_CASE", primary_account_id="A1", status=CaseStatus.CLOSED_TP,
        level=CaseLevel.L1, priority=Priority.P1, actor_type=ActorType.SYSTEM, actor_id=None,
    )
    CaseRepository(session).update(
        "OLD_CASE", resolution=CaseResolution.TRUE_POSITIVE_SAR,
        actor_type=ActorType.SYSTEM, actor_id=None,
    )
    AlertRepository(session).create(
        alert_id="OLD_ALERT", detection_type=DetectionType.structuring,
        primary_account_id="A1", account_ids=["A1"], score=0.9, risk_score=90.0,
        severity=RiskLevel.CRITICAL, priority=Priority.P1, status="closed", source="pipeline",
        case_id="OLD_CASE", actor_type=ActorType.SYSTEM, actor_id=None,
    )
    session.commit()

    CaseRepository(session).create(
        case_id="CASE1", primary_account_id="A1", status=CaseStatus.IN_PROGRESS,
        level=CaseLevel.L2, priority=Priority.P2, actor_type=ActorType.SYSTEM, actor_id=None,
    )
    session.commit()

    profile = build_customer_profile(session, "CASE1", "A1")

    assert profile["prior_sar_count"] == 1
    assert profile["total_prior_alerts"] == 1
