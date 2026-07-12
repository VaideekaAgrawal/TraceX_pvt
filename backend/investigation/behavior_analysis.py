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

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from db.models.reference import Transaction
from db.repositories.investigation import CaseAccountRepository
from db.repositories.reference import TransactionRepository
from investigation.case_graph import CASE_SCOPE_TRANSACTION_LIMIT

#: Spec items 5 ("salary mismatch") and 7 ("seasonal trends") -- see module
#: docstring for why each is deferred rather than faked.
_DEFERRED_ITEMS = ["salary_mismatch", "seasonal_trends"]


def _month_key(ts: datetime) -> str:
    return f"{ts.year:04d}-{ts.month:02d}"


def _bucket_by_month(
    txns: list[Transaction],
    *,
    include: Callable[[Transaction], bool],
    amounts_of: Callable[[Transaction], dict[str, float]],
) -> list[dict[str, Any]]:
    """Shared "filter -> bucket by calendar month -> sum one or more amount
    fields -> sort ascending" reducer (code-review finding, Phase 6:
    `monthly_totals`/`cash_deposit_trend`/`transfer_trend` each hand-rolled
    an identical version of this loop).

    `include(txn)` decides which transactions count toward the bucket set
    at all. `amounts_of(txn)` returns a `{field_name: amount_to_add}` dict
    for a counted transaction -- may be empty (a transaction that counts
    toward `txn_count` but contributes to no summed field this call cares
    about). `cash_deposit_trend`/`transfer_trend` each contribute exactly
    one field; `monthly_totals` contributes `total_in`/`total_out`
    conditionally per transaction and fills in whichever field a given
    month never saw a contribution for afterward (see its own docstring)."""
    buckets: dict[str, dict[str, Any]] = {}
    for txn in txns:
        if not include(txn):
            continue
        key = _month_key(txn.timestamp)
        bucket = buckets.setdefault(key, {"month": key, "txn_count": 0})
        for field, amount in amounts_of(txn).items():
            bucket[field] = bucket.get(field, 0.0) + amount
        bucket["txn_count"] += 1
    return [buckets[key] for key in sorted(buckets)]


def monthly_totals(txns: list[Transaction], account_id: str) -> list[dict[str, Any]]:
    """Monthly inflow/outflow/total for `account_id`, sorted ascending by
    month -- "monthly spending" (spec item 1)."""

    def amounts_of(txn: Transaction) -> dict[str, float]:
        amounts: dict[str, float] = {}
        if txn.dest_account == account_id:
            amounts["total_in"] = float(txn.amount)
        if txn.source_account == account_id:
            amounts["total_out"] = float(txn.amount)
        return amounts

    buckets = _bucket_by_month(
        txns,
        include=lambda t: t.source_account == account_id or t.dest_account == account_id,
        amounts_of=amounts_of,
    )
    for bucket in buckets:
        # A month whose transactions were entirely one-directional never got
        # the other field set by `_bucket_by_month`'s `amounts_of` -- fill it
        # in so every bucket always carries both fields, matching this
        # function's pre-existing contract.
        bucket.setdefault("total_in", 0.0)
        bucket.setdefault("total_out", 0.0)
        bucket["total"] = bucket["total_in"] + bucket["total_out"]
    return buckets


def cash_deposit_trend(txns: list[Transaction], account_id: str) -> list[dict[str, Any]]:
    """Monthly cash-deposit totals -- `channel == branch_cash` AND
    `account_id` is the receiving side (spec item 2)."""
    return _bucket_by_month(
        txns,
        include=lambda t: t.dest_account == account_id and str(t.channel) == "branch_cash",
        amounts_of=lambda t: {"cash_deposit_total": float(t.amount)},
    )


def transfer_trend(txns: list[Transaction], account_id: str) -> list[dict[str, Any]]:
    """Monthly transfer totals -- `txn_type == "transfer"` (the schema's
    own field, not an invented channel heuristic), touching `account_id`
    (spec item 3)."""
    return _bucket_by_month(
        txns,
        include=lambda t: (
            (t.source_account == account_id or t.dest_account == account_id)
            and t.txn_type == "transfer"
        ),
        amounts_of=lambda t: {"transfer_total": float(t.amount)},
    )


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
    """Validates `account_id` is in `case_id`'s scope (defense-in-depth --
    see `investigation.timeline.build_timeline`'s docstring for the same
    pattern/reasoning; raises `ValueError` otherwise), then fetches
    `account_id`'s transactions once (`limit=CASE_SCOPE_TRANSACTION_LIMIT`,
    `most_recent=True` -- code-review finding, Phase 6:
    `velocity_increase`/`dormancy_reactivation` both treat the tail of this
    list as "most recent activity," which the old ascending-then-limit
    order could silently truncate away for an account exceeding the cap)
    and runs every reducer above over it."""
    case_account_ids = set(CaseAccountRepository(session).list_account_ids_for_case(case_id))
    if account_id not in case_account_ids:
        raise ValueError(f"account {account_id!r} is not in case {case_id!r}'s scope")

    txns = TransactionRepository(session).list_for_account_in_window(
        account_id, limit=CASE_SCOPE_TRANSACTION_LIMIT, most_recent=True
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
