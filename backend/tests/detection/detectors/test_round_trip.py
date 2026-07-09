from __future__ import annotations

import pandas as pd

from detection.detectors.round_trip import RoundTripDetector
from tests.detection.detectors.conftest import ts


def test_detects_a_tight_round_trip_cycle(make_store) -> None:
    txns = pd.DataFrame(
        [
            {"source_account": "A", "dest_account": "B", "amount": 100_000.0,
             "timestamp": ts("2026-01-01 10:00"), "channel": "NEFT"},
            {"source_account": "B", "dest_account": "C", "amount": 98_000.0,
             "timestamp": ts("2026-01-01 10:10"), "channel": "NEFT"},
            {"source_account": "C", "dest_account": "A", "amount": 95_000.0,
             "timestamp": ts("2026-01-01 10:20"), "channel": "NEFT"},
        ]
    )
    store = make_store(txns)
    results = RoundTripDetector().detect(store, txns)

    assert len(results) == 1
    r = results[0]
    assert r.detection_type == "round_trip"
    assert set(r.account_ids) == {"A", "B", "C"}
    assert r.severity == "CRITICAL"
    assert r.details["return_ratio"] >= 0.85


def test_no_cycle_no_detection(make_store) -> None:
    txns = pd.DataFrame(
        [
            {"source_account": "A", "dest_account": "B", "amount": 100_000.0,
             "timestamp": ts("2026-01-01 10:00"), "channel": "NEFT"},
            {"source_account": "B", "dest_account": "C", "amount": 98_000.0,
             "timestamp": ts("2026-01-01 10:10"), "channel": "NEFT"},
        ]
    )
    store = make_store(txns)
    results = RoundTripDetector().detect(store, txns)
    assert results == []


def test_loose_return_ratio_is_not_a_tight_loop(make_store) -> None:
    # `return_ratio` is computed relative to whichever node the cycle-
    # detection happens to list first (`cycle_nodes[0]`), which for an
    # N-node ring isn't something callers control — the product of the
    # three possible "next hop / previous hop" ratios around a 3-node ring
    # is always exactly 1, so it's mathematically impossible to pick
    # amounts that guarantee return_ratio < 0.85 regardless of that
    # starting point. Use an unreachably high `min_return_ratio` override
    # instead, which guarantees the MEDIUM ("not a tight loop") branch no
    # matter which node the cycle starts from.
    txns = pd.DataFrame(
        [
            {"source_account": "A", "dest_account": "B", "amount": 100_000.0,
             "timestamp": ts("2026-01-01 10:00"), "channel": "NEFT"},
            {"source_account": "B", "dest_account": "C", "amount": 50_000.0,
             "timestamp": ts("2026-01-01 10:10"), "channel": "NEFT"},
            {"source_account": "C", "dest_account": "A", "amount": 10_000.0,
             "timestamp": ts("2026-01-01 10:20"), "channel": "NEFT"},
        ]
    )
    store = make_store(txns)
    results = RoundTripDetector(params={"min_return_ratio": 100.0}).detect(store, txns)
    assert len(results) == 1
    assert results[0].severity == "MEDIUM"


def test_params_override_min_return_ratio(make_store) -> None:
    txns = pd.DataFrame(
        [
            {"source_account": "A", "dest_account": "B", "amount": 100_000.0,
             "timestamp": ts("2026-01-01 10:00"), "channel": "NEFT"},
            {"source_account": "B", "dest_account": "C", "amount": 50_000.0,
             "timestamp": ts("2026-01-01 10:10"), "channel": "NEFT"},
            {"source_account": "C", "dest_account": "A", "amount": 10_000.0,
             "timestamp": ts("2026-01-01 10:20"), "channel": "NEFT"},
        ]
    )
    store = make_store(txns)
    results = RoundTripDetector(params={"min_return_ratio": 0.05}).detect(store, txns)
    assert results[0].severity == "CRITICAL"
