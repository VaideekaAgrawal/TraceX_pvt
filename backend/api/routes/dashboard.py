"""
`GET /dashboard/summary` -- the Dashboard's system-wide summary view
(ROADMAP Phase 14). Both roles get an identical response (same locked
roadmap decision as `api.routes.alerts`'s `GET /alerts`): no RBAC beyond
plain authentication.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.models.platform import User
from db.session import get_db
from foundation.auth import get_current_user
from investigation.dashboard import compute_dashboard_summary

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


# ── Response models ──────────────────────────────────────────────────────


class AlertsOverTimePoint(BaseModel):
    date: str
    count: int


class DashboardSummaryResponse(BaseModel):
    active_alert_count: int
    open_case_count: int
    avg_risk_score: float | None
    severity_breakdown: dict[str, int]
    alerts_over_time: list[AlertsOverTimePoint]
    window_days: int


@router.get("/summary", response_model=DashboardSummaryResponse)
def get_dashboard_summary(
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DashboardSummaryResponse:
    result = compute_dashboard_summary(db)
    return DashboardSummaryResponse(**result)
