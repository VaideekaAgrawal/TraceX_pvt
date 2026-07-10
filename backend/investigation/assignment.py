"""
Workload-based case auto-assignment + SLA due-date computation.

`SYSTEM_DEVELOPMENT_PLAN.md` §5 says "fewest open **high-priority** cases";
`docs/DATA_SCHEMA.md` says a plain `COUNT(cases WHERE assigned_to=? AND
status open)` with no priority filter, and the same file's own reasoning
explicitly warns "don't over-engineer assignment logic before the store
itself is unified." This module follows `DATA_SCHEMA.md`'s simpler,
more implementation-ready formula (ROADMAP Phase 4 plan, decided -- not
re-litigated here): plain open-case count per investigator, no priority
weighting.

Only active (`User.active=True`) `INVESTIGATOR`-role users are eligible.
Ties are broken by lexicographically smallest `user_id` -- deterministic
and testable; the doc doesn't specify a tie-break rule.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db.enums import ActorType, CaseStatus, UserRole
from db.models.base import utcnow
from db.models.investigation import Case
from db.models.platform import User
from db.repositories.investigation import CaseRepository
from investigation.config import DEFAULT_SLA_POLICY
from investigation.fsm import transition_case

#: Statuses that count toward an investigator's workload -- everything
#: except the three terminal/resolved statuses (ROADMAP Phase 4 plan).
OPEN_STATUSES: set[CaseStatus] = {
    CaseStatus.NEW,
    CaseStatus.ASSIGNED,
    CaseStatus.IN_PROGRESS,
    CaseStatus.AWAITING_REVIEW,
    CaseStatus.ESCALATED,
}


class NoEligibleInvestigatorError(RuntimeError):
    """Raised by `auto_assign` when there is no active `INVESTIGATOR` user
    to assign the case to."""


def _workload(session: Session) -> dict[str, int]:
    """Open-case count per active-investigator `user_id`. Investigators
    with zero open cases are still included (via the LEFT OUTER JOIN) so
    they're eligible to be picked as the minimum."""
    stmt = (
        select(User.user_id, func.count(Case.case_id))
        .select_from(User)
        .outerjoin(
            Case,
            (Case.assigned_to == User.user_id) & (Case.status.in_(OPEN_STATUSES)),
        )
        .where(User.role == UserRole.INVESTIGATOR, User.active.is_(True))
        .group_by(User.user_id)
    )
    return {user_id: count for user_id, count in session.execute(stmt)}


def auto_assign(
    session: Session, case: Case, *, actor_type: ActorType, actor_id: str | None
) -> Case:
    """Pick the active investigator with the fewest open cases, set
    `assigned_to` + `sla_due_at` on `case`, then transition NEW->ASSIGNED via
    the FSM. Raises `NoEligibleInvestigatorError` if there is no active
    investigator at all."""
    workload = _workload(session)
    if not workload:
        raise NoEligibleInvestigatorError(
            "no active INVESTIGATOR users available for auto-assignment"
        )

    chosen_user_id = min(workload.items(), key=lambda kv: (kv[1], kv[0]))[0]

    case_repo = CaseRepository(session)
    sla_due_at = utcnow() + DEFAULT_SLA_POLICY.duration_for(case.priority)
    case_repo.update(
        case.case_id,
        assigned_to=chosen_user_id,
        sla_due_at=sla_due_at,
        action="case_assigned",
        actor_type=actor_type,
        actor_id=actor_id,
    )

    return transition_case(
        session,
        case.case_id,
        CaseStatus.ASSIGNED,
        actor_type=actor_type,
        actor_id=actor_id,
        reason="auto-assigned (workload-based)",
    )


def list_overdue_cases(session: Session) -> list[Case]:
    """Every still-open case whose `sla_due_at` has passed -- tracking only
    (ROADMAP Phase 4 plan): no automatic escalation on breach."""
    now = utcnow()
    stmt = select(Case).where(
        Case.status.in_(OPEN_STATUSES),
        Case.sla_due_at.is_not(None),
        Case.sla_due_at < now,
    )
    return list(session.scalars(stmt))
