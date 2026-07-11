"""
Previous Alert Summary (ROADMAP Phase 5, `SYSTEM_DEVELOPMENT_PLAN.md` §4.1):
"count of prior alerts/SARs/false-positives on the account, risk trend."

Deliberately scoped to one account's own `alerts.primary_account_id` history
-- NOT the full connected-network reach ("Previous Alert & Case History
(network-wide)", §4.2, an L2/Phase 6-7 feature that walks every account in
the case-scoped graph, not just the one being triaged). Widening this now
would silently absorb Phase 6/7 scope into Phase 5's L1 triage surface.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from db.enums import CaseResolution
from db.repositories.detection import AlertRepository
from db.repositories.investigation import CaseRepository


def summarize(
    session: Session, account_id: str, *, exclude_case_id: str | None = None
) -> dict[str, Any]:
    """Prior-alert stats for `account_id` (as primary account), across every
    alert except ones belonging to `exclude_case_id` (the case currently
    being triaged -- its own alerts aren't "previous").

    `prior_sar_count`/`prior_false_positive_count`/`prior_monitoring_count`
    are tallied by resolving each alert's `case_id` (if any) to its `Case`
    row and reading `Case.resolution` -- an alert with no case yet, or whose
    case isn't closed, contributes to `total_prior_alerts` and `risk_trend`
    but not to any of the three resolution buckets.

    `AlertRepository.list_for_primary_account` returns most-recent-first
    (so that this account's *newest* activity survives its `limit`, not its
    oldest) -- `risk_trend` re-sorts ascending by `created_at` here, since
    "trend" reads left-to-right chronologically and that display order
    shouldn't depend on the repository's own limit-truncation order.
    """
    alert_repo = AlertRepository(session)
    case_repo = CaseRepository(session)

    alerts = sorted(
        (
            a
            for a in alert_repo.list_for_primary_account(account_id)
            if a.case_id != exclude_case_id
        ),
        key=lambda a: a.created_at,
    )

    prior_sar_count = 0
    prior_false_positive_count = 0
    prior_monitoring_count = 0
    risk_trend: list[dict[str, Any]] = []
    case_cache: dict[str, Any] = {}

    for alert in alerts:
        risk_trend.append(
            {
                "alert_id": alert.alert_id,
                "created_at": alert.created_at,
                "risk_score": alert.risk_score,
            }
        )
        if alert.case_id is None:
            continue
        if alert.case_id not in case_cache:
            case_cache[alert.case_id] = case_repo.get(alert.case_id)
        case = case_cache[alert.case_id]
        if case is None:
            continue
        if case.resolution == CaseResolution.TRUE_POSITIVE_SAR:
            prior_sar_count += 1
        elif case.resolution == CaseResolution.FALSE_POSITIVE:
            prior_false_positive_count += 1
        elif case.resolution == CaseResolution.ENHANCED_MONITORING:
            prior_monitoring_count += 1

    return {
        "total_prior_alerts": len(alerts),
        "prior_sar_count": prior_sar_count,
        "prior_false_positive_count": prior_false_positive_count,
        "prior_monitoring_count": prior_monitoring_count,
        "risk_trend": risk_trend,
    }
