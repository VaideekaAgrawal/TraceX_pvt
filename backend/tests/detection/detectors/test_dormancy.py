from __future__ import annotations

import pandas as pd

from detection.detectors.dormancy import DormancyDetector
from tests.detection.detectors.conftest import ts


def _dormancy_txns() -> pd.DataFrame:
    rows = []
    # Pre-dormancy: 2 small outgoing transactions, low amounts.
    rows.append({"source_account": "DORM1", "dest_account": "X", "amount": 1_000.0,
                 "timestamp": ts("2026-01-01 09:00"), "channel": "UPI"})
    rows.append({"source_account": "DORM1", "dest_account": "X", "amount": 1_000.0,
                 "timestamp": ts("2026-01-02 09:00"), "channel": "UPI"})
    # Gap of ~400 days, then a burst of 5 large transactions.
    burst_start = ts("2027-02-06 09:00")  # ~400 days after 2026-01-02
    for i in range(5):
        rows.append({
            "source_account": "DORM1", "dest_account": f"Y{i}", "amount": 50_000.0,
            "timestamp": burst_start + pd.Timedelta(hours=i), "channel": "UPI",
        })
    return pd.DataFrame(rows)


def test_detects_dormancy_reactivation_burst(make_store) -> None:
    txns = _dormancy_txns()
    store = make_store(txns)
    results = DormancyDetector().detect(store, txns)

    assert len(results) == 1
    r = results[0]
    assert r.account_ids == ["DORM1"]
    assert r.details["dormancy_days"] >= 180
    assert r.details["burst_multiplier"] >= 10
    assert r.severity in {"HIGH", "CRITICAL"}


def test_regular_activity_no_gap_not_detected(make_store) -> None:
    rows = []
    for i in range(10):
        rows.append({
            "source_account": "REG1", "dest_account": "X", "amount": 1_000.0,
            "timestamp": ts("2026-01-01 09:00") + pd.Timedelta(days=i), "channel": "UPI",
        })
    txns = pd.DataFrame(rows)
    store = make_store(txns)
    results = DormancyDetector().detect(store, txns)
    assert results == []


def test_burst_below_multiplier_threshold_not_detected(make_store) -> None:
    rows = []
    rows.append({"source_account": "DORM2", "dest_account": "X", "amount": 40_000.0,
                 "timestamp": ts("2026-01-01 09:00"), "channel": "UPI"})
    rows.append({"source_account": "DORM2", "dest_account": "X", "amount": 40_000.0,
                 "timestamp": ts("2026-01-02 09:00"), "channel": "UPI"})
    burst_start = ts("2027-02-06 09:00")
    # Burst amounts only ~2x the pre-dormancy average, well below the 10x
    # multiplier threshold.
    for i in range(5):
        rows.append({
            "source_account": "DORM2", "dest_account": f"Y{i}", "amount": 80_000.0,
            "timestamp": burst_start + pd.Timedelta(hours=i), "channel": "UPI",
        })
    txns = pd.DataFrame(rows)
    store = make_store(txns)
    results = DormancyDetector().detect(store, txns)
    assert results == []


def test_params_override_threshold_days(make_store) -> None:
    txns = _dormancy_txns()
    store = make_store(txns)
    # Raise the gap threshold above the actual ~400-day gap -> no detection.
    results = DormancyDetector(params={"threshold_days": 500}).detect(store, txns)
    assert results == []
