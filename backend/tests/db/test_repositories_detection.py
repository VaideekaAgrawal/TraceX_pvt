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
    ALERT_SORT_KEYS,
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


def test_alert_repository_list_for_primary_accounts_batched(session: Session) -> None:
    """`list_for_primary_accounts` (code-review finding, Phase 6 -- added
    so `investigation.graph_filters.annotate_nodes` doesn't call
    `list_for_primary_account` once per ego-graph node): one `IN` query
    covering every requested account at once."""
    _seed_account_and_user(session)
    AccountRepository(session).create(
        account_id="A2", actor_type=ActorType.SYSTEM, actor_id=None
    )
    AccountRepository(session).create(
        account_id="A3", actor_type=ActorType.SYSTEM, actor_id=None
    )
    session.commit()
    repo = AlertRepository(session)

    for alert_id, primary in [("AL_A1", "A1"), ("AL_A2", "A2")]:
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
            actor_type=ActorType.SYSTEM,
            actor_id=None,
        )
    session.commit()

    result = repo.list_for_primary_accounts(["A1", "A2", "A3"])
    assert {a.alert_id for a in result} == {"AL_A1", "AL_A2"}
    assert repo.list_for_primary_accounts(["A3"]) == []
    assert repo.list_for_primary_accounts([]) == []


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


# ── ROADMAP Phase 14: list_filtered/count_filtered/dashboard aggregates ────


def _seed_alert(
    session: Session,
    alert_id: str,
    *,
    primary_account_id: str = "A1",
    risk_score: float = 50.0,
    severity: RiskLevel = RiskLevel.MEDIUM,
    priority: Priority = Priority.P3,
    detection_type: DetectionType = DetectionType.layering,
    status: str = "open",
    case_id: str | None = None,
    created_at: datetime | None = None,
) -> None:
    AlertRepository(session).create(
        alert_id=alert_id,
        detection_type=detection_type,
        primary_account_id=primary_account_id,
        account_ids=[primary_account_id],
        score=0.5,
        risk_score=risk_score,
        severity=severity,
        priority=priority,
        status=status,
        source="pipeline",
        case_id=case_id,
        created_at=created_at,
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )


def test_alert_sort_keys_matches_private_list_sorts() -> None:
    assert ALERT_SORT_KEYS == set(AlertRepository._LIST_SORTS)
    assert "risk_score_desc" in ALERT_SORT_KEYS
    assert "created_at_asc" in ALERT_SORT_KEYS
    assert "priority_desc" in ALERT_SORT_KEYS


def test_list_filtered_by_status_priority_severity_detection_type(session: Session) -> None:
    _seed_account_and_user(session)
    session.commit()
    _seed_alert(
        session, "AL_MATCH", severity=RiskLevel.HIGH, priority=Priority.P1,
        detection_type=DetectionType.round_trip, status="open",
    )
    _seed_alert(
        session, "AL_OTHER", severity=RiskLevel.LOW, priority=Priority.P4,
        detection_type=DetectionType.layering, status="assigned",
    )
    session.commit()

    repo = AlertRepository(session)
    result = repo.list_filtered(
        status="open",
        priority=Priority.P1,
        severity=RiskLevel.HIGH,
        detection_type=DetectionType.round_trip,
    )
    assert [a.alert_id for a in result] == ["AL_MATCH"]
    assert repo.count_filtered(
        status="open",
        priority=Priority.P1,
        severity=RiskLevel.HIGH,
        detection_type=DetectionType.round_trip,
    ) == 1


def test_list_filtered_by_risk_score_range_and_date_range(session: Session) -> None:
    _seed_account_and_user(session)
    session.commit()
    _seed_alert(session, "AL_LOW", risk_score=10.0, created_at=datetime(2026, 1, 1, tzinfo=UTC))
    _seed_alert(session, "AL_MID", risk_score=50.0, created_at=datetime(2026, 2, 1, tzinfo=UTC))
    _seed_alert(session, "AL_HIGH", risk_score=90.0, created_at=datetime(2026, 3, 1, tzinfo=UTC))
    session.commit()

    repo = AlertRepository(session)
    assert {a.alert_id for a in repo.list_filtered(min_risk_score=40.0, max_risk_score=95.0)} == {
        "AL_MID",
        "AL_HIGH",
    }
    assert {
        a.alert_id
        for a in repo.list_filtered(
            start=datetime(2026, 1, 15, tzinfo=UTC), end=datetime(2026, 2, 15, tzinfo=UTC)
        )
    } == {"AL_MID"}
    assert repo.count_filtered(min_risk_score=40.0, max_risk_score=95.0) == 2


def test_list_filtered_unassigned_only_and_assigned_to(session: Session) -> None:
    _seed_account_and_user(session)
    CaseRepository(session).create(
        case_id="CASE1",
        primary_account_id="A1",
        status=CaseStatus.NEW,
        level=CaseLevel.L1,
        priority=Priority.P2,
        assigned_to="U1",
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    session.commit()
    _seed_alert(session, "AL_UNASSIGNED", case_id=None)
    _seed_alert(session, "AL_ASSIGNED", case_id="CASE1")
    session.commit()

    repo = AlertRepository(session)
    assert [a.alert_id for a in repo.list_filtered(unassigned_only=True)] == ["AL_UNASSIGNED"]
    assert [a.alert_id for a in repo.list_filtered(assigned_to="U1")] == ["AL_ASSIGNED"]
    assert repo.list_filtered(assigned_to="NOBODY") == []
    assert repo.count_filtered(unassigned_only=True) == 1


def test_list_filtered_sort_none_returns_full_set_unordered_no_limit(session: Session) -> None:
    _seed_account_and_user(session)
    session.commit()
    for i in range(5):
        _seed_alert(session, f"AL{i}", risk_score=float(i))
    session.commit()

    repo = AlertRepository(session)
    result = repo.list_filtered(sort=None, limit=2)  # limit ignored when sort is None
    assert {a.alert_id for a in result} == {f"AL{i}" for i in range(5)}


def test_list_filtered_sort_applies_order_and_limit_offset(session: Session) -> None:
    _seed_account_and_user(session)
    session.commit()
    for i in range(5):
        _seed_alert(session, f"AL{i}", risk_score=float(i))
    session.commit()

    repo = AlertRepository(session)
    result = repo.list_filtered(sort="risk_score_desc", limit=2)
    assert [a.alert_id for a in result] == ["AL4", "AL3"]

    page2 = repo.list_filtered(sort="risk_score_desc", limit=2, offset=2)
    assert [a.alert_id for a in page2] == ["AL2", "AL1"]

    all_asc = repo.list_filtered(sort="risk_score_asc")
    assert [a.alert_id for a in all_asc] == ["AL0", "AL1", "AL2", "AL3", "AL4"]


def test_list_filtered_and_count_filtered_empty_result(session: Session) -> None:
    repo = AlertRepository(session)
    assert repo.list_filtered(status="open") == []
    assert repo.count_filtered(status="open") == 0


def test_count_active_and_grouped_by_severity_and_avg_risk_score(session: Session) -> None:
    _seed_account_and_user(session)
    session.commit()
    _seed_alert(session, "AL1", severity=RiskLevel.HIGH, risk_score=80.0, status="open")
    _seed_alert(session, "AL2", severity=RiskLevel.HIGH, risk_score=60.0, status="assigned")
    _seed_alert(session, "AL3", severity=RiskLevel.LOW, risk_score=10.0, status="closed")
    session.commit()

    repo = AlertRepository(session)
    # "closed" excludes AL3 from every active-only aggregate.
    assert repo.count_active() == 2
    assert repo.count_active_grouped_by_severity() == {"HIGH": 2}
    assert repo.avg_active_risk_score() == 70.0


def test_avg_active_risk_score_returns_none_when_no_active_alerts(session: Session) -> None:
    repo = AlertRepository(session)
    assert repo.avg_active_risk_score() is None
    assert repo.count_active_grouped_by_severity() == {}


def test_count_by_day_buckets_by_utc_calendar_day_and_excludes_before_since(
    session: Session,
) -> None:
    _seed_account_and_user(session)
    session.commit()
    _seed_alert(session, "AL_D1_A", created_at=datetime(2026, 6, 1, 3, 0, tzinfo=UTC))
    _seed_alert(session, "AL_D1_B", created_at=datetime(2026, 6, 1, 23, 0, tzinfo=UTC))
    _seed_alert(session, "AL_D2", created_at=datetime(2026, 6, 2, 12, 0, tzinfo=UTC))
    _seed_alert(session, "AL_TOO_OLD", created_at=datetime(2026, 5, 1, tzinfo=UTC))
    session.commit()

    repo = AlertRepository(session)
    result = repo.count_by_day(since=datetime(2026, 6, 1, tzinfo=UTC))
    assert result == [("2026-06-01", 2), ("2026-06-02", 1)]


def test_count_by_day_empty_result(session: Session) -> None:
    repo = AlertRepository(session)
    assert repo.count_by_day(since=datetime(2026, 1, 1, tzinfo=UTC)) == []
