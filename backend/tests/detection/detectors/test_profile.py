from __future__ import annotations

import pandas as pd

from detection.detectors.profile import ProfileMismatchDetector
from tests.detection.detectors.conftest import ts


def test_income_mismatch_detected(make_store) -> None:
    accounts = pd.DataFrame(
        {
            "account_id": ["A", "B"],
            # B's declared_annual_income is 0 -> excluded from the check
            # entirely (`accs = accounts[declared_annual_income > 0]`), so
            # only A's volume-vs-income ratio is evaluated here, even
            # though B also receives the full 2.5M (the check is symmetric
            # over total in+out flow, not "sender only" — a real property
            # of the ported code, not a test artifact).
            "declared_annual_income": [100_000.0, 0.0],
        }
    )
    txns = pd.DataFrame(
        [
            {"source_account": "A", "dest_account": "B", "amount": 2_500_000.0,
             "timestamp": ts("2026-01-01 10:00"), "channel": "NEFT"},
        ]
    )
    store = make_store(txns, accounts)
    results = ProfileMismatchDetector().detect(store, txns, accounts)

    income_mismatch = [r for r in results if r.details.get("sub_type") == "income_mismatch"]
    assert len(income_mismatch) == 1
    r = income_mismatch[0]
    assert r.account_ids == ["A"]
    assert r.details["volume_to_income_ratio"] > 10


def test_income_within_ratio_not_detected(make_store) -> None:
    accounts = pd.DataFrame(
        {
            "account_id": ["A", "B"],
            "declared_annual_income": [1_000_000.0, 1_000_000.0],
        }
    )
    txns = pd.DataFrame(
        [
            {"source_account": "A", "dest_account": "B", "amount": 500_000.0,
             "timestamp": ts("2026-01-01 10:00"), "channel": "NEFT"},
        ]
    )
    store = make_store(txns, accounts)
    results = ProfileMismatchDetector().detect(store, txns, accounts)
    assert [r for r in results if r.details.get("sub_type") == "income_mismatch"] == []


def test_peer_zscore_deviation_detected(make_store) -> None:
    peers = [f"P{i}" for i in range(5)]
    outlier = "P_OUT"
    accounts = pd.DataFrame(
        {
            "account_id": [*peers, outlier],
            "occupation": ["clerk"] * 6,
            "income_bracket": ["medium"] * 6,
        }
    )
    rows = []
    for p in peers:
        rows.append({"source_account": p, "dest_account": "SINK", "amount": 10_000.0,
                     "timestamp": ts("2026-01-01 10:00"), "channel": "UPI"})
    rows.append({"source_account": outlier, "dest_account": "SINK", "amount": 5_000_000.0,
                 "timestamp": ts("2026-01-01 10:00"), "channel": "UPI"})
    txns = pd.DataFrame(rows)
    store = make_store(txns, accounts)
    # With only 6 accounts in the peer group, one extreme outlier caps the
    # achievable z-score at (n-1)/sqrt(n) ~= 2.04 regardless of how large
    # the outlier's volume is (a property of the sample std formula, not a
    # detector bug) -- lower the threshold below that cap so this stays a
    # small, fast fixture instead of needing a much larger peer group.
    results = ProfileMismatchDetector(params={"z_threshold": 1.5}).detect(store, txns, accounts)

    peer_hits = [r for r in results if r.details.get("sub_type") == "peer_deviation"]
    assert any(r.account_ids == [outlier] for r in peer_hits)


def test_behavioural_shift_spike_detected(make_store) -> None:
    account_id = "SHIFT1"
    rows = []
    for i in range(20):
        rows.append({
            "source_account": account_id, "dest_account": "SINK",
            "amount": 1_000.0 + (i % 3) * 10,  # small variance so std != 0
            "timestamp": ts("2026-01-01 08:00") + pd.Timedelta(hours=i), "channel": "UPI",
        })
    rows.append({
        "source_account": account_id, "dest_account": "SINK", "amount": 500_000.0,
        "timestamp": ts("2026-01-02 05:00"), "channel": "UPI",
    })
    txns = pd.DataFrame(rows)
    # The account must have a declared profile — a profile-mismatch alert on an
    # entity we have no profile for is meaningless (see _detect_behavioural_shift).
    accounts = pd.DataFrame(
        {"account_id": [account_id, "SINK"], "declared_annual_income": [500_000.0, 500_000.0]}
    )
    store = make_store(txns, accounts)
    results = ProfileMismatchDetector().detect(store, txns, accounts)

    shift_hits = [r for r in results if r.details.get("sub_type") == "behavioural_shift"]
    assert any(r.account_ids == [account_id] for r in shift_hits)


def test_behavioural_shift_is_gated_on_having_a_profile(make_store) -> None:
    """The fix for the 36k-alert noise: an identical spike on an account with NO
    declared income produces NO profile_mismatch alert — you cannot mismatch a
    profile you do not have."""
    account_id = "NOKYC1"
    rows = [
        {
            "source_account": account_id, "dest_account": "SINK",
            "amount": 1_000.0 + (i % 3) * 10,
            "timestamp": ts("2026-01-01 08:00") + pd.Timedelta(hours=i), "channel": "UPI",
        }
        for i in range(20)
    ]
    rows.append({
        "source_account": account_id, "dest_account": "SINK", "amount": 500_000.0,
        "timestamp": ts("2026-01-02 05:00"), "channel": "UPI",
    })
    txns = pd.DataFrame(rows)
    # No declared_annual_income → no profile → no alert.
    accounts = pd.DataFrame(
        {"account_id": [account_id, "SINK"], "declared_annual_income": [0.0, 0.0]}
    )
    store = make_store(txns, accounts)
    results = ProfileMismatchDetector().detect(store, txns, accounts)
    assert [r for r in results if r.details.get("sub_type") == "behavioural_shift"] == []
