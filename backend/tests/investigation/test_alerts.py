from __future__ import annotations

from sqlalchemy.orm import Session

from db.enums import ActorType, DetectionType, Priority, RiskLevel
from db.repositories.detection import AlertRepository
from db.repositories.reference import AccountRepository
from detection.types import DetectionResult
from investigation.alerts import generate_alerts_from_detection, make_deterministic_alert_id


def _seed_accounts(session: Session, *account_ids: str) -> None:
    repo = AccountRepository(session)
    for account_id in account_ids:
        repo.create(account_id=account_id, actor_type=ActorType.SYSTEM, actor_id=None)
    session.commit()


def test_make_deterministic_alert_id_is_stable_and_order_independent() -> None:
    id1 = make_deterministic_alert_id(["B", "A"], "layering", "2026-07-09")
    id2 = make_deterministic_alert_id(["A", "B"], "layering", "2026-07-09")
    assert id1 == id2
    assert id1.startswith("ALT-")
    assert len(id1) == len("ALT-") + 12


def test_make_deterministic_alert_id_differs_by_type_and_date() -> None:
    base = make_deterministic_alert_id(["A"], "layering", "2026-07-09")
    diff_type = make_deterministic_alert_id(["A"], "round_trip", "2026-07-09")
    diff_date = make_deterministic_alert_id(["A"], "layering", "2026-07-10")
    assert base != diff_type
    assert base != diff_date


def test_generate_alerts_creates_new_alert(session: Session) -> None:
    _seed_accounts(session, "A", "B")
    rule_results = {
        "layering": [
            DetectionResult(
                detection_type="layering",
                account_ids=["A", "B"],
                score=0.9,
                severity="HIGH",
                details={"total_amount": 2_000_000},
            )
        ]
    }
    ensemble_scores = {"A": 80.0, "B": 40.0}

    alerts = generate_alerts_from_detection(
        session,
        ensemble_scores,
        rule_results,
        model_run_id="RUN1",
        actor_type=ActorType.SYSTEM,
        actor_id=None,
        date_str="2026-07-09",
    )
    session.commit()

    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.detection_type == DetectionType.layering
    assert alert.primary_account_id == "A"  # higher ensemble score
    assert alert.risk_score == 80.0
    assert alert.severity == RiskLevel.HIGH
    assert alert.model_run_id == "RUN1"
    assert alert.status == "open"
    assert alert.account_ids == ["A", "B"]

    repo = AlertRepository(session)
    assert repo.get(alert.alert_id) is not None


def test_generate_alerts_refreshes_not_duplicates_on_rerun(session: Session) -> None:
    _seed_accounts(session, "A")
    rule_results = {
        "dormancy": [
            DetectionResult(
                detection_type="dormancy", account_ids=["A"], score=0.6, severity="MEDIUM"
            )
        ]
    }
    ensemble_scores = {"A": 50.0}

    first = generate_alerts_from_detection(
        session, ensemble_scores, rule_results, "RUN1",
        actor_type=ActorType.SYSTEM, actor_id=None, date_str="2026-07-09",
    )
    session.commit()
    assert len(first) == 1
    first_id = first[0].alert_id
    first_created_at = first[0].created_at
    first_last_seen = first[0].last_seen_at

    # Re-run "detection" for the same day -- must refresh, not duplicate.
    second = generate_alerts_from_detection(
        session, ensemble_scores, rule_results, "RUN2",
        actor_type=ActorType.SYSTEM, actor_id=None, date_str="2026-07-09",
    )
    session.commit()

    assert len(second) == 1
    assert second[0].alert_id == first_id
    assert second[0].created_at == first_created_at
    assert second[0].last_seen_at >= first_last_seen
    assert second[0].model_run_id == "RUN2"

    all_alerts = AlertRepository(session).list_by_status("open")
    assert len(all_alerts) == 1


def test_generate_alerts_skips_unknown_detection_type(session: Session) -> None:
    _seed_accounts(session, "A")
    rule_results = {
        "custom": [
            DetectionResult(
                detection_type="custom", account_ids=["A"], score=0.5, severity="MEDIUM"
            )
        ]
    }
    alerts = generate_alerts_from_detection(
        session, {"A": 30.0}, rule_results, None,
        actor_type=ActorType.SYSTEM, actor_id=None,
    )
    session.commit()
    assert alerts == []


def test_generate_alerts_confidence_scales_with_indicator_count(session: Session) -> None:
    _seed_accounts(session, "A")
    rule_results = {
        "layering": [
            DetectionResult(
                detection_type="layering", account_ids=["A"], score=0.9, severity="HIGH"
            )
        ],
        "round_trip": [
            DetectionResult(
                detection_type="round_trip", account_ids=["A"], score=0.8, severity="HIGH"
            )
        ],
    }
    ensemble_scores = {"A": 90.0}

    alerts = generate_alerts_from_detection(
        session, ensemble_scores, rule_results, None,
        actor_type=ActorType.SYSTEM, actor_id=None, date_str="2026-07-09",
    )
    session.commit()

    by_type = {str(a.detection_type): a for a in alerts}
    # Account "A" is flagged by 2 independent detection types -> Moderate (>=2).
    assert by_type["layering"].confidence == "Moderate"
    assert by_type["round_trip"].confidence == "Moderate"
    assert by_type["layering"].priority in {Priority.P1, Priority.P2, Priority.P3, Priority.P4}
