from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from db.enums import ActorType, CaseLevel, CaseStatus, Priority
from db.repositories.investigation import CaseRepository, CaseStatusHistoryRepository
from db.repositories.reference import AccountRepository
from investigation.fsm import VALID_TRANSITIONS, InvalidTransitionError, transition_case


def _seed_case(session: Session, *, status: CaseStatus = CaseStatus.NEW) -> str:
    AccountRepository(session).create(account_id="A1", actor_type=ActorType.SYSTEM, actor_id=None)
    CaseRepository(session).create(
        case_id="CASE1",
        primary_account_id="A1",
        status=status,
        level=CaseLevel.L1,
        priority=Priority.P2,
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    session.commit()
    return "CASE1"


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [
        (CaseStatus.NEW, CaseStatus.ASSIGNED),
        (CaseStatus.ASSIGNED, CaseStatus.IN_PROGRESS),
        (CaseStatus.IN_PROGRESS, CaseStatus.AWAITING_REVIEW),
        (CaseStatus.IN_PROGRESS, CaseStatus.ESCALATED),
        (CaseStatus.IN_PROGRESS, CaseStatus.CLOSED_FP),
        (CaseStatus.AWAITING_REVIEW, CaseStatus.IN_PROGRESS),
        (CaseStatus.AWAITING_REVIEW, CaseStatus.CLOSED_TP),
        (CaseStatus.AWAITING_REVIEW, CaseStatus.CLOSED_FP),
        (CaseStatus.AWAITING_REVIEW, CaseStatus.MONITORING),
        (CaseStatus.ESCALATED, CaseStatus.CLOSED_TP),
        (CaseStatus.ESCALATED, CaseStatus.CLOSED_FP),
        (CaseStatus.ESCALATED, CaseStatus.MONITORING),
    ],
)
def test_every_legal_transition_succeeds(
    session: Session, from_status: CaseStatus, to_status: CaseStatus
) -> None:
    case_id = _seed_case(session, status=from_status)
    updated = transition_case(
        session, case_id, to_status, actor_type=ActorType.INVESTIGATOR, actor_id="U1"
    )
    session.commit()
    assert updated.status == to_status

    history = CaseStatusHistoryRepository(session).list_for_case(case_id)
    assert [h.to_status for h in history] == [to_status]
    assert history[0].from_status == from_status


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [
        (CaseStatus.NEW, CaseStatus.IN_PROGRESS),
        (CaseStatus.NEW, CaseStatus.CLOSED_TP),
        (CaseStatus.ASSIGNED, CaseStatus.AWAITING_REVIEW),
        (CaseStatus.ASSIGNED, CaseStatus.NEW),
        (CaseStatus.IN_PROGRESS, CaseStatus.CLOSED_TP),
        (CaseStatus.IN_PROGRESS, CaseStatus.MONITORING),
        (CaseStatus.IN_PROGRESS, CaseStatus.NEW),
        (CaseStatus.AWAITING_REVIEW, CaseStatus.ESCALATED),
        (CaseStatus.ESCALATED, CaseStatus.IN_PROGRESS),
        (CaseStatus.ESCALATED, CaseStatus.AWAITING_REVIEW),
        (CaseStatus.CLOSED_TP, CaseStatus.IN_PROGRESS),
        (CaseStatus.CLOSED_FP, CaseStatus.MONITORING),
        (CaseStatus.MONITORING, CaseStatus.IN_PROGRESS),
    ],
)
def test_every_illegal_transition_raises(
    session: Session, from_status: CaseStatus, to_status: CaseStatus
) -> None:
    case_id = _seed_case(session, status=from_status)
    with pytest.raises(InvalidTransitionError):
        transition_case(
            session, case_id, to_status, actor_type=ActorType.INVESTIGATOR, actor_id="U1"
        )
    # No history row should have been written for a rejected transition.
    assert CaseStatusHistoryRepository(session).list_for_case(case_id) == []


def test_terminal_states_have_no_outgoing_transitions() -> None:
    for terminal in (CaseStatus.CLOSED_TP, CaseStatus.CLOSED_FP, CaseStatus.MONITORING):
        assert VALID_TRANSITIONS[terminal] == set()


def test_transition_case_raises_on_unknown_case(session: Session) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        transition_case(
            session,
            "NOPE",
            CaseStatus.ASSIGNED,
            actor_type=ActorType.SYSTEM,
            actor_id=None,
        )


def test_transition_case_writes_taxonomy_specific_audit_action(session: Session) -> None:
    from db.repositories.platform import AuditLogRepository

    case_id = _seed_case(session, status=CaseStatus.AWAITING_REVIEW)
    transition_case(
        session, case_id, CaseStatus.CLOSED_TP, actor_type=ActorType.ADMIN, actor_id="ADMIN1"
    )
    session.commit()

    rows = AuditLogRepository(session).list_for_case(case_id)
    actions = [r.action for r in rows]
    assert "decision_changed" in actions
