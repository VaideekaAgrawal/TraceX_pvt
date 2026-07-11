"""
Round-trip tests for `db.repositories.detection`: AlertRepository,
ModelRunRepository, RuleDefinitionRepository, RlArmStateRepository,
DetectionFeedbackRepository.
"""
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
    UserRole,
)
from db.repositories.detection import (
    AlertRepository,
    DetectionFeedbackRepository,
    ModelRunRepository,
    RlArmStateRepository,
    RuleDefinitionRepository,
)
from db.repositories.investigation import CaseRepository
from db.repositories.platform import UserRepository
from db.repositories.reference import AccountRepository

NOW = datetime(2026, 7, 1, tzinfo=UTC)


def _seed_account_and_user(session: Session) -> None:
    AccountRepository(session).create(account_id="A1", actor_type=ActorType.SYSTEM, actor_id=None)
    UserRepository(session).create(
        user_id="U1",
        username="inv1",
        email="inv1@example.com",
        password_hash="x",
        role=UserRole.INVESTIGATOR,
        full_name="Investigator One",
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    session.commit()


def test_alert_repository_round_trip(session: Session) -> None:
    _seed_account_and_user(session)
    CaseRepository(session).create(
        case_id="CASE1",
        primary_account_id="A1",
        status=CaseStatus.NEW,
        level=CaseLevel.L1,
        priority=Priority.P2,
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    repo = AlertRepository(session)
    repo.create(
        alert_id="AL1",
        detection_type=DetectionType.layering,
        primary_account_id="A1",
        account_ids=["A1"],
        score=0.8,
        risk_score=75.0,
        severity=RiskLevel.HIGH,
        priority=Priority.P1,
        status="open",
        source="pipeline",
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    session.commit()

    assert repo.get("AL1") is not None
    assert [a.alert_id for a in repo.list_unassigned()] == ["AL1"]
    assert [a.alert_id for a in repo.list_by_status("open")] == ["AL1"]

    # "Assignment" here means attaching a case (doc §3.2: `case_id` null
    # until a case is created) -- `list_unassigned()` tracks that, not the
    # freeform `status` text column, which is updated independently below.
    updated = repo.update(
        "AL1",
        case_id="CASE1",
        status="assigned",
        actor_type=ActorType.INVESTIGATOR,
        actor_id="U1",
    )
    session.commit()
    assert updated.status == "assigned"
    assert updated.case_id == "CASE1"
    assert repo.list_unassigned() == []
    assert [a.alert_id for a in repo.list_for_case("CASE1")] == ["AL1"]


def test_alert_repository_list_for_case_orders_by_risk_score_desc(session: Session) -> None:
    _seed_account_and_user(session)
    CaseRepository(session).create(
        case_id="CASE1",
        primary_account_id="A1",
        status=CaseStatus.NEW,
        level=CaseLevel.L1,
        priority=Priority.P2,
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    repo = AlertRepository(session)
    for alert_id, risk_score in [("AL_LOW", 10.0), ("AL_HIGH", 90.0), ("AL_MID", 50.0)]:
        repo.create(
            alert_id=alert_id,
            detection_type=DetectionType.layering,
            primary_account_id="A1",
            account_ids=["A1"],
            score=0.5,
            risk_score=risk_score,
            severity=RiskLevel.MEDIUM,
            priority=Priority.P3,
            status="open",
            source="pipeline",
            case_id="CASE1",
            actor_type=ActorType.SYSTEM,
            actor_id=None,
        )
    session.commit()

    assert [a.alert_id for a in repo.list_for_case("CASE1")] == ["AL_HIGH", "AL_MID", "AL_LOW"]


def test_alert_repository_list_for_primary_account_orders_by_created_at_desc(
    session: Session,
) -> None:
    _seed_account_and_user(session)
    AccountRepository(session).create(
        account_id="A2", actor_type=ActorType.SYSTEM, actor_id=None
    )
    session.commit()
    repo = AlertRepository(session)

    for alert_id, primary, created_at in [
        ("AL_OLD", "A1", datetime(2026, 1, 1, tzinfo=UTC)),
        ("AL_NEW", "A1", datetime(2026, 6, 1, tzinfo=UTC)),
        ("AL_OTHER", "A2", datetime(2026, 3, 1, tzinfo=UTC)),
    ]:
        repo.create(
            alert_id=alert_id,
            detection_type=DetectionType.layering,
            primary_account_id=primary,
            account_ids=[primary],
            score=0.5,
            risk_score=40.0,
            severity=RiskLevel.MEDIUM,
            priority=Priority.P3,
            status="open",
            source="pipeline",
            created_at=created_at,
            actor_type=ActorType.SYSTEM,
            actor_id=None,
        )
    session.commit()

    assert [a.alert_id for a in repo.list_for_primary_account("A1")] == ["AL_NEW", "AL_OLD"]
    assert [a.alert_id for a in repo.list_for_primary_account("A2")] == ["AL_OTHER"]
    assert repo.list_for_primary_account("NOPE") == []


def test_alert_repository_update_score_and_risk_score(session: Session) -> None:
    _seed_account_and_user(session)
    repo = AlertRepository(session)
    repo.create(
        alert_id="AL1",
        detection_type=DetectionType.layering,
        primary_account_id="A1",
        account_ids=["A1"],
        score=0.5,
        risk_score=40.0,
        severity=RiskLevel.MEDIUM,
        priority=Priority.P3,
        status="open",
        source="pipeline",
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    session.commit()

    updated = repo.update(
        "AL1", score=0.95, risk_score=88.0, actor_type=ActorType.SYSTEM, actor_id=None
    )
    session.commit()
    assert updated.score == 0.95
    assert updated.risk_score == 88.0


def test_alert_repository_mark_opened(session: Session) -> None:
    _seed_account_and_user(session)
    repo = AlertRepository(session)
    repo.create(
        alert_id="AL1",
        detection_type=DetectionType.layering,
        primary_account_id="A1",
        account_ids=["A1"],
        score=0.8,
        risk_score=75.0,
        severity=RiskLevel.HIGH,
        priority=Priority.P1,
        status="open",
        source="pipeline",
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    session.commit()

    from db.repositories.platform import AuditLogRepository

    repo.mark_opened("AL1", actor_type=ActorType.INVESTIGATOR, actor_id="U1")
    session.commit()

    alert = repo.get("AL1")
    assert alert is not None
    assert alert.status == "open"  # no domain-field change

    actions = [r.action for r in AuditLogRepository(session).list_for_entity("alert", "AL1")]
    assert "alert_opened" in actions


def test_model_run_repository_round_trip(session: Session) -> None:
    repo = ModelRunRepository(session)
    repo.create(
        run_id="MR1",
        model_name="ensemble_v1",
        model_type="ensemble",
        version="0.1.0",
        trained_at=NOW,
        metrics={"f1": 0.9},
        active=False,
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    session.commit()

    assert repo.list_active() == []
    updated = repo.update("MR1", active=True, actor_type=ActorType.SYSTEM, actor_id=None)
    session.commit()

    assert updated.active is True
    assert [r.run_id for r in repo.list_active()] == ["MR1"]
    assert repo.get_active_for_model("ensemble_v1") is not None
    assert repo.get_active_for_model("no_such_model") is None


def test_rule_definition_repository_round_trip(session: Session) -> None:
    repo = RuleDefinitionRepository(session)
    repo.create(
        rule_id="R1",
        name="high-velocity",
        dsl={"op": "and", "children": []},
        tier=1,
        confidence=0.5,
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    session.commit()

    assert repo.get("R1") is not None
    assert [r.rule_id for r in repo.list_enabled()] == ["R1"]
    assert [r.rule_id for r in repo.list_by_tier(1)] == ["R1"]

    updated = repo.update(
        "R1", enabled=False, confidence=0.75, actor_type=ActorType.SYSTEM, actor_id=None
    )
    session.commit()
    assert updated.enabled is False
    assert updated.confidence == 0.75
    assert repo.list_enabled() == []


def test_rl_arm_state_repository_upsert_round_trip(session: Session) -> None:
    repo = RlArmStateRepository(session)
    created = repo.upsert(
        arm_id="ARM1", a_matrix=[[1.0]], b_vector=[0.0], actor_type=ActorType.SYSTEM, actor_id=None
    )
    session.commit()
    assert created.a_matrix == [[1.0]]

    updated = repo.upsert(
        arm_id="ARM1",
        a_matrix=[[2.0]],
        b_vector=[1.0],
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    session.commit()

    assert updated.a_matrix == [[2.0]]
    assert updated.b_vector == [1.0]
    assert [s.arm_id for s in repo.list_all()] == ["ARM1"]


def test_detection_feedback_repository_round_trip(session: Session) -> None:
    _seed_account_and_user(session)
    CaseRepository(session).create(
        case_id="CASE1",
        primary_account_id="A1",
        status=CaseStatus.NEW,
        level=CaseLevel.L1,
        priority=Priority.P2,
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    session.commit()

    repo = DetectionFeedbackRepository(session)
    feedback = repo.create(
        case_id="CASE1",
        verdict=CaseResolution.TRUE_POSITIVE_SAR,
        reward=1.0,
        created_by="U1",
        actor_type=ActorType.INVESTIGATOR,
        actor_id="U1",
    )
    session.commit()

    assert repo.get(feedback.id) is not None
    assert [f.id for f in repo.list_for_case("CASE1")] == [feedback.id]
