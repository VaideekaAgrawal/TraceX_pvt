"""
Case status FSM -- the coupling Phase 1's `CaseRepository`/
`CaseStatusHistoryRepository` module docstring deliberately deferred to
Phase 4: "writing that history row is a second, explicit call to
`CaseStatusHistoryRepository` by the caller (the Phase 4 FSM)."

`transition_case()` is the one place in the codebase that:
  1. validates a status change against `VALID_TRANSITIONS`,
  2. writes the plain field change via `CaseRepository.update(...,
     action=<taxonomy verb>)`, and
  3. appends the append-only `case_status_history` row via
     `CaseStatusHistoryRepository.record_transition(...)`.

Every other Phase 4 module that changes case status (`assignment.auto_assign`,
`cases.close_case`) calls this function rather than writing to `cases.status`
or `case_status_history` directly, so FSM validity is enforced in exactly one
place.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from db.enums import ActorType, CaseStatus
from db.models.investigation import Case
from db.repositories.investigation import CaseRepository, CaseStatusHistoryRepository

#: Legal `from_status -> {to_status, ...}` transitions, taken verbatim from
#: the ROADMAP Phase 4 plan: "NEW->ASSIGNED->IN_PROGRESS->
#: {AWAITING_REVIEW,ESCALATED,CLOSED_FP}, AWAITING_REVIEW<->IN_PROGRESS,
#: AWAITING_REVIEW/ESCALATED->{CLOSED_TP,CLOSED_FP,MONITORING}". Judgment
#: call: taken literally -- e.g. ESCALATED has no path back to
#: IN_PROGRESS/AWAITING_REVIEW (escalation is one-directional except to
#: close/monitor) since the plan doesn't list one, and CLOSED_TP is only
#: reachable from AWAITING_REVIEW or ESCALATED, not directly from
#: IN_PROGRESS (a TP verdict implies a review step first) -- not adding
#: extra transitions beyond what's explicitly specified.
VALID_TRANSITIONS: dict[CaseStatus, set[CaseStatus]] = {
    CaseStatus.NEW: {CaseStatus.ASSIGNED},
    CaseStatus.ASSIGNED: {CaseStatus.IN_PROGRESS},
    CaseStatus.IN_PROGRESS: {
        CaseStatus.AWAITING_REVIEW,
        CaseStatus.ESCALATED,
        CaseStatus.CLOSED_FP,
    },
    CaseStatus.AWAITING_REVIEW: {
        CaseStatus.IN_PROGRESS,
        CaseStatus.CLOSED_TP,
        CaseStatus.CLOSED_FP,
        CaseStatus.MONITORING,
    },
    CaseStatus.ESCALATED: {
        CaseStatus.CLOSED_TP,
        CaseStatus.CLOSED_FP,
        CaseStatus.MONITORING,
    },
    CaseStatus.CLOSED_TP: set(),
    CaseStatus.CLOSED_FP: set(),
    CaseStatus.MONITORING: set(),
}

#: `docs/DATA_SCHEMA.md` §3.5's `audit_log.action` taxonomy names
#: `decision_changed`/`escalated` explicitly (among others, "e.g."); the
#: remaining, non-terminal, non-escalation transitions use the generic
#: `case_status_changed` verb (there is no more specific named verb for
#: them in the doc's taxonomy).
_TRANSITION_ACTIONS: dict[CaseStatus, str] = {
    CaseStatus.ASSIGNED: "case_assigned",
    CaseStatus.IN_PROGRESS: "case_status_changed",
    CaseStatus.AWAITING_REVIEW: "case_status_changed",
    CaseStatus.ESCALATED: "escalated",
    CaseStatus.CLOSED_TP: "decision_changed",
    CaseStatus.CLOSED_FP: "decision_changed",
    CaseStatus.MONITORING: "decision_changed",
}


class InvalidTransitionError(ValueError):
    """Raised by `transition_case` when `to_status` is not reachable from
    the case's current status per `VALID_TRANSITIONS`."""


def transition_case(
    session: Session,
    case_id: str,
    to_status: CaseStatus,
    *,
    actor_type: ActorType,
    actor_id: str | None,
    reason: str | None = None,
) -> Case:
    """Validate and perform one case-status transition, writing both the
    `cases.status` field change and the append-only `case_status_history`
    row. Raises `InvalidTransitionError` if `to_status` is not legal from the
    case's current status; raises `ValueError` if the case doesn't exist."""
    case_repo = CaseRepository(session)
    history_repo = CaseStatusHistoryRepository(session)

    case = case_repo.get(case_id)
    if case is None:
        raise ValueError(f"case {case_id!r} does not exist")

    from_status = case.status
    allowed = VALID_TRANSITIONS.get(from_status, set())
    if to_status not in allowed:
        raise InvalidTransitionError(
            f"illegal case transition {from_status.value} -> {to_status.value} "
            f"for case {case_id!r}"
        )

    action = _TRANSITION_ACTIONS.get(to_status, "case_status_changed")
    updated = case_repo.update(
        case_id,
        status=to_status,
        action=action,
        actor_type=actor_type,
        actor_id=actor_id,
    )
    history_repo.record_transition(
        case_id=case_id,
        from_status=from_status,
        to_status=to_status,
        changed_by=actor_id,
        reason=reason,
        actor_type=actor_type,
        actor_id=actor_id,
    )
    return updated
