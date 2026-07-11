"""
`investigation.behavior_analysis` -- ROADMAP Phase 6 Historical Behaviour
Analysis. Every reducer is a pure function over a hand-built
`list[Transaction]`-shaped set of `SimpleNamespace` stand-ins (matching
`investigation.account_facts.transaction_stats`'s own "pure function, no DB
access" testing style -- no need for a real ORM row when only a handful of
attributes are read).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast

from sqlalchemy.orm import Session

from db.enums import ActorType, Channel
from db.models.reference import Transaction
from db.repositories.reference import AccountRepository, TransactionRepository
from investigation.behavior_analysis import (
    analyze,
    cash_deposit_trend,
    dormancy_reactivation,
    monthly_totals,
    transfer_trend,
    velocity_increase,
)


def _txn(
    txn_id: str, src: str, dst: str, amount: float, ts: datetime,
    *, channel: str = "NEFT", txn_type: str = "transfer",
) -> Transaction:
    # A `SimpleNamespace` stand-in, not a real ORM row -- every reducer
    # below only reads a handful of attributes (matching `investigation.
    # account_facts.transaction_stats`'s own "pure function, no DB access"
    # testing style). `cast` tells mypy to trust the duck-typed shape.
    return cast(
        Transaction,
        SimpleNamespace(
            txn_id=txn_id, source_account=src, dest_account=dst, amount=amount,
            timestamp=ts, channel=channel, txn_type=txn_type, is_laundering=0,
        ),
    )


def test_monthly_totals_groups_by_calendar_month() -> None:
    txns = [
        _txn("T1", "A", "B", 100.0, datetime(2026, 1, 5, tzinfo=UTC)),
        _txn("T2", "B", "A", 50.0, datetime(2026, 1, 20, tzinfo=UTC)),
        _txn("T3", "A", "B", 200.0, datetime(2026, 2, 1, tzinfo=UTC)),
    ]

    result = monthly_totals(txns, "A")

    assert [r["month"] for r in result] == ["2026-01", "2026-02"]
    jan = result[0]
    assert jan["total_out"] == 100.0
    assert jan["total_in"] == 50.0
    assert jan["total"] == 150.0
    assert jan["txn_count"] == 2
    feb = result[1]
    assert feb["total_out"] == 200.0
    assert feb["txn_count"] == 1


def test_cash_deposit_trend_only_incoming_branch_cash() -> None:
    ts = datetime(2026, 1, 1, tzinfo=UTC)
    txns = [
        _txn("T1", "X", "A", 5_000.0, ts, channel="branch_cash"),  # incoming cash deposit
        _txn("T2", "A", "X", 5_000.0, ts, channel="branch_cash"),  # outgoing -- not a deposit
        _txn("T3", "X", "A", 100.0, ts, channel="UPI"),  # incoming but not cash
    ]

    result = cash_deposit_trend(txns, "A")

    assert len(result) == 1
    assert result[0]["cash_deposit_total"] == 5_000.0
    assert result[0]["txn_count"] == 1


def test_transfer_trend_only_transfer_type() -> None:
    ts = datetime(2026, 1, 1, tzinfo=UTC)
    txns = [
        _txn("T1", "A", "B", 300.0, ts, txn_type="transfer"),
        _txn("T2", "A", "B", 999.0, ts, txn_type="atm_withdrawal"),
    ]

    result = transfer_trend(txns, "A")

    assert len(result) == 1
    assert result[0]["transfer_total"] == 300.0


def test_dormancy_reactivation_flags_gap_then_burst() -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    txns = [_txn("T0", "A", "B", 100.0, base)]
    reactivation_start = base + timedelta(days=120)  # gap well past the 90-day default
    for i in range(3):
        txns.append(
            _txn(f"BURST{i}", "A", "B", 100.0, reactivation_start + timedelta(days=i))
        )

    result = dormancy_reactivation(txns, "A")

    assert result["reactivation_detected"] is True
    assert len(result["events"]) == 1
    assert result["events"][0]["burst_txn_count"] == 3


def test_dormancy_reactivation_steady_activity_not_flagged() -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    txns = [_txn(f"T{i}", "A", "B", 100.0, base + timedelta(days=i * 3)) for i in range(10)]

    result = dormancy_reactivation(txns, "A")

    assert result["reactivation_detected"] is False
    assert result["events"] == []


def test_dormancy_reactivation_gap_without_burst_not_flagged() -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    txns = [
        _txn("T0", "A", "B", 100.0, base),
        _txn("T1", "A", "B", 100.0, base + timedelta(days=120)),  # long gap
        # only ONE transaction after the gap -- below burst_min_txns=3
    ]

    result = dormancy_reactivation(txns, "A")

    assert result["reactivation_detected"] is False


def test_velocity_increase_detects_recent_spike() -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    txns = []
    # Sparse baseline: one txn every 2 weeks for ~12 weeks.
    for i in range(6):
        txns.append(_txn(f"BASE{i}", "A", "B", 100.0, base + timedelta(weeks=2 * i)))
    baseline_end = base + timedelta(weeks=10)
    # Dense recent burst: many txns in the last 4 weeks.
    for i in range(20):
        txns.append(
            _txn(f"RECENT{i}", "A", "B", 100.0, baseline_end + timedelta(days=i))
        )

    result = velocity_increase(txns, "A", recent_weeks=4, threshold=2.0)

    assert result["velocity_increase_detected"] is True
    assert result["ratio"] is not None
    assert result["ratio"] >= 2.0


def test_velocity_increase_steady_rate_not_flagged() -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    txns = [_txn(f"T{i}", "A", "B", 100.0, base + timedelta(days=i * 3)) for i in range(30)]

    result = velocity_increase(txns, "A", recent_weeks=4, threshold=2.0)

    assert result["velocity_increase_detected"] is False


def test_velocity_increase_too_few_transactions_returns_not_detected() -> None:
    result = velocity_increase([], "A")
    assert result["velocity_increase_detected"] is False
    assert result["ratio"] is None


def test_analyze_wires_every_reducer_and_lists_deferred_items(session: Session) -> None:
    AccountRepository(session).create(account_id="A", actor_type=ActorType.SYSTEM, actor_id=None)
    AccountRepository(session).create(account_id="B", actor_type=ActorType.SYSTEM, actor_id=None)
    session.commit()
    ts = datetime(2026, 1, 1, tzinfo=UTC)
    TransactionRepository(session).create(
        txn_id="T1", timestamp=ts, source_account="A", dest_account="B", amount=1_000.0,
        channel=Channel.UPI, is_laundering=0, ingested_at=ts,
        actor_type=ActorType.SYSTEM, actor_id=None,
    )
    session.commit()

    result = analyze(session, "CASE1", "A")

    assert result["account_id"] == "A"
    assert result["monthly_totals"][0]["total_out"] == 1_000.0
    assert "cash_deposit_trend" in result
    assert "transfer_trend" in result
    assert "dormancy_reactivation" in result
    assert "velocity_increase" in result
    # Gap is visible in the API itself, not silently dropped (module
    # docstring: "salary mismatch"/"seasonal trends" have no backing
    # schema/data to compute from).
    assert result["deferred"] == ["salary_mismatch", "seasonal_trends"]
