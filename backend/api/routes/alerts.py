"""
`/alerts` -- the system-wide alert list + manual assignment surface
(ROADMAP Phase 14). Distinct from `api.routes.cases`'s `/cases/{case_id}/
summary/alerts` (that's a single case's alerts, scoped via `require_case_
access`); this router is deliberately NOT case-scoped -- both roles see an
identical alert landscape (locked roadmap decision), it's the Dashboard's
data source.

Matches this codebase's transaction-boundary convention: the mutating route
(`PATCH /alerts/{alert_id}/assign`) calls `db.commit()` itself; the
`investigation` functions it calls only flush, never commit.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.enums import DetectionType, Priority, RiskLevel, UserRole
from db.models.investigation import Case
from db.models.platform import User
from db.repositories.detection import ALERT_SORT_KEYS, AlertRepository
from db.repositories.investigation import CaseRepository
from db.repositories.platform import UserRepository
from db.session import get_db
from foundation.auth import actor_type_for_role, get_current_user, require_role
from investigation.assignment import assign_case_to, compute_workload
from investigation.cases import claim_alert_for_new_case, create_case_from_alert, new_case_id
from investigation.prioritization import rank_alert_queue

router = APIRouter(prefix="/alerts", tags=["alerts"])


# ── Response models ──────────────────────────────────────────────────────


class AlertListItem(BaseModel):
    alert_id: str
    primary_account_id: str
    detection_type: str
    risk_score: float
    priority: str
    severity: str
    status: str
    created_at: datetime
    case_id: str | None
    assigned_to: str | None
    assigned_to_name: str | None
    case_status: str | None


class AlertListResponse(BaseModel):
    items: list[AlertListItem]
    total_count: int
    limit: int
    offset: int


class InvestigatorWorkloadItem(BaseModel):
    user_id: str
    full_name: str
    open_case_count: int


class WorkloadResponse(BaseModel):
    investigators: list[InvestigatorWorkloadItem]


class AssignAlertRequest(BaseModel):
    investigator_id: str


class AssignAlertResponse(BaseModel):
    alert_id: str
    case_id: str
    case_status: str
    assigned_to: str | None


# ── Query params ─────────────────────────────────────────────────────────


@dataclass
class _AlertListParams:
    """Shared query-param set for `GET /alerts` -- mirrors `api.routes.
    l2._TransactionSearchParams`'s dataclass-`Depends()` convention."""

    status: str | None = Query(default=None)
    priority: Priority | None = Query(default=None)
    severity: RiskLevel | None = Query(default=None)
    detection_type: DetectionType | None = Query(default=None)
    min_risk_score: float | None = Query(default=None)
    max_risk_score: float | None = Query(default=None)
    start: datetime | None = Query(default=None)
    end: datetime | None = Query(default=None)
    assigned_to: str | None = Query(default=None)
    unassigned_only: bool = Query(default=False)
    sort: str | None = Query(default=None)
    limit: int = Query(default=200, le=1000)
    offset: int = Query(default=0, ge=0)


def _filter_kwargs(params: _AlertListParams) -> dict[str, Any]:
    return {
        "status": params.status,
        "priority": params.priority,
        "severity": params.severity,
        "detection_type": params.detection_type,
        "min_risk_score": params.min_risk_score,
        "max_risk_score": params.max_risk_score,
        "start": params.start,
        "end": params.end,
        "unassigned_only": params.unassigned_only,
        "assigned_to": params.assigned_to,
    }


# ── Workload (Admin/Compliance only) ──────────────────────────────────────


@router.get("/workload", response_model=WorkloadResponse)
def get_alert_workload(
    _user: User = Depends(require_role(UserRole.ADMIN_COMPLIANCE)),
    db: Session = Depends(get_db),
) -> WorkloadResponse:
    """Per-investigator open-case counts (`investigation.assignment.
    compute_workload`, reused not reinvented) -- lets an Admin/Compliance
    user pick a sensible manual assignee for `PATCH .../assign` instead of
    guessing. Admin-only: an Investigator has no use for the whole team's
    workload and this is org-wide staffing information, not their own
    queue."""
    workload = compute_workload(db)
    investigators = {u.user_id: u for u in UserRepository(db).list_by_role(UserRole.INVESTIGATOR)}
    items = [
        InvestigatorWorkloadItem(
            user_id=user_id, full_name=investigators[user_id].full_name, open_case_count=count
        )
        for user_id, count in workload.items()
        if user_id in investigators
    ]
    return WorkloadResponse(investigators=items)


# ── System-wide alert list ────────────────────────────────────────────────


def _alert_list_item(
    alert: Any, cases_by_id: dict[str, Case], users_by_id: dict[str, User]
) -> AlertListItem:
    case = cases_by_id.get(alert.case_id) if alert.case_id is not None else None
    assigned_to = case.assigned_to if case is not None else None
    assignee = users_by_id.get(assigned_to) if assigned_to is not None else None
    return AlertListItem(
        alert_id=alert.alert_id,
        primary_account_id=alert.primary_account_id,
        detection_type=str(alert.detection_type),
        risk_score=alert.risk_score,
        priority=str(alert.priority),
        severity=str(alert.severity),
        status=alert.status,
        created_at=alert.created_at,
        case_id=alert.case_id,
        assigned_to=assigned_to,
        assigned_to_name=assignee.full_name if assignee is not None else None,
        case_status=str(case.status) if case is not None else None,
    )


@router.get("", response_model=AlertListResponse)
def list_alerts(
    params: _AlertListParams = Depends(),
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AlertListResponse:
    """System-wide alert list -- deliberately NOT case-scoped and open to
    both roles (locked roadmap decision: Dashboard is identical for
    Investigator and Admin/Compliance).

    `sort` given -> a plain SQL-ordered page. `sort` omitted -> the full
    filtered set is fetched (`AlertRepository.list_filtered(sort=None,
    limit=None)`), run through `investigation.prioritization.
    rank_alert_queue` (safe on a large list -- it sorts by `risk_score`
    desc internally and only RL-reranks the top 200, appending the
    remainder unchanged), then paginated in Python. Either way, the `Case`/
    `User` rows needed for `assigned_to_name`/`case_status` are batch-
    fetched once for the page, not per-row.

    `unassigned_only=true` and `assigned_to=<id>` are rejected together
    (400) -- code-review finding, Phase 14: `AlertRepository.
    _list_where_clause` ANDs `case_id IS NULL` (from `unassigned_only`) with
    a `case_id IN (that investigator's cases)` subquery (from
    `assigned_to`) as independent, unvalidated clauses, which can never
    both match -- silently returning `total_count=0` with no indication the
    combination is contradictory."""
    if params.sort is not None and params.sort not in ALERT_SORT_KEYS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"invalid sort: {params.sort!r}")
    if params.unassigned_only and params.assigned_to is not None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "unassigned_only and assigned_to cannot both be set",
        )

    repo = AlertRepository(db)
    filter_kwargs = _filter_kwargs(params)
    total_count = repo.count_filtered(**filter_kwargs)

    if params.sort is not None:
        page = repo.list_filtered(
            **filter_kwargs, sort=params.sort, limit=params.limit, offset=params.offset
        )
    else:
        all_matching = repo.list_filtered(**filter_kwargs, sort=None, limit=None)
        ranked = rank_alert_queue(db, all_matching)
        page = ranked[params.offset : params.offset + params.limit]

    case_ids = [a.case_id for a in page if a.case_id is not None]
    cases_by_id = {c.case_id: c for c in CaseRepository(db).list_by_ids(case_ids)}
    assignee_ids = [c.assigned_to for c in cases_by_id.values() if c.assigned_to is not None]
    users_by_id = {u.user_id: u for u in UserRepository(db).list_by_ids(assignee_ids)}

    items = [_alert_list_item(a, cases_by_id, users_by_id) for a in page]
    return AlertListResponse(
        items=items, total_count=total_count, limit=params.limit, offset=params.offset
    )


# ── Manual assignment (Admin/Compliance only) ─────────────────────────────


@router.patch("/{alert_id}/assign", response_model=AssignAlertResponse)
def assign_alert(
    alert_id: str,
    body: AssignAlertRequest,
    user: User = Depends(require_role(UserRole.ADMIN_COMPLIANCE)),
    db: Session = Depends(get_db),
) -> AssignAlertResponse:
    """Manual (re)assignment of the case behind `alert_id` to a specific
    investigator. Handles both real shapes alerts come in on this dataset
    (live DB check, ROADMAP Phase 14 planning: most alerts have no case yet
    -- `alert.case_id IS NULL` -- because `generate_alerts_from_detection`
    creates them without promoting every one to a case):

      - `alert.case_id is None`: atomically claims the alert for a
        newly-minted case_id via `investigation.cases.
        claim_alert_for_new_case` (code-review finding, Phase 14: a plain
        read-then-write of `alert.case_id` here was racy -- two concurrent
        requests on the same caseless alert could both read `case_id is
        None` and both create a `Case`, orphaning the loser's). If the
        claim wins (`rowcount == 1`), creates the case now via
        `investigation.cases.create_case_from_alert(..., case_id=...,
        assigned_to=...)`, which routes the NEW->ASSIGNED handoff through
        `investigation.assignment.assign_case_to` (a specific investigator)
        instead of the workload-based `auto_assign`. If the claim loses
        (`rowcount == 0`, a concurrent request already linked a case to
        this alert), re-fetches the alert and falls through to the same
        reassignment path below as if the alert had a case from the start
        -- no error surfaced to the caller, no orphaned `Case` ever
        created.
      - `alert.case_id` already set (from the start, or because the race
        above was lost): fetches that `Case` and calls `assign_case_to`
        directly -- a real FSM transition if the case is still NEW, a plain
        reassignment (no status change) if it's already open, `ValueError`
        (-> 409) if it's terminal.

    `investigator_id` must reference an active `INVESTIGATOR`-role user
    (422 otherwise) -- Admin/Compliance cannot assign a case to themselves
    or another Admin/Compliance user via this route."""
    alert_repo = AlertRepository(db)
    alert = alert_repo.get(alert_id)
    if alert is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert not found")

    target = UserRepository(db).get(body.investigator_id)
    if target is None or target.role != UserRole.INVESTIGATOR or not target.active:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "investigator_id must reference an active INVESTIGATOR user",
        )

    actor_type = actor_type_for_role(user.role)
    case_repo = CaseRepository(db)
    try:
        if alert.case_id is None:
            claimed_case_id = new_case_id()
            rowcount = claim_alert_for_new_case(db, alert.alert_id, claimed_case_id)
            if rowcount == 1:
                alert.case_id = claimed_case_id
                case = create_case_from_alert(
                    db,
                    alert,
                    actor_type=actor_type,
                    actor_id=user.user_id,
                    assigned_to=body.investigator_id,
                    case_id=claimed_case_id,
                )
            else:
                # Lost the race: a concurrent request already linked a case
                # between our read and our claim attempt -- re-fetch to see
                # its real, now-committed case_id and fall through to the
                # reassignment path below (same as the `else` branch).
                db.refresh(alert)
                existing_case = case_repo.get(alert.case_id) if alert.case_id else None
                if existing_case is None:
                    raise HTTPException(
                        status.HTTP_404_NOT_FOUND, "Case not found for this alert"
                    )
                case = assign_case_to(
                    db,
                    existing_case,
                    investigator_id=body.investigator_id,
                    actor_type=actor_type,
                    actor_id=user.user_id,
                )
        else:
            existing_case = case_repo.get(alert.case_id)
            if existing_case is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found for this alert")
            case = assign_case_to(
                db,
                existing_case,
                investigator_id=body.investigator_id,
                actor_type=actor_type,
                actor_id=user.user_id,
            )
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    db.commit()
    return AssignAlertResponse(
        alert_id=alert.alert_id,
        case_id=case.case_id,
        case_status=str(case.status),
        assigned_to=case.assigned_to,
    )
