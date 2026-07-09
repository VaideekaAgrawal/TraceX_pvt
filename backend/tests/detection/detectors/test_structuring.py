from __future__ import annotations

import pandas as pd

from detection.detectors.structuring import StructuringDetector
from tests.detection.detectors.conftest import ts


def test_classic_structuring_detected(make_store) -> None:
    # 3 transactions just under the CTR threshold from the same source
    # within the rolling window -> classic structuring.
    txns = pd.DataFrame(
        [
            {"source_account": "A", "dest_account": "B", "amount": 950_000.0,
             "timestamp": ts("2026-01-01 10:00"), "channel": "NEFT"},
            {"source_account": "A", "dest_account": "C", "amount": 960_000.0,
             "timestamp": ts("2026-01-02 10:00"), "channel": "NEFT"},
            {"source_account": "A", "dest_account": "D", "amount": 970_000.0,
             "timestamp": ts("2026-01-03 10:00"), "channel": "NEFT"},
        ]
    )
    store = make_store(txns)
    results = StructuringDetector().detect(store, txns)

    assert len(results) == 1
    r = results[0]
    assert r.account_ids == ["A"]
    assert r.details["sub_type"] == "classic"
    assert r.details["near_threshold_count"] == 3


def test_below_min_count_not_detected(make_store) -> None:
    txns = pd.DataFrame(
        [
            {"source_account": "A", "dest_account": "B", "amount": 950_000.0,
             "timestamp": ts("2026-01-01 10:00"), "channel": "NEFT"},
            {"source_account": "A", "dest_account": "C", "amount": 960_000.0,
             "timestamp": ts("2026-01-02 10:00"), "channel": "NEFT"},
        ]
    )
    store = make_store(txns)
    results = StructuringDetector().detect(store, txns)
    assert results == []


def test_split_structuring_detected(make_store) -> None:
    # Several smaller same-day transactions summing to near-threshold.
    txns = pd.DataFrame(
        [
            {"source_account": "A", "dest_account": "B", "amount": 300_000.0,
             "timestamp": ts("2026-01-01 09:00"), "channel": "NEFT"},
            {"source_account": "A", "dest_account": "C", "amount": 300_000.0,
             "timestamp": ts("2026-01-01 11:00"), "channel": "NEFT"},
            {"source_account": "A", "dest_account": "D", "amount": 300_000.0,
             "timestamp": ts("2026-01-01 13:00"), "channel": "NEFT"},
        ]
    )
    store = make_store(txns)
    results = StructuringDetector().detect(store, txns)

    assert len(results) == 1
    assert results[0].details["sub_type"] == "split"
    assert results[0].details["transaction_count"] == 3


def test_amounts_above_ctr_threshold_not_flagged(make_store) -> None:
    txns = pd.DataFrame(
        [
            {"source_account": "A", "dest_account": "B", "amount": 1_500_000.0,
             "timestamp": ts("2026-01-01 10:00"), "channel": "NEFT"},
            {"source_account": "A", "dest_account": "C", "amount": 1_600_000.0,
             "timestamp": ts("2026-01-02 10:00"), "channel": "NEFT"},
            {"source_account": "A", "dest_account": "D", "amount": 1_700_000.0,
             "timestamp": ts("2026-01-03 10:00"), "channel": "NEFT"},
        ]
    )
    store = make_store(txns)
    results = StructuringDetector().detect(store, txns)
    assert results == []


def test_params_override_min_count(make_store) -> None:
    txns = pd.DataFrame(
        [
            {"source_account": "A", "dest_account": "B", "amount": 950_000.0,
             "timestamp": ts("2026-01-01 10:00"), "channel": "NEFT"},
            {"source_account": "A", "dest_account": "C", "amount": 960_000.0,
             "timestamp": ts("2026-01-02 10:00"), "channel": "NEFT"},
        ]
    )
    store = make_store(txns)
    results = StructuringDetector(params={"min_count": 2}).detect(store, txns)
    assert len(results) == 1
