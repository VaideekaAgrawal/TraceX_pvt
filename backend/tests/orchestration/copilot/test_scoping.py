"""Copilot case-scoping — ROADMAP Phase 10. The RBAC boundary for a cross-case
agent."""
from __future__ import annotations

from sqlalchemy.orm import Session

from db.enums import ActorType, CaseLevel, CaseStatus, Priority, UserRole
from db.models.platform import User
from db.repositories.investigation import CaseRepository
from db.repositories.platform import UserRepository
from orchestration.copilot import scoping


def test_investigator_sees_only_their_assigned_cases(
    session: Session, investigator: User
) -> None:
    assert scoping.accessible_case_ids(session, investigator) == {"CASE-MINE"}


def test_admin_sees_the_review_queue_not_assigned_cases(session: Session) -> None:
    admin = UserRepository(session).create(
        user_id="U-ADM", username="adm", email="adm@example.com", password_hash="x",
        role=UserRole.ADMIN_COMPLIANCE, full_name="Admin",
        actor_type=ActorType.SYSTEM, actor_id=None,
    )
    cases = CaseRepository(session)
    cases.create(
        case_id="C-REVIEW", primary_account_id="A", status=CaseStatus.AWAITING_REVIEW,
        level=CaseLevel.L1, priority=Priority.P1, risk_score=50.0,
        actor_type=ActorType.SYSTEM, actor_id=None,
    )
    cases.create(
        case_id="C-INPROG", primary_account_id="A", status=CaseStatus.IN_PROGRESS,
        level=CaseLevel.L1, priority=Priority.P1, risk_score=50.0,
        assigned_to="someone", actor_type=ActorType.SYSTEM, actor_id=None,
    )
    session.commit()
    # The AWAITING_REVIEW case is in the admin's queue; the IN_PROGRESS one is not.
    assert scoping.accessible_case_ids(session, admin) == {"C-REVIEW"}
