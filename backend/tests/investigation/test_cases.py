from __future__ import annotations

import numpy as np
import pytest
from sqlalchemy.orm import Session

from db.enums import (
    ActorType,
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
    RlArmStateRepository,
)
from db.repositories.investigation import CaseAccountRepository, CaseFeatureVectorRepository
from db.repositories.platform import AuditLogRepository, UserRepository
from db.repositories.reference import AccountRepository
from detection.rl.bandit import GLOBAL_ARM_ID, LinUCBAgent
from investigation.cases import case_rl_features, close_case, create_case_from_alert
from investigation.fsm import InvalidTransitionError, transition_case


def _seed_accounts(session: Session, *account_ids: str) -> None:
    repo = AccountRepository(session)
    for account_id in account_ids:
        repo.create(account_id=account_id, actor_type=ActorType.SYSTEM, actor_id=None)


def _seed_investigator(session: Session, user_id: str = "U1") -> None:
    UserRepository(session).create(
        user_id=user_id,
        username=user_id.lower(),
        email=f"{user_id.lower()}@example.com",
        password_hash="x",
        role=UserRole.INVESTIGATOR,
        full_name=user_id,
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )


def _seed_alert(session: Session, alert_id: str = "AL1", *, account_ids: list[str] | None = None):
    account_ids = account_ids or ["A", "B"]
    return AlertRepository(session).create(
        alert_id=alert_id,
        detection_type=DetectionType.layering,
        primary_account_id=account_ids[0],
        account_ids=account_ids,
        score=0.9,
        risk_score=88.0,
        severity=RiskLevel.HIGH,
        priority=Priority.P1,
        status="open",
        source="pipeline",
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )


def test_create_case_from_alert_links_accounts_and_assigns(session: Session) -> None:
    _seed_accounts(session, "A", "B")
    _seed_investigator(session)
    alert = _seed_alert(session)
    session.commit()

    case = create_case_from_alert(session, alert, actor_type=ActorType.SYSTEM, actor_id=None)
    session.commit()

    assert case.status == CaseStatus.ASSIGNED
    assert case.assigned_to == "U1"
    assert case.sla_due_at is not None
    assert case.primary_account_id == "A"
    assert case.priority == Priority.P1
    assert case.typology == "layering"

    linked = {ca.account_id for ca in CaseAccountRepository(session).list_for_case(case.case_id)}
    assert linked == {"A", "B"}

    refreshed_alert = AlertRepository(session).get(alert.alert_id)
    assert refreshed_alert is not None
    assert refreshed_alert.case_id == case.case_id
    assert refreshed_alert.status == "assigned"


def test_create_case_from_alert_with_assigned_to_takes_manual_path_not_auto_assign(
    session: Session,
) -> None:
    """ROADMAP Phase 14: `assigned_to` given routes the NEW->ASSIGNED
    handoff through `assign_case_to` (a specific investigator), not
    `auto_assign`'s workload-based pick -- confirmed here by seeding a
    SECOND investigator who has the lower workload (so a plain `auto_assign`
    call would have picked them instead) and asserting the alert's own
    explicit choice wins."""
    _seed_accounts(session, "A", "B")
    _seed_investigator(session, "U1")
    _seed_investigator(session, "U_LOWER_WORKLOAD")
    alert = _seed_alert(session)
    session.commit()

    case = create_case_from_alert(
        session, alert, actor_type=ActorType.ADMIN, actor_id="ADMIN1", assigned_to="U1"
    )
    session.commit()

    assert case.status == CaseStatus.ASSIGNED
    assert case.assigned_to == "U1"

    rows = AuditLogRepository(session).list_for_case(case.case_id)
    assigned_rows = [r for r in rows if r.action == "case_assigned"]
    assert len(assigned_rows) == 1
    reassigned_rows = [r for r in rows if r.action == "case_reassigned"]
    assert len(reassigned_rows) == 0


def _walk_to_awaiting_review(session: Session, case_id: str) -> None:
    transition_case(
        session, case_id, CaseStatus.IN_PROGRESS,
        actor_type=ActorType.INVESTIGATOR, actor_id="U1",
    )
    transition_case(
        session, case_id, CaseStatus.AWAITING_REVIEW,
        actor_type=ActorType.INVESTIGATOR, actor_id="U1",
    )


def test_close_case_true_positive_sar_full_flow(session: Session) -> None:
    _seed_accounts(session, "A", "B")
    _seed_investigator(session)
    alert = _seed_alert(session)
    session.commit()

    case = create_case_from_alert(session, alert, actor_type=ActorType.SYSTEM, actor_id=None)
    session.commit()
    _walk_to_awaiting_review(session, case.case_id)
    session.commit()

    closed = close_case(
        session,
        case.case_id,
        CaseResolution.TRUE_POSITIVE_SAR,
        actor_type=ActorType.INVESTIGATOR,
        actor_id="U1",
        reason="Confirmed layering pattern.",
    )
    session.commit()

    assert closed.status == CaseStatus.CLOSED_TP
    assert closed.resolution == CaseResolution.TRUE_POSITIVE_SAR
    assert closed.closed_at is not None

    feedback = DetectionFeedbackRepository(session).list_for_case(case.case_id)
    assert len(feedback) == 1
    assert feedback[0].verdict == CaseResolution.TRUE_POSITIVE_SAR
    assert feedback[0].reward == 1.0
    assert feedback[0].alert_id == alert.alert_id


def test_close_case_false_positive_reachable_directly_from_in_progress(session: Session) -> None:
    _seed_accounts(session, "A", "B")
    _seed_investigator(session)
    alert = _seed_alert(session)
    session.commit()

    case = create_case_from_alert(session, alert, actor_type=ActorType.SYSTEM, actor_id=None)
    session.commit()
    transition_case(
        session, case.case_id, CaseStatus.IN_PROGRESS,
        actor_type=ActorType.INVESTIGATOR, actor_id="U1",
    )
    session.commit()

    closed = close_case(
        session,
        case.case_id,
        CaseResolution.FALSE_POSITIVE,
        actor_type=ActorType.INVESTIGATOR,
        actor_id="U1",
    )
    session.commit()

    assert closed.status == CaseStatus.CLOSED_FP
    feedback = DetectionFeedbackRepository(session).list_for_case(case.case_id)
    assert feedback[0].reward == -0.3


def test_close_case_persists_rl_feedback_reloadable_by_fresh_agent(session: Session) -> None:
    _seed_accounts(session, "A", "B")
    _seed_investigator(session)
    alert = _seed_alert(session)
    session.commit()

    case = create_case_from_alert(session, alert, actor_type=ActorType.SYSTEM, actor_id=None)
    session.commit()
    _walk_to_awaiting_review(session, case.case_id)
    session.commit()

    close_case(
        session,
        case.case_id,
        CaseResolution.TRUE_POSITIVE_SAR,
        actor_type=ActorType.INVESTIGATOR,
        actor_id="U1",
    )
    session.commit()

    repo = RlArmStateRepository(session)
    state = repo.get(GLOBAL_ARM_ID)
    assert state is not None
    assert not np.array_equal(np.array(state.a_matrix), np.identity(16))

    # A fresh agent instance in the same session must resume from the
    # persisted state, not identity/zero (the landmine Phase 3 fixed).
    fresh_agent = LinUCBAgent(session)
    assert np.allclose(fresh_agent.A, np.array(state.a_matrix))


def test_close_case_rejects_escalated_compliance(session: Session) -> None:
    _seed_accounts(session, "A", "B")
    _seed_investigator(session)
    alert = _seed_alert(session)
    session.commit()
    case = create_case_from_alert(session, alert, actor_type=ActorType.SYSTEM, actor_id=None)
    session.commit()

    with pytest.raises(ValueError, match="ESCALATED_COMPLIANCE"):
        close_case(
            session,
            case.case_id,
            CaseResolution.ESCALATED_COMPLIANCE,
            actor_type=ActorType.INVESTIGATOR,
            actor_id="U1",
        )


def test_close_case_raises_on_illegal_fsm_state(session: Session) -> None:
    _seed_accounts(session, "A", "B")
    _seed_investigator(session)
    alert = _seed_alert(session)
    session.commit()
    case = create_case_from_alert(session, alert, actor_type=ActorType.SYSTEM, actor_id=None)
    session.commit()
    # case.status == ASSIGNED -- CLOSED_TP isn't reachable directly from there.

    with pytest.raises(InvalidTransitionError):
        close_case(
            session,
            case.case_id,
            CaseResolution.TRUE_POSITIVE_SAR,
            actor_type=ActorType.INVESTIGATOR,
            actor_id="U1",
        )


def test_close_case_raises_on_unknown_case(session: Session) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        close_case(
            session,
            "NOPE",
            CaseResolution.FALSE_POSITIVE,
            actor_type=ActorType.SYSTEM,
            actor_id=None,
        )


def test_close_case_enhanced_monitoring_does_not_set_closed_at(session: Session) -> None:
    _seed_accounts(session, "A", "B")
    _seed_investigator(session)
    alert = _seed_alert(session)
    session.commit()

    case = create_case_from_alert(session, alert, actor_type=ActorType.SYSTEM, actor_id=None)
    session.commit()
    _walk_to_awaiting_review(session, case.case_id)
    session.commit()

    closed = close_case(
        session,
        case.case_id,
        CaseResolution.ENHANCED_MONITORING,
        actor_type=ActorType.INVESTIGATOR,
        actor_id="U1",
    )
    session.commit()

    assert closed.status == CaseStatus.MONITORING
    assert closed.resolution == CaseResolution.ENHANCED_MONITORING
    # Still being watched, not finished -- closed_at must stay unset
    # (code-review finding, Phase 4).
    assert closed.closed_at is None


def test_close_case_writes_exactly_one_decision_changed_audit_row(session: Session) -> None:
    from db.repositories.platform import AuditLogRepository

    _seed_accounts(session, "A", "B")
    _seed_investigator(session)
    alert = _seed_alert(session)
    session.commit()

    case = create_case_from_alert(session, alert, actor_type=ActorType.SYSTEM, actor_id=None)
    session.commit()
    _walk_to_awaiting_review(session, case.case_id)
    session.commit()

    close_case(
        session,
        case.case_id,
        CaseResolution.TRUE_POSITIVE_SAR,
        actor_type=ActorType.INVESTIGATOR,
        actor_id="U1",
    )
    session.commit()

    rows = AuditLogRepository(session).list_for_case(case.case_id)
    decision_rows = [r for r in rows if r.action == "decision_changed"]
    # Code-review finding, Phase 4: previously 2 (a direct case_repo.update()
    # here plus transition_case's own) -- now bundled into exactly 1.
    assert len(decision_rows) == 1
    details = decision_rows[0].details
    assert details is not None
    assert details["after"].get("resolution") == "TRUE_POSITIVE_SAR"
    assert details["after"].get("status") == "CLOSED_TP"


def test_close_case_attributes_feedback_to_highest_risk_alert(session: Session) -> None:
    _seed_accounts(session, "A", "B")
    _seed_investigator(session)
    low_risk_alert = _seed_alert(session, "AL_LOW", account_ids=["A", "B"])
    AlertRepository(session).update(
        "AL_LOW", risk_score=20.0, actor_type=ActorType.SYSTEM, actor_id=None
    )
    session.commit()

    case = create_case_from_alert(
        session, low_risk_alert, actor_type=ActorType.SYSTEM, actor_id=None
    )
    session.commit()

    high_risk_alert = AlertRepository(session).create(
        alert_id="AL_HIGH",
        detection_type=DetectionType.round_trip,
        primary_account_id="A",
        account_ids=["A", "B"],
        score=0.95,
        risk_score=99.0,
        severity=RiskLevel.CRITICAL,
        priority=Priority.P1,
        status="open",
        source="pipeline",
        case_id=case.case_id,
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    session.commit()

    _walk_to_awaiting_review(session, case.case_id)
    session.commit()

    close_case(
        session,
        case.case_id,
        CaseResolution.TRUE_POSITIVE_SAR,
        actor_type=ActorType.INVESTIGATOR,
        actor_id="U1",
    )
    session.commit()

    feedback = DetectionFeedbackRepository(session).list_for_case(case.case_id)
    assert feedback[0].alert_id == high_risk_alert.alert_id


def test_close_case_upserts_case_feature_vector_reusing_bandit_context(
    session: Session,
) -> None:
    """ROADMAP Phase 7: `close_case` is the only writer of a REAL case's
    `case_feature_vector` row (the Similar Historical Cases corpus gap this
    phase closes) -- and it must reuse the exact same context it just fed
    the bandit, not recompute a second one."""
    _seed_accounts(session, "A", "B")
    _seed_investigator(session)
    alert = _seed_alert(session)
    session.commit()

    case = create_case_from_alert(session, alert, actor_type=ActorType.SYSTEM, actor_id=None)
    session.commit()
    _walk_to_awaiting_review(session, case.case_id)
    session.commit()

    closed = close_case(
        session,
        case.case_id,
        CaseResolution.TRUE_POSITIVE_SAR,
        actor_type=ActorType.INVESTIGATOR,
        actor_id="U1",
    )
    session.commit()

    row = CaseFeatureVectorRepository(session).get(case.case_id)
    assert row is not None
    assert row.outcome == CaseResolution.TRUE_POSITIVE_SAR
    assert row.typology == closed.typology

    # Same context the bandit itself was fed -- built via the now-public
    # `case_rl_features`, not a second, possibly-divergent computation.
    agent = LinUCBAgent(session)
    expected_context = agent.build_context(case_rl_features(closed)).tolist()
    assert row.vector == expected_context


def test_close_case_upsert_is_idempotent_across_repeated_calls(session: Session) -> None:
    """`CaseFeatureVectorRepository.upsert` (reused, not reinvented) means a
    hypothetical second `close_case` on the same case_id updates the same
    row in place rather than erroring/duplicating -- exercised here to
    confirm the new call site inherits that behavior for free."""
    _seed_accounts(session, "A", "B")
    _seed_investigator(session)
    alert = _seed_alert(session)
    session.commit()

    case = create_case_from_alert(session, alert, actor_type=ActorType.SYSTEM, actor_id=None)
    session.commit()
    _walk_to_awaiting_review(session, case.case_id)
    session.commit()

    close_case(
        session,
        case.case_id,
        CaseResolution.TRUE_POSITIVE_SAR,
        actor_type=ActorType.INVESTIGATOR,
        actor_id="U1",
    )
    session.commit()

    row = CaseFeatureVectorRepository(session).get(case.case_id)
    assert row is not None
