"""
Case creation from an alert (+ auto-assignment) and case closure (+
feedback-loop tie-in). Reuses `fsm.transition_case` for every status change
and `assignment.auto_assign` for the NEW->ASSIGNED handoff -- no case-status
logic duplicated here.

Neither `create_case_from_alert` nor `close_case` commits `session` --
consistent with every repository (`db/repositories/base.py`) and
`LinUCBAgent.update()`/`.receive_feedback()` (`detection/rl/bandit.py`) in
this codebase: callees flush, the caller owns the transaction boundary. The
caller here is `scripts/run_detection_pipeline.py` for now; a later phase's
API route handler will be the caller once one exists.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from db.enums import ActorType, CaseLevel, CaseResolution, CaseStatus
from db.models.base import utcnow
from db.models.detection import Alert
from db.models.investigation import Case
from db.repositories.detection import AlertRepository, DetectionFeedbackRepository
from db.repositories.investigation import CaseAccountRepository, CaseRepository
from detection.rl.bandit import LinUCBAgent
from investigation.assignment import auto_assign
from investigation.fsm import transition_case
from investigation.rl_features import base_rl_feature_dict


def _new_case_id() -> str:
    return f"CASE-{datetime.now(UTC).strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"


def create_case_from_alert(
    session: Session,
    alert: Alert,
    *,
    actor_type: ActorType,
    actor_id: str | None,
    workload: dict[str, int] | None = None,
) -> Case:
    """Create a `Case` (status=NEW, level=L1 -- every case starts at
    triage) from `alert`, link every account in the alert's pattern into
    `case_accounts` (the case-scoping security boundary, doc §3.3), point
    the alert at the new case, then hand off to `auto_assign` for the
    NEW->ASSIGNED workload assignment + SLA computation.

    `workload` is forwarded unchanged to `auto_assign` (see its docstring)
    so a batch caller looping over many alerts can pass the same
    incrementally-maintained dict through every call instead of a fresh
    aggregate query per case (code-review finding, Phase 4)."""
    case_repo = CaseRepository(session)
    case_account_repo = CaseAccountRepository(session)
    alert_repo = AlertRepository(session)

    case_id = _new_case_id()
    case = case_repo.create(
        case_id=case_id,
        primary_account_id=alert.primary_account_id,
        status=CaseStatus.NEW,
        level=CaseLevel.L1,
        priority=alert.priority,
        typology=str(alert.detection_type),
        risk_score=alert.risk_score,
        actor_type=actor_type,
        actor_id=actor_id,
    )

    for account_id in alert.account_ids:
        case_account_repo.add_account(
            case_id=case_id,
            account_id=account_id,
            hop_distance=0 if account_id == alert.primary_account_id else 1,
            actor_type=actor_type,
            actor_id=actor_id,
        )

    alert_repo.update(
        alert.alert_id,
        case_id=case_id,
        status="assigned",
        actor_type=actor_type,
        actor_id=actor_id,
    )

    return auto_assign(
        session, case, actor_type=actor_type, actor_id=actor_id, workload=workload
    )


#: Which `CaseResolution` values `close_case` accepts, and the `CaseStatus`
#: each transitions to. `ESCALATED_COMPLIANCE` is deliberately excluded --
#: escalation is a mid-flow FSM transition (the case stays open, pending
#: compliance action), not a closing action; call `investigation.fsm.
#: transition_case(..., CaseStatus.ESCALATED)` directly for that instead.
_CLOSING_TRANSITIONS: dict[CaseResolution, CaseStatus] = {
    CaseResolution.TRUE_POSITIVE_SAR: CaseStatus.CLOSED_TP,
    CaseResolution.FALSE_POSITIVE: CaseStatus.CLOSED_FP,
    CaseResolution.ENHANCED_MONITORING: CaseStatus.MONITORING,
}

#: RL reward per resolution (`LinUCBAgent.receive_feedback`'s own
#: convention: +1.0 confirmed-risk / -0.3 false positive).
#: `ENHANCED_MONITORING` is treated as a TP-like (+1.0) outcome -- it
#: confirms genuine risk warranting ongoing monitoring, not a cleared alert.
_CLOSING_REWARD: dict[CaseResolution, float] = {
    CaseResolution.TRUE_POSITIVE_SAR: 1.0,
    CaseResolution.FALSE_POSITIVE: -0.3,
    CaseResolution.ENHANCED_MONITORING: 1.0,
}


def _case_rl_features(case: Case) -> dict:
    """Adapt a `Case` row into the flat feature dict `LinUCBAgent.
    build_context` expects -- source-specific extraction (reading
    `case.typology`/`case.risk_score`) stays here; the shared dict-shape/
    defaulting is `investigation.rl_features.base_rl_feature_dict`
    (code-review finding, Phase 4: this used to duplicate
    `investigation.prioritization._build_account_features`'s copy of the
    same defaulting)."""
    patterns = [case.typology] if case.typology else []
    return {
        "account_id": case.primary_account_id,
        **base_rl_feature_dict(risk_score=case.risk_score or 0.0, patterns=patterns),
    }


#: Resolutions whose closing transition sets `Case.closed_at` -- only the
#: two genuinely terminal outcomes (CLOSED_TP/CLOSED_FP). `MONITORING`
#: deliberately does NOT set `closed_at`: enhanced monitoring means the
#: case is still being actively watched, not finished, so `closed_at`
#: (which everywhere else in this schema means "stopped being worked")
#: would be misleading if set here (code-review finding, Phase 4 --
#: previously set unconditionally for all three with no documented reason).
_SETS_CLOSED_AT = frozenset({CaseResolution.TRUE_POSITIVE_SAR, CaseResolution.FALSE_POSITIVE})


def close_case(
    session: Session,
    case_id: str,
    resolution: CaseResolution,
    *,
    actor_type: ActorType,
    actor_id: str | None,
    reason: str | None = None,
) -> Case:
    """Close `case_id` with `resolution`: transition to the matching
    terminal `CaseStatus` via the FSM (raises `investigation.fsm.
    InvalidTransitionError` if the case isn't currently in a status the FSM
    allows that transition from -- e.g. a TRUE_POSITIVE_SAR verdict requires
    the case to be in AWAITING_REVIEW or ESCALATED first; raises
    `ValueError` if the case doesn't exist -- that check lives solely in
    `transition_case`, not duplicated here), write a
    `DetectionFeedbackRepository` row, and feed the verdict to the
    already-injected `LinUCBAgent` for the case's primary account/context.
    Does NOT touch `RuleDefinition.confidence` -- that adjustment is
    Phase 12's job (ROADMAP Phase 4 plan)."""
    if resolution not in _CLOSING_TRANSITIONS:
        raise ValueError(
            f"close_case does not support resolution={resolution!r} -- "
            "ESCALATED_COMPLIANCE is a mid-flow FSM transition (case stays "
            "open pending compliance action), not a closing action; call "
            "investigation.fsm.transition_case(session, case_id, "
            "CaseStatus.ESCALATED, ...) directly for that case instead."
        )

    to_status = _CLOSING_TRANSITIONS[resolution]
    extra_changes: dict[str, object] = {"resolution": resolution, "resolution_reason": reason}
    if resolution in _SETS_CLOSED_AT:
        extra_changes["closed_at"] = utcnow()

    # Bundles resolution/resolution_reason/closed_at into the SAME
    # CaseRepository call/audit row as the status change (code-review
    # finding, Phase 4: previously a separate `case_repo.update()` here plus
    # `transition_case`'s own, confirmed live as `decision_changed`
    # appearing twice per real close).
    case = transition_case(
        session,
        case_id,
        to_status,
        actor_type=actor_type,
        actor_id=actor_id,
        reason=reason,
        extra_changes=extra_changes,
    )

    # Ordered by risk_score descending (`AlertRepository.list_for_case`) so
    # the highest-risk alert -- not an incidental DB-order first row -- is
    # the one attributed to this verdict (code-review finding, Phase 4).
    case_alerts = AlertRepository(session).list_for_case(case_id)
    primary_alert_id = case_alerts[0].alert_id if case_alerts else None
    rule_ids = sorted({rid for a in case_alerts for rid in (a.rule_ids or [])}) or None

    reward = _CLOSING_REWARD[resolution]
    DetectionFeedbackRepository(session).create(
        case_id=case_id,
        alert_id=primary_alert_id,
        verdict=resolution,
        reward=reward,
        rule_ids=rule_ids,
        created_by=actor_id or "system",
        actor_type=actor_type,
        actor_id=actor_id,
    )

    agent = LinUCBAgent(session, actor_type=actor_type, actor_id=actor_id)
    context = agent.build_context(_case_rl_features(case))
    agent.receive_feedback(case.primary_account_id, context, is_true_positive=reward > 0)

    return case
