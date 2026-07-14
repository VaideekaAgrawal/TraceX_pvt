"""
Dashboard aggregation (ROADMAP Phase 14: `GET /dashboard/summary`) -- pure
read-side aggregation over data other repositories already maintain (alert
severity/status/risk_score, case status). No new state, no new ML: every
number here is a `COUNT`/`AVG`/`GROUP BY` over `alerts`/`cases`.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from db.enums import RiskLevel
from db.repositories.detection import AlertRepository
from db.repositories.investigation import CaseRepository
from investigation.assignment import OPEN_STATUSES


def compute_dashboard_summary(session: Session, *, window_days: int = 30) -> dict[str, Any]:
    """Headline numbers for the Dashboard's system-wide summary view (both
    roles see the identical response -- system-wide, not per-investigator).

    - `open_case_count` reuses `investigation.assignment.OPEN_STATUSES` --
      the exact same "what counts as open" definition `compute_workload`
      already uses, not a second invented one.
    - `severity_breakdown` is zero-filled for every `RiskLevel` value, not
      just ones with a nonzero count, so a caller doesn't have to guard a
      missing key for a severity that currently has zero active alerts.
    - `alerts_over_time` is zero-filled for every day in the
      `[today - window_days + 1, today]` window (`window_days` calendar
      days total, inclusive of today), not a sparse series of only the
      days that actually have alerts.

    Note on the real dataset: every alert currently comes from a single
    historical detection-pipeline run (`scripts/run_detection_pipeline.py`,
    see `docs/METRICS.md` §4), so `alerts_over_time` will show exactly one
    real spike day and zero-filled bars for the rest of the window --
    confirmed live against `data/tracex.db` (3,995 alerts on one day, 0 on
    every other day in the 30-day window) -- expected given the pilot's
    data-generation story, not a bug in this aggregation.
    """
    alert_repo = AlertRepository(session)
    case_repo = CaseRepository(session)

    today: date = datetime.now(UTC).date()
    start_day = today - timedelta(days=window_days - 1) if window_days > 0 else today
    since = datetime(start_day.year, start_day.month, start_day.day, tzinfo=UTC)

    severity_breakdown = {level.value: 0 for level in RiskLevel}
    severity_breakdown.update(alert_repo.count_active_grouped_by_severity())

    counts_by_day = dict(alert_repo.count_by_day(since=since))
    alerts_over_time: list[dict[str, Any]] = []
    day = start_day
    while day <= today:
        key = day.isoformat()
        alerts_over_time.append({"date": key, "count": counts_by_day.get(key, 0)})
        day += timedelta(days=1)

    return {
        "active_alert_count": alert_repo.count_active(),
        "open_case_count": case_repo.count_by_status(OPEN_STATUSES),
        "avg_risk_score": alert_repo.avg_active_risk_score(),
        "severity_breakdown": severity_breakdown,
        "alerts_over_time": alerts_over_time,
        "window_days": window_days,
    }
