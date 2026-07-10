from __future__ import annotations

import pandas as pd

from detection.detectors.layering import LayeringDetector
from tests.detection.detectors.conftest import ts


def test_detects_a_decaying_layering_chain(make_store) -> None:
    txns = pd.DataFrame(
        [
            {"source_account": "A", "dest_account": "B", "amount": 100_000.0,
             "timestamp": ts("2026-01-01 10:00"), "channel": "NEFT"},
            {"source_account": "B", "dest_account": "C", "amount": 80_000.0,
             "timestamp": ts("2026-01-01 10:20"), "channel": "NEFT"},
            {"source_account": "C", "dest_account": "D", "amount": 60_000.0,
             "timestamp": ts("2026-01-01 10:40"), "channel": "NEFT"},
        ]
    )
    store = make_store(txns)
    results = LayeringDetector().detect(store, txns)

    assert len(results) == 1
    r = results[0]
    assert r.detection_type == "layering"
    assert r.account_ids == ["A", "B", "C", "D"]
    assert r.details["chain_mode"] == "tight"
    assert r.details["amount_decay"] > 0


def test_short_chain_below_min_hops_not_detected(make_store) -> None:
    txns = pd.DataFrame(
        [
            {"source_account": "A", "dest_account": "B", "amount": 100_000.0,
             "timestamp": ts("2026-01-01 10:00"), "channel": "NEFT"},
            {"source_account": "B", "dest_account": "C", "amount": 80_000.0,
             "timestamp": ts("2026-01-01 10:20"), "channel": "NEFT"},
        ]
    )
    store = make_store(txns)
    results = LayeringDetector().detect(store, txns)
    assert results == []


def test_increasing_amounts_and_wide_window_not_detected(make_store) -> None:
    # No decay (amounts increase) and outside both the tight and extended
    # min-hop thresholds -> nothing flagged.
    txns = pd.DataFrame(
        [
            {"source_account": "A", "dest_account": "B", "amount": 10_000.0,
             "timestamp": ts("2026-01-01 10:00"), "channel": "NEFT"},
            {"source_account": "B", "dest_account": "C", "amount": 20_000.0,
             "timestamp": ts("2026-01-01 10:20"), "channel": "NEFT"},
            {"source_account": "C", "dest_account": "D", "amount": 30_000.0,
             "timestamp": ts("2026-01-01 10:40"), "channel": "NEFT"},
        ]
    )
    store = make_store(txns)
    results = LayeringDetector().detect(store, txns)
    assert results == []


def test_params_override_min_hops(make_store) -> None:
    txns = pd.DataFrame(
        [
            {"source_account": "A", "dest_account": "B", "amount": 100_000.0,
             "timestamp": ts("2026-01-01 10:00"), "channel": "NEFT"},
            {"source_account": "B", "dest_account": "C", "amount": 80_000.0,
             "timestamp": ts("2026-01-01 10:20"), "channel": "NEFT"},
        ]
    )
    store = make_store(txns)
    results = LayeringDetector(params={"min_hops": 2}).detect(store, txns)
    assert len(results) == 1
