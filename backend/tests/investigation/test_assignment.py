from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from db.enums import ActorType, CaseLevel, CaseStatus, Priority, UserRole
from db.models.base import utcnow
from db.repositories.investigation import CaseRepository
from db.repositories.platform import UserRepository
from db.repositories.reference import AccountRepository
from investigation.assignment import (
    NoEligibleInvestigatorError,
    auto_assign,
    list_overdue_cases,
)
from investigation.config import DEFAULT_SLA_POLICY


def _seed_account(session: Session, account_id: str = "A1") -> None:
    AccountRepository(session).create(
        account_id=account_id, actor_type=ActorType.SYSTEM, actor_id=None
    )


def _seed_investigator(
    session: Session, user_id: str, *, active: bool = True, role: UserRole = UserRole.INVESTIGATOR
) -> None:
    UserRepository(session).create(
        user_id=user_id,
        username=user_id.lower(),
        email=f"{user_id.lower()}@example.com",
        password_hash="x",
        role=role,
        full_name=user_id,
        active=active,
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )


def _seed_case(
    session: Session,
    case_id: str,
    *,
    account_id: str = "A1",
    status: CaseStatus = CaseStatus.NEW,
    priority: Priority = Priority.P2,
    assigned_to: str | None = None,
) -> None:
    CaseRepository(session).create(
        case_id=case_id,
        primary_account_id=account_id,
        status=status,
        level=CaseLevel.L1,
        priority=priority,
        assigned_to=assigned_to,
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )


def test_auto_assign_picks_investigator_with_fewest_open_cases(session: Session) -> None:
    _seed_account(session)
    _seed_investigator(session, "U1")
    _seed_investigator(session, "U2")
    # U1 already has one open case; U2 has none -- U2 should be picked next.
    _seed_case(session, "EXISTING", status=CaseStatus.IN_PROGRESS, assigned_to="U1")
    _seed_case(session, "NEWCASE")
    session.commit()

    case = CaseRepository(session).get("NEWCASE")
    assert case is not None
    updated = auto_assign(session, case, actor_type=ActorType.SYSTEM, actor_id=None)
    session.commit()

    assert updated.assigned_to == "U2"
    assert updated.status == CaseStatus.ASSIGNED


def test_auto_assign_ties_break_by_lexicographically_smallest_user_id(session: Session) -> None:
    _seed_account(session)
    _seed_investigator(session, "U_B")
    _seed_investigator(session, "U_A")
    _seed_case(session, "NEWCASE")
    session.commit()

    case = CaseRepository(session).get("NEWCASE")
    assert case is not None
    updated = auto_assign(session, case, actor_type=ActorType.SYSTEM, actor_id=None)
    session.commit()

    assert updated.assigned_to == "U_A"


def test_auto_assign_ignores_closed_cases_in_workload(session: Session) -> None:
    _seed_account(session)
    _seed_investigator(session, "U1")
    _seed_investigator(session, "U2")
    # U1 has a closed case (doesn't count) and U2 has none -- tied at 0,
    # tie-break picks U1 (lexicographically smaller).
    _seed_case(session, "OLD", status=CaseStatus.CLOSED_FP, assigned_to="U1")
    _seed_case(session, "NEWCASE")
    session.commit()

    case = CaseRepository(session).get("NEWCASE")
    assert case is not None
    updated = auto_assign(session, case, actor_type=ActorType.SYSTEM, actor_id=None)
    session.commit()

    assert updated.assigned_to == "U1"


def test_auto_assign_ignores_inactive_and_non_investigator_users(session: Session) -> None:
    _seed_account(session)
    _seed_investigator(session, "INACTIVE", active=False)
    _seed_investigator(session, "ADMIN1", role=UserRole.ADMIN_COMPLIANCE)
    _seed_investigator(session, "U1")
    _seed_case(session, "NEWCASE")
    session.commit()

    case = CaseRepository(session).get("NEWCASE")
    assert case is not None
    updated = auto_assign(session, case, actor_type=ActorType.SYSTEM, actor_id=None)
    session.commit()

    assert updated.assigned_to == "U1"


def test_auto_assign_raises_when_no_eligible_investigator(session: Session) -> None:
    _seed_account(session)
    _seed_case(session, "NEWCASE")
    session.commit()

    case = CaseRepository(session).get("NEWCASE")
    assert case is not None
    with pytest.raises(NoEligibleInvestigatorError):
        auto_assign(session, case, actor_type=ActorType.SYSTEM, actor_id=None)


def test_auto_assign_computes_sla_due_at_from_priority(session: Session) -> None:
    _seed_account(session)
    _seed_investigator(session, "U1")
    _seed_case(session, "NEWCASE", priority=Priority.P1)
    session.commit()

    case = CaseRepository(session).get("NEWCASE")
    assert case is not None
    before = utcnow()
    updated = auto_assign(session, case, actor_type=ActorType.SYSTEM, actor_id=None)
    session.commit()

    assert updated.sla_due_at is not None
    # SQLite round-trips tz-aware datetimes as naive-UTC (see
    # `db/repositories/_audit.py::_canonical_ts`'s documented reasoning) --
    # normalize both sides the same way before comparing.
    actual = updated.sla_due_at.replace(tzinfo=None)
    expected_min = (
        before + DEFAULT_SLA_POLICY.duration_for(Priority.P1) - timedelta(seconds=5)
    ).replace(tzinfo=None)
    expected_max = (
        before + DEFAULT_SLA_POLICY.duration_for(Priority.P1) + timedelta(seconds=5)
    ).replace(tzinfo=None)
    assert expected_min <= actual <= expected_max


def test_list_overdue_cases_only_returns_open_and_past_due(session: Session) -> None:
    _seed_account(session)
    now = utcnow()

    CaseRepository(session).create(
        case_id="OVERDUE_OPEN",
        primary_account_id="A1",
        status=CaseStatus.IN_PROGRESS,
        level=CaseLevel.L1,
        priority=Priority.P2,
        sla_due_at=now - timedelta(hours=1),
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    CaseRepository(session).create(
        case_id="OVERDUE_CLOSED",
        primary_account_id="A1",
        status=CaseStatus.CLOSED_FP,
        level=CaseLevel.L1,
        priority=Priority.P2,
        sla_due_at=now - timedelta(hours=1),
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    CaseRepository(session).create(
        case_id="NOT_YET_DUE",
        primary_account_id="A1",
        status=CaseStatus.IN_PROGRESS,
        level=CaseLevel.L1,
        priority=Priority.P2,
        sla_due_at=now + timedelta(hours=1),
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    CaseRepository(session).create(
        case_id="NO_SLA",
        primary_account_id="A1",
        status=CaseStatus.IN_PROGRESS,
        level=CaseLevel.L1,
        priority=Priority.P2,
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    session.commit()

    overdue_ids = {c.case_id for c in list_overdue_cases(session)}
    assert overdue_ids == {"OVERDUE_OPEN"}
