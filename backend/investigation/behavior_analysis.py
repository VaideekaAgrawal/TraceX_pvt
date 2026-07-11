"""
Historical Behaviour Analysis (ROADMAP Phase 6; `SYSTEM_DEVELOPMENT_PLAN.md`
§4.2). Pure reducers over an already-fetched `list[Transaction]` for one
account, matching `investigation.account_facts.transaction_stats`'s
convention -- no DB access except in `analyze()`, which fetches once and
hands the same list to every reducer below.

Nothing in this codebase or the archive does historical-behavior
aggregation before this (the archive's `DormancyDetector` is reference-only
*logic*, not portable code -- its own `temporal_bfs` is documented-buggy,
BUG-001, and is explicitly NOT ported here or anywhere else this phase).
This module is genuinely net-new.

Ships 5 of the spec's 7 items: monthly spending, cash deposit trend,
transfer trend, dormant-account activation, velocity increase. Explicitly
DEFERRED (documented, not silently dropped -- `analyze()`'s response
includes a `"deferred"` list so this gap is visible in the API itself):

  - salary mismatch: no pay-cycle-expectation concept exists in this
    schema (only `Customer.declared_annual_income`, a single self-declared
    annual figure with no expected pay date/frequency to compare against).
  - seasonal trends: no formula for "seasonal" exists anywhere to port, and
    this dataset has no multi-year span to detect a season *over*.

`dormancy_reactivation` adapts the archive `DormancyDetector`'s
inactivity-gap-then-burst *logic* to this schema's real transaction shape
-- not its code, which predates this schema and isn't otherwise portable.
Its constants (`gap_days`/`burst_window_days`/`burst_min_txns`) and
`velocity_increase`'s (`recent_weeks`/`threshold`) are documented judgment
calls -- no formula for either exists anywhere to port, same precedent as
`investigation.network_risk`'s weights.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from db.models.reference import Transaction
from db.repositories.reference import TransactionRepository
from investigation.case_graph import CASE_SCOPE_TRANSACTION_LIMIT

#: Spec items 5 ("salary mismatch") and 7 ("seasonal trends") -- see module
#: docstring for why each is deferred rather than faked.
_DEFERRED_ITEMS = ["salary_mismatch", "seasonal_trends"]


def _month_key(ts: datetime) -> str:
    return f"{ts.year:04d}-{ts.month:02d}"


def monthly_totals(txns: list[Transaction], account_id: str) -> list[dict[str, Any]]:
    """Monthly inflow/outflow/total for `account_id`, sorted ascending by
    month -- "monthly spending" (spec item 1)."""
    buckets: dict[str, dict[str, Any]] = {}
    for txn in txns:
        if txn.source_account != account_id and txn.dest_account != account_id:
            continue
        key = _month_key(txn.timestamp)
        bucket = buckets.setdefault(
            key, {"month": key, "total_in": 0.0, "total_out": 0.0, "txn_count": 0}
        )
        if txn.dest_account == account_id:
            bucket["total_in"] += float(txn.amount)
        if txn.source_account == account_id:
            bucket["total_out"] += float(txn.amount)
        bucket["txn_count"] += 1
    result = []
    for key in sorted(buckets):
        bucket = buckets[key]
        bucket["total"] = bucket["total_in"] + bucket["total_out"]
        result.append(bucket)
    return result


def cash_deposit_trend(txns: list[Transaction], account_id: str) -> list[dict[str, Any]]:
    """Monthly cash-deposit totals -- `channel == branch_cash` AND
    `account_id` is the receiving side (spec item 2)."""
    buckets: dict[str, dict[str, Any]] = {}
    for txn in txns:
        if txn.dest_account != account_id:
            continue
        if str(txn.channel) != "branch_cash":
            continue
        key = _month_key(txn.timestamp)
        bucket = buckets.setdefault(key, {"month": key, "cash_deposit_total": 0.0, "txn_count": 0})
        bucket["cash_deposit_total"] += float(txn.amount)
        bucket["txn_count"] += 1
    return [buckets[key] for key in sorted(buckets)]


def transfer_trend(txns: list[Transaction], account_id: str) -> list[dict[str, Any]]:
    """Monthly transfer totals -- `txn_type == "transfer"` (the schema's
    own field, not an invented channel heuristic), touching `account_id`
    (spec item 3)."""
    buckets: dict[str, dict[str, Any]] = {}
    for txn in txns:
        if txn.source_account != account_id and txn.dest_account != account_id:
            continue
        if txn.txn_type != "transfer":
            continue
        key = _month_key(txn.timestamp)
        bucket = buckets.setdefault(key, {"month": key, "transfer_total": 0.0, "txn_count": 0})
        bucket["transfer_total"] += float(txn.amount)
        bucket["txn_count"] += 1
    return [buckets[key] for key in sorted(buckets)]


def dormancy_reactivation(
    txns: list[Transaction],
    account_id: str,
    *,
    gap_days: int = 90,
    burst_window_days: int = 7,
    burst_min_txns: int = 3,
) -> dict[str, Any]:
    """Flags a dormant-then-reactivated account: an inactivity gap of at
    least `gap_days` between two consecutive transactions touching
    `account_id`, immediately followed by a burst of at least
    `burst_min_txns` transactions within `burst_window_days` of the gap
    ending (spec item 4). Adapted from the archive `DormancyDetector`'s
    gap-then-burst *logic*, not its code (see module docstring)."""
    own = sorted(
        (t for t in txns if t.source_account == account_id or t.dest_account == account_id),
        key=lambda t: t.timestamp,
    )
    events: list[dict[str, Any]] = []
    for i in range(1, len(own)):
        gap = own[i].timestamp - own[i - 1].timestamp
        if gap < timedelta(days=gap_days):
            continue
        burst_end = own[i].timestamp + timedelta(days=burst_window_days)
        burst_count = sum(1 for t in own[i:] if own[i].timestamp <= t.timestamp <= burst_end)
        if burst_count >= burst_min_txns:
            events.append(
                {
                    "gap_start": own[i - 1].timestamp,
                    "gap_end": own[i].timestamp,
                    "gap_days": gap.days,
                    "burst_txn_count": burst_count,
                }
            )
    return {"reactivation_detected": bool(events), "events": events}


def velocity_increase(
    txns: list[Transaction],
    account_id: str,
    *,
    recent_weeks: int = 4,
    threshold: float = 2.0,
) -> dict[str, Any]:
    """Flags a recent spike in transaction frequency: the average weekly
    transaction count over the most recent `recent_weeks` (ending at the
    account's own last transaction, not "now" -- so this is stable for
    historical/backfilled data, not just live data) versus the average
    weekly count over everything before that window (spec item 6).
    `threshold=2.0` -- recent activity at least double the baseline rate --
    is a judgment call (see module docstring)."""
    own = sorted(
        (t for t in txns if t.source_account == account_id or t.dest_account == account_id),
        key=lambda t: t.timestamp,
    )
    if len(own) < 2:
        return {
            "recent_avg_weekly_txn_count": 0.0,
            "baseline_avg_weekly_txn_count": 0.0,
            "ratio": None,
            "velocity_increase_detected": False,
        }
    latest = own[-1].timestamp
    cutoff = latest - timedelta(weeks=recent_weeks)
    recent = [t for t in own if t.timestamp > cutoff]
    baseline = [t for t in own if t.timestamp <= cutoff]

    recent_avg = len(recent) / recent_weeks if recent_weeks > 0 else 0.0
    if baseline:
        baseline_span_days = max((cutoff - baseline[0].timestamp).days, 1)
        baseline_weeks = baseline_span_days / 7.0
        baseline_avg = len(baseline) / baseline_weeks if baseline_weeks > 0 else 0.0
    else:
        baseline_avg = 0.0

    ratio = (recent_avg / baseline_avg) if baseline_avg > 0 else None
    detected = ratio is not None and ratio >= threshold
    return {
        "recent_avg_weekly_txn_count": recent_avg,
        "baseline_avg_weekly_txn_count": baseline_avg,
        "ratio": ratio,
        "velocity_increase_detected": detected,
    }


def analyze(session: Session, case_id: str, account_id: str) -> dict[str, Any]:
    """Fetch `account_id`'s transactions once (`limit=CASE_SCOPE_
    TRANSACTION_LIMIT` -- same case-scoped-is-small-but-not-500 reasoning as
    every other Phase 5/6 caller of `list_for_account_in_window`) and run
    every reducer above over it. `case_id` is accepted but not otherwise
    used here -- kept for signature consistency with this module's sibling
    L2 functions (`investigation.customer_profile.build_customer_profile`,
    `investigation.timeline.build_timeline`), which `api.routes.l2`'s route
    handlers call the same way, even though this function's own computation
    is single-account and doesn't need case scope."""
    txns = TransactionRepository(session).list_for_account_in_window(
        account_id, limit=CASE_SCOPE_TRANSACTION_LIMIT
    )
    return {
        "account_id": account_id,
        "monthly_totals": monthly_totals(txns, account_id),
        "cash_deposit_trend": cash_deposit_trend(txns, account_id),
        "transfer_trend": transfer_trend(txns, account_id),
        "dormancy_reactivation": dormancy_reactivation(txns, account_id),
        "velocity_increase": velocity_increase(txns, account_id),
        "deferred": list(_DEFERRED_ITEMS),
    }
