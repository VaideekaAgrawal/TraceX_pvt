from __future__ import annotations

import pandas as pd

from detection.detectors.fan_out import FanOutFanInDetector
from tests.detection.detectors.conftest import ts


def test_fan_out_detected(make_store) -> None:
    hub = "HUB"
    rows = [
        {"source_account": hub, "dest_account": f"D{i}", "amount": 10_000.0,
         "timestamp": ts("2026-01-01 09:00") + pd.Timedelta(minutes=i), "channel": "UPI"}
        for i in range(6)
    ]
    txns = pd.DataFrame(rows)
    store = make_store(txns)
    results = FanOutFanInDetector().detect(store, txns)

    fan_out_hits = [
        r for r in results
        if r.detection_type == "fan_out" and r.details.get("hub_account") == hub
    ]
    assert len(fan_out_hits) == 1
    assert fan_out_hits[0].details["unique_destinations"] == 6


def test_fan_in_detected(make_store) -> None:
    hub = "HUB"
    rows = [
        {"source_account": f"S{i}", "dest_account": hub, "amount": 10_000.0,
         "timestamp": ts("2026-01-01 09:00") + pd.Timedelta(minutes=i), "channel": "UPI"}
        for i in range(6)
    ]
    txns = pd.DataFrame(rows)
    store = make_store(txns)
    results = FanOutFanInDetector().detect(store, txns)

    fan_in_hits = [
        r for r in results
        if r.detection_type == "fan_in" and r.details.get("hub_account") == hub
    ]
    assert len(fan_in_hits) == 1
    assert fan_in_hits[0].details["unique_sources"] == 6


def test_below_min_degree_not_detected(make_store) -> None:
    hub = "HUB"
    rows = [
        {"source_account": hub, "dest_account": f"D{i}", "amount": 10_000.0,
         "timestamp": ts("2026-01-01 09:00") + pd.Timedelta(minutes=i), "channel": "UPI"}
        for i in range(2)
    ]
    txns = pd.DataFrame(rows)
    store = make_store(txns)
    results = FanOutFanInDetector().detect(store, txns)
    assert results == []


def test_bipartite_scatter_gather_detected(make_store) -> None:
    sources = [f"S{i}" for i in range(3)]
    dests = [f"D{i}" for i in range(3)]
    rows = []
    for s in sources:
        for d in dests:
            rows.append({
                "source_account": s, "dest_account": d, "amount": 50_000.0,
                "timestamp": ts("2026-01-01 09:00"), "channel": "UPI",
            })
    txns = pd.DataFrame(rows)
    store = make_store(txns)
    results = FanOutFanInDetector().detect(store, txns)

    bipartite_hits = [r for r in results if r.details.get("sub_type") == "bipartite"]
    assert len(bipartite_hits) >= 1
    assert bipartite_hits[0].details["left_size"] >= 3
    assert bipartite_hits[0].details["right_size"] >= 3


def test_params_override_min_degree(make_store) -> None:
    hub = "HUB"
    rows = [
        {"source_account": hub, "dest_account": f"D{i}", "amount": 10_000.0,
         "timestamp": ts("2026-01-01 09:00") + pd.Timedelta(minutes=i), "channel": "UPI"}
        for i in range(2)
    ]
    txns = pd.DataFrame(rows)
    store = make_store(txns)
    results = FanOutFanInDetector(params={"min_degree": 2}).detect(store, txns)
    fan_out_hits = [r for r in results if r.detection_type == "fan_out"]
    assert len(fan_out_hits) == 1
