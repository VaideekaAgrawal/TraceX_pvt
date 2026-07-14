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


def compute_workload(session: Session) -> dict[str, int]:
    """Open-case count per active-investigator `user_id`. Investigators
    with zero open cases are still included (via the LEFT OUTER JOIN) so
    they're eligible to be picked as the minimum.

    Public (not `_workload`, code-review finding, Phase 4) so a batch
    caller can compute this once and pass the same dict to many
    `auto_assign` calls -- see `auto_assign`'s `workload` parameter."""
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
    session: Session,
    case: Case,
    *,
    actor_type: ActorType,
    actor_id: str | None,
    workload: dict[str, int] | None = None,
) -> Case:
    """Pick the active investigator with the fewest open cases, then
    transition NEW->ASSIGNED via the FSM, bundling `assigned_to`/
    `sla_due_at` into that same call (`transition_case`'s `extra_changes`)
    so exactly one `cases` write/audit row happens per assignment
    (code-review finding, Phase 4: previously two -- a direct
    `case_repo.update()` here plus `transition_case`'s own, confirmed live
    as `case_assigned` appearing twice per real assignment). Raises
    `NoEligibleInvestigatorError` if there is no active investigator at
    all.

    `workload`, if given, is used instead of querying fresh, and is
    mutated in place (the chosen investigator's count incremented by 1) so
    a batch caller (e.g. `scripts/run_detection_pipeline.py`'s top-N loop)
    can call `compute_workload()` once before the loop and keep it current
    in Python across many `auto_assign` calls, instead of re-running the
    full aggregate query once per case (code-review finding, Phase 4:
    confirmed redundant -- the same query re-ran 20 times in one real
    pipeline run when only the just-assigned investigator's count
    changed). Standalone callers can omit it; a fresh query is run as
    before."""
    if workload is None:
        workload = compute_workload(session)
    if not workload:
        raise NoEligibleInvestigatorError(
            "no active INVESTIGATOR users available for auto-assignment"
        )

    chosen_user_id = min(workload.items(), key=lambda kv: (kv[1], kv[0]))[0]
    workload[chosen_user_id] += 1

    sla_due_at = utcnow() + DEFAULT_SLA_POLICY.duration_for(case.priority)
    return transition_case(
        session,
        case.case_id,
        CaseStatus.ASSIGNED,
        actor_type=actor_type,
        actor_id=actor_id,
        reason="auto-assigned (workload-based)",
        extra_changes={"assigned_to": chosen_user_id, "sla_due_at": sla_due_at},
    )


def assign_case_to(
    session: Session,
    case: Case,
    *,
    investigator_id: str,
    actor_type: ActorType,
    actor_id: str | None,
) -> Case:
    """Manual (re)assignment to a SPECIFIC investigator -- the
    Admin/Compliance-driven counterpart to workload-based `auto_assign`
    (ROADMAP Phase 14: `PATCH /alerts/{alert_id}/assign`). Does not check
    eligibility of `investigator_id` itself (active/INVESTIGATOR-role) --
    that's the caller's job (the route, before this is ever called), same
    division of responsibility as `auto_assign` trusting `compute_workload`'s
    own eligibility filter rather than re-checking it here.

    Three cases based on `case.status`:

      - `NEW`: a real FSM transition (NEW->ASSIGNED), bundling
        `assigned_to`/`sla_due_at` into the same `transition_case` call/
        audit row `auto_assign` uses, computing `sla_due_at` the identical
        way (reused, not reinvented, from `DEFAULT_SLA_POLICY`).
      - Already open but not NEW (`ASSIGNED`/`IN_PROGRESS`/
        `AWAITING_REVIEW`/`ESCALATED`, i.e. `OPEN_STATUSES` minus `NEW`):
        status does NOT change -- this is a plain `assigned_to` field
        write, not an FSM transition, logged under a dedicated
        `case_reassigned` action so it's distinguishable from both
        `case_assigned` (the NEW->ASSIGNED handoff) and the generic
        `case_updated`. Reassigning to the SAME investigator still writes a
        `case_reassigned` row -- no special-cased no-op, mirroring
        `AlertRepository.mark_opened`'s precedent of an audit-only write
        with no actual field-value change being a legitimate call.
      - Terminal (`CLOSED_TP`/`CLOSED_FP`/`MONITORING`): raises
        `ValueError` -- a closed/monitored case cannot be reassigned.
    """
    if case.status == CaseStatus.NEW:
        sla_due_at = utcnow() + DEFAULT_SLA_POLICY.duration_for(case.priority)
        return transition_case(
            session,
            case.case_id,
            CaseStatus.ASSIGNED,
            actor_type=actor_type,
            actor_id=actor_id,
            reason="manually assigned by Admin/Compliance",
            extra_changes={"assigned_to": investigator_id, "sla_due_at": sla_due_at},
        )
    if case.status in OPEN_STATUSES:
        return CaseRepository(session).update(
            case.case_id,
            assigned_to=investigator_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="case_reassigned",
        )
    raise ValueError(
        f"cannot reassign case {case.case_id!r}: status {case.status.value!r} is terminal"
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
