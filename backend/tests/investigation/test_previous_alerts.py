from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from db.enums import (
    ActorType,
    CaseLevel,
    CaseResolution,
    CaseStatus,
    DetectionType,
    Priority,
    RiskLevel,
)
from db.repositories.detection import AlertRepository
from db.repositories.investigation import CaseRepository
from db.repositories.reference import AccountRepository
from investigation.previous_alerts import summarize


def _seed_account(session: Session, account_id: str) -> None:
    AccountRepository(session).create(
        account_id=account_id, actor_type=ActorType.SYSTEM, actor_id=None
    )


def _seed_case(
    session: Session,
    case_id: str,
    *,
    primary_account_id: str,
    resolution: CaseResolution | None,
) -> None:
    status = CaseStatus.CLOSED_TP if resolution is not None else CaseStatus.NEW
    CaseRepository(session).create(
        case_id=case_id,
        primary_account_id=primary_account_id,
        status=status,
        level=CaseLevel.L1,
        priority=Priority.P2,
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    if resolution is not None:
        CaseRepository(session).update(
            case_id, resolution=resolution, actor_type=ActorType.SYSTEM, actor_id=None
        )


def _seed_alert(
    session: Session,
    alert_id: str,
    *,
    primary_account_id: str,
    case_id: str,
    created_at: datetime,
    risk_score: float = 50.0,
) -> None:
    AlertRepository(session).create(
        alert_id=alert_id,
        detection_type=DetectionType.layering,
        primary_account_id=primary_account_id,
        account_ids=[primary_account_id],
        score=0.5,
        risk_score=risk_score,
        severity=RiskLevel.MEDIUM,
        priority=Priority.P3,
        status="open",
        source="pipeline",
        case_id=case_id,
        created_at=created_at,
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )


def test_summarize_counts_by_resolution_and_orders_risk_trend(session: Session) -> None:
    _seed_account(session, "A1")
    session.commit()

    _seed_case(
        session, "CASE_SAR", primary_account_id="A1", resolution=CaseResolution.TRUE_POSITIVE_SAR
    )
    _seed_case(
        session, "CASE_FP", primary_account_id="A1", resolution=CaseResolution.FALSE_POSITIVE
    )
    _seed_case(
        session,
        "CASE_MON",
        primary_account_id="A1",
        resolution=CaseResolution.ENHANCED_MONITORING,
    )
    _seed_case(session, "CASE_CURRENT", primary_account_id="A1", resolution=None)
    session.commit()

    _seed_alert(
        session, "AL_SAR", primary_account_id="A1", case_id="CASE_SAR",
        created_at=datetime(2026, 1, 1, tzinfo=UTC), risk_score=90.0,
    )
    _seed_alert(
        session, "AL_FP", primary_account_id="A1", case_id="CASE_FP",
        created_at=datetime(2026, 2, 1, tzinfo=UTC), risk_score=30.0,
    )
    _seed_alert(
        session, "AL_MON", primary_account_id="A1", case_id="CASE_MON",
        created_at=datetime(2026, 3, 1, tzinfo=UTC), risk_score=60.0,
    )
    _seed_alert(
        session, "AL_CURRENT", primary_account_id="A1", case_id="CASE_CURRENT",
        created_at=datetime(2026, 4, 1, tzinfo=UTC), risk_score=70.0,
    )
    session.commit()

    result = summarize(session, "A1", exclude_case_id="CASE_CURRENT")

    assert result["total_prior_alerts"] == 3
    assert result["prior_sar_count"] == 1
    assert result["prior_false_positive_count"] == 1
    assert result["prior_monitoring_count"] == 1
    assert [p["alert_id"] for p in result["risk_trend"]] == ["AL_SAR", "AL_FP", "AL_MON"]
    assert [p["risk_score"] for p in result["risk_trend"]] == [90.0, 30.0, 60.0]


def test_summarize_no_prior_alerts_returns_zeros(session: Session) -> None:
    _seed_account(session, "A2")
    session.commit()

    result = summarize(session, "A2")

    assert result == {
        "total_prior_alerts": 0,
        "prior_sar_count": 0,
        "prior_false_positive_count": 0,
        "prior_monitoring_count": 0,
        "risk_trend": [],
    }


def test_summarize_ignores_other_accounts_alerts(session: Session) -> None:
    _seed_account(session, "A1")
    _seed_account(session, "A2")
    session.commit()
    _seed_case(
        session, "CASE_A2", primary_account_id="A2", resolution=CaseResolution.TRUE_POSITIVE_SAR
    )
    session.commit()
    _seed_alert(
        session, "AL_A2", primary_account_id="A2", case_id="CASE_A2",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    session.commit()

    result = summarize(session, "A1")
    assert result["total_prior_alerts"] == 0
