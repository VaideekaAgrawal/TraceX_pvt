from __future__ import annotations

from sqlalchemy.orm import Session

from db.enums import ActorType, DetectionType, Priority, RiskLevel
from db.repositories.detection import AlertRepository
from db.repositories.reference import AccountRepository
from investigation.prioritization import _RL_CANDIDATE_CAP, rank_alert_queue


def _seed_account(session: Session, account_id: str) -> None:
    AccountRepository(session).create(
        account_id=account_id, actor_type=ActorType.SYSTEM, actor_id=None
    )


def _make_alert(
    session: Session,
    alert_id: str,
    *,
    account_id: str,
    risk_score: float,
    detection_type: DetectionType = DetectionType.layering,
):
    return AlertRepository(session).create(
        alert_id=alert_id,
        detection_type=detection_type,
        primary_account_id=account_id,
        account_ids=[account_id],
        score=0.5,
        risk_score=risk_score,
        severity=RiskLevel.MEDIUM,
        priority=Priority.P3,
        status="open",
        source="pipeline",
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )


def test_rank_alert_queue_empty_input_returns_empty(session: Session) -> None:
    assert rank_alert_queue(session, []) == []


def test_rank_alert_queue_returns_every_alert(session: Session) -> None:
    _seed_account(session, "A")
    _seed_account(session, "B")
    a1 = _make_alert(session, "AL1", account_id="A", risk_score=90.0)
    a2 = _make_alert(session, "AL2", account_id="B", risk_score=10.0)
    session.commit()

    ranked = rank_alert_queue(session, [a1, a2])
    assert {a.alert_id for a in ranked} == {"AL1", "AL2"}


def test_rank_alert_queue_groups_same_account_alerts_together(session: Session) -> None:
    _seed_account(session, "A")
    _seed_account(session, "B")
    a1 = _make_alert(
        session, "AL1", account_id="A", risk_score=95.0, detection_type=DetectionType.layering
    )
    a2 = _make_alert(
        session, "AL2", account_id="A", risk_score=85.0, detection_type=DetectionType.round_trip
    )
    a3 = _make_alert(session, "AL3", account_id="B", risk_score=5.0)
    session.commit()

    ranked = rank_alert_queue(session, [a1, a2, a3])
    ranked_ids = [a.alert_id for a in ranked]
    # Both of account "A"'s alerts must stay adjacent (same ranked block).
    assert ranked_ids.index("AL2") == ranked_ids.index("AL1") + 1


def test_rank_alert_queue_caps_reranking_at_candidate_cap(session: Session) -> None:
    """Beyond `_RL_CANDIDATE_CAP` alerts, the overflow is returned unranked
    (in original risk_score-descending order) rather than dropped or forced
    through the (expensive) bandit scoring path."""
    total = _RL_CANDIDATE_CAP + 5
    alerts = []
    for i in range(total):
        account_id = f"ACC{i:04d}"
        _seed_account(session, account_id)
        # Descending risk_score so index 0 is highest.
        alert = _make_alert(
            session, f"AL{i:04d}", account_id=account_id, risk_score=float(total - i)
        )
        alerts.append(alert)
    session.commit()

    ranked = rank_alert_queue(session, alerts)
    assert len(ranked) == total

    # The lowest-risk_score alerts (the last 5, beyond the cap) must appear
    # at the tail, in their original risk_score-descending relative order.
    overflow_ids = [a.alert_id for a in alerts[_RL_CANDIDATE_CAP:]]
    assert [a.alert_id for a in ranked[_RL_CANDIDATE_CAP:]] == overflow_ids


def test_rank_alert_queue_prefers_higher_risk_score_absent_learned_signal(session: Session) -> None:
    """With a fresh (untrained) bandit, UCB scores are driven mostly by
    uncertainty/risk_score_norm -- a much higher risk_score account should
    still generally rank at or near the top."""
    _seed_account(session, "HIGH")
    _seed_account(session, "LOW")
    high = _make_alert(session, "AL_HIGH", account_id="HIGH", risk_score=95.0)
    low = _make_alert(session, "AL_LOW", account_id="LOW", risk_score=2.0)
    session.commit()

    ranked = rank_alert_queue(session, [low, high])
    assert ranked[0].alert_id == "AL_HIGH"
