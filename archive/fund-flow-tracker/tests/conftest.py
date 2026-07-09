"""
Shared fixtures and synthetic data builders for TraceX tests.

All builders produce (accounts_df, transactions_df) in canonical format
so tests bypass the CSV parser entirely and run against real service code.
"""
import os
import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ──────────────────────────────────────────────────────────────────────────────
# Low-level builders
# ──────────────────────────────────────────────────────────────────────────────

def _make_txn(txn_id, src, dst, amount, ts, channel="NEFT", is_laundering=0):
    return {
        "txn_id": txn_id,
        "source_account": src,
        "dest_account": dst,
        "amount": float(amount),
        "timestamp": pd.Timestamp(ts),
        "channel": channel,
        "txn_type": "transfer",
        "is_laundering": int(is_laundering),
    }


def _make_accounts(account_ids, declared_income=None, occupation="salaried",
                   income_bracket="low"):
    rows = []
    for i, acc_id in enumerate(account_ids):
        income = (declared_income[i] if declared_income else 300_000)
        rows.append({
            "account_id": acc_id,
            "account_type": "savings",
            "branch_city": "Mumbai",
            "occupation": occupation,
            "income_bracket": income_bracket,
            "declared_annual_income": float(income),
        })
    return pd.DataFrame(rows)


def _txns_to_df(rows):
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


# ──────────────────────────────────────────────────────────────────────────────
# Pattern-specific builders
# ──────────────────────────────────────────────────────────────────────────────

def build_layering_data():
    """
    5-hop layering chain: A→B→C→D→E within 60 minutes, 12% decay per hop.
    Repeated 8 times so decay_ratio ≥ 0.5 reliably triggers.
    """
    chain = ["LAY_A", "LAY_B", "LAY_C", "LAY_D", "LAY_E"]
    normal_accounts = [f"NORM_{i:03d}" for i in range(30)]
    base = datetime(2026, 1, 10, 9, 0, 0)
    txns = []
    tid = 0

    for rep in range(8):
        start = base + timedelta(hours=rep * 3)
        amount = 500_000.0
        for j in range(len(chain) - 1):
            ts = start + timedelta(minutes=j * 10)
            hop_amount = round(amount * (0.88 ** j), 2)
            txns.append(_make_txn(f"LAY_{tid}", chain[j], chain[j + 1],
                                  hop_amount, ts, is_laundering=1))
            tid += 1

    # Add background normal transactions
    for i in range(200):
        src = normal_accounts[i % len(normal_accounts)]
        dst = normal_accounts[(i + 1) % len(normal_accounts)]
        txns.append(_make_txn(f"NORM_{tid}", src, dst, 50_000,
                              base + timedelta(hours=i), is_laundering=0))
        tid += 1

    all_accounts = chain + normal_accounts
    accounts_df = _make_accounts(all_accounts)
    txns_df = _txns_to_df(txns)
    return accounts_df, txns_df, chain


def build_round_trip_data():
    """
    A→B (100k) then B→A (92k) = 92% return ratio — well above 0.85 threshold.
    Also a 3-node cycle: C→D→E→C.
    """
    normal_accounts = [f"NORM_{i:03d}" for i in range(40)]
    base = datetime(2026, 2, 1, 8, 0, 0)
    txns = []
    tid = 0

    # 2-node round trip repeated 10 times
    for rep in range(10):
        ts_fwd = base + timedelta(hours=rep * 2)
        ts_ret = ts_fwd + timedelta(minutes=30)
        txns.append(_make_txn(f"RT2_{tid}", "RT_A", "RT_B", 100_000,
                              ts_fwd, is_laundering=1))
        tid += 1
        txns.append(_make_txn(f"RT2_{tid}", "RT_B", "RT_A", 92_000,
                              ts_ret, is_laundering=1))
        tid += 1

    # 3-node cycle repeated 8 times
    for rep in range(8):
        ts = base + timedelta(hours=rep * 3)
        txns.append(_make_txn(f"RT3_{tid}", "CY_C", "CY_D", 80_000,
                              ts + timedelta(minutes=5), is_laundering=1))
        tid += 1
        txns.append(_make_txn(f"RT3_{tid}", "CY_D", "CY_E", 76_000,
                              ts + timedelta(minutes=15), is_laundering=1))
        tid += 1
        txns.append(_make_txn(f"RT3_{tid}", "CY_E", "CY_C", 72_000,
                              ts + timedelta(minutes=25), is_laundering=1))
        tid += 1

    # Background noise
    for i in range(150):
        src = normal_accounts[i % len(normal_accounts)]
        dst = normal_accounts[(i + 3) % len(normal_accounts)]
        txns.append(_make_txn(f"NORM_{tid}", src, dst, 20_000,
                              base + timedelta(hours=i), is_laundering=0))
        tid += 1

    all_accounts = ["RT_A", "RT_B", "CY_C", "CY_D", "CY_E"] + normal_accounts
    accounts_df = _make_accounts(all_accounts)
    txns_df = _txns_to_df(txns)
    return accounts_df, txns_df


def build_structuring_data():
    """
    4 accounts each send 8 transactions in the INR 900k–999k band
    (just below the ₹10L CTR threshold = 1,000,000 in config).
    Also 2 accounts with split structuring: multiple txns summing to the band per day.
    """
    struct_accs = ["STR_A", "STR_B", "STR_C", "STR_D"]
    split_accs = ["SPL_A", "SPL_B"]
    normal_accounts = [f"NORM_{i:03d}" for i in range(50)]
    base = datetime(2026, 3, 1, 9, 0, 0)
    txns = []
    tid = 0

    # Classic structuring: individual txns in 900k–999k range
    for acc in struct_accs:
        for i in range(8):
            ts = base + timedelta(hours=i * 3)
            dst = normal_accounts[i % len(normal_accounts)]
            amount = 900_001 + (i * 10_000)   # 900001, 910001, ... 970001 — all in range
            txns.append(_make_txn(f"STRUCT_{tid}", acc, dst, amount, ts,
                                  is_laundering=1))
            tid += 1

    # Split structuring: multiple txns in one day summing to 900k–999k
    for acc in split_accs:
        day_base = base
        for split_i in range(3):   # 3 daily groups
            # 3 txns each ~300k that sum to ~900k in the day
            for k in range(3):
                ts = day_base + timedelta(hours=k * 2)
                dst = normal_accounts[(split_i * 3 + k) % len(normal_accounts)]
                txns.append(_make_txn(f"SPLIT_{tid}", acc, dst, 305_000,
                                      ts, is_laundering=1))
                tid += 1
            day_base += timedelta(days=1)

    # Background
    for i in range(200):
        src = normal_accounts[i % len(normal_accounts)]
        dst = normal_accounts[(i + 7) % len(normal_accounts)]
        txns.append(_make_txn(f"NORM_{tid}", src, dst, 50_000,
                              base + timedelta(hours=i), is_laundering=0))
        tid += 1

    all_accounts = struct_accs + split_accs + normal_accounts
    accounts_df = _make_accounts(all_accounts)
    txns_df = _txns_to_df(txns)
    return accounts_df, txns_df, struct_accs, split_accs


def build_dormancy_data():
    """
    DORM_A: 1 old txn on 2025-11-01, then 30 high-value txns on 2026-06-01.
    Gap = 212 days (> 180 threshold). Post-avg >> pre-avg (10x multiplier).
    """
    dormant_accs = ["DORM_A", "DORM_B", "DORM_C"]
    normal_accounts = [f"NORM_{i:03d}" for i in range(60)]
    old_base = datetime(2025, 11, 1, 10, 0, 0)
    new_base = datetime(2026, 6, 1, 9, 0, 0)
    txns = []
    tid = 0

    # Use high-index accounts as OLD txn targets so they don't overlap with
    # the burst targets (burst uses accounts[b % 60] for b in 0..24 → indices 0..24)
    old_target_1 = normal_accounts[55]
    old_target_2 = normal_accounts[56]

    for acc in dormant_accs:
        # 2 old transactions to accounts that are NOT in the burst range (indices 0-24)
        txns.append(_make_txn(f"DORM_OLD_{tid}", acc,
                              old_target_1, 5_000, old_base,
                              is_laundering=0))
        tid += 1
        txns.append(_make_txn(f"DORM_OLD_{tid}", acc,
                              old_target_2, 4_500, old_base + timedelta(days=3),
                              is_laundering=0))
        tid += 1
        # 25 burst transactions to accounts[0..24] — none overlap with old_target_1/2
        for b in range(25):
            ts = new_base + timedelta(hours=b)
            dst = normal_accounts[b % 25]  # indices 0-24 only
            txns.append(_make_txn(f"DORM_NEW_{tid}", acc, dst, 80_000,
                                  ts, is_laundering=1))
            tid += 1

    # Background normal
    for i in range(200):
        src = normal_accounts[i % len(normal_accounts)]
        dst = normal_accounts[(i + 5) % len(normal_accounts)]
        txns.append(_make_txn(f"NORM_{tid}", src, dst, 30_000,
                              new_base + timedelta(hours=i), is_laundering=0))
        tid += 1

    all_accounts = dormant_accs + normal_accounts
    accounts_df = _make_accounts(all_accounts)
    txns_df = _txns_to_df(txns)
    return accounts_df, txns_df, dormant_accs


def build_profile_mismatch_data():
    """
    10 'salaried/low' peers each with ~300k volume.
    MISMATCH_A: same occupation/bracket but 15M volume (50× declared income of 300k).
    """
    peer_accounts = [f"PEER_{i:03d}" for i in range(15)]
    base = datetime(2026, 4, 1, 9, 0, 0)
    txns = []
    tid = 0

    # Peers: normal low-volume salaried
    for i, acc in enumerate(peer_accounts):
        for j in range(5):
            ts = base + timedelta(days=j * 10, hours=i)
            dst = peer_accounts[(i + 1) % len(peer_accounts)]
            txns.append(_make_txn(f"PEER_{tid}", acc, dst, 20_000,
                                  ts, is_laundering=0))
            tid += 1

    # Mismatch account: sends 50 × 300k = 15M total (50× its 300k declared income)
    for k in range(50):
        ts = base + timedelta(days=k)
        txns.append(_make_txn(f"MISM_{tid}", "MISMATCH_A",
                              peer_accounts[k % len(peer_accounts)],
                              300_000, ts, is_laundering=1))
        tid += 1

    all_accounts = peer_accounts + ["MISMATCH_A"]
    declared = [300_000] * len(peer_accounts) + [300_000]  # same low declared income
    accounts_df = _make_accounts(all_accounts, declared_income=declared,
                                  occupation="salaried", income_bracket="low")
    txns_df = _txns_to_df(txns)
    return accounts_df, txns_df


def build_incremental_data(n_shared=400, n_new_day2=400, seed=42):
    """
    Day 1: n_shared accounts with clean transactions.
    Day 2: n_shared (returning) + n_new_day2 (brand new) accounts.
         Some returning accounts escalate to suspicious behaviour.
         Some dormant accounts (in Day 1) burst in Day 2.
    """
    rng = np.random.default_rng(seed)
    base_d1 = datetime(2026, 1, 15, 8, 0, 0)
    base_d2 = datetime(2026, 1, 16, 8, 0, 0)

    shared_accs = [f"SHARED_{i:04d}" for i in range(n_shared)]
    new_day2_accs = [f"NEW_{i:04d}" for i in range(n_new_day2)]
    dormant_accs = [f"DORMANT_{i:02d}" for i in range(5)]

    # Accounts that turn dirty on Day 2
    dirty_accs = shared_accs[:10]
    struct_accs_d2 = shared_accs[10:15]   # do structuring on Day 2

    txns_d1, txns_d2 = [], []
    tid = 0

    # Day 1: all shared accounts have normal low-value activity
    for i, acc in enumerate(shared_accs):
        for j in range(5):
            dst = shared_accs[(i + j + 1) % n_shared]
            ts = base_d1 + timedelta(hours=i % 23, minutes=j * 10)
            txns_d1.append(_make_txn(f"D1_{tid}", acc, dst,
                                      rng.uniform(1_000, 50_000), ts, is_laundering=0))
            tid += 1

    # Day 1: dormant accounts have exactly 1 very old txn each
    dormant_base = base_d1 - timedelta(days=200)
    for acc in dormant_accs:
        txns_d1.append(_make_txn(f"DORM_D1_{tid}", acc,
                                  shared_accs[0], 3_000, dormant_base, is_laundering=0))
        tid += 1

    # Day 2: returning accounts (shared_accs)
    for i, acc in enumerate(shared_accs):
        for j in range(3):
            dst = shared_accs[(i + j + 1) % n_shared]
            ts = base_d2 + timedelta(hours=i % 23, minutes=j * 15)
            txns_d2.append(_make_txn(f"D2_NORM_{tid}", acc, dst,
                                      rng.uniform(1_000, 50_000), ts, is_laundering=0))
            tid += 1

    # Day 2: dirty accounts start doing structuring
    for acc in struct_accs_d2:
        for k in range(6):
            ts = base_d2 + timedelta(hours=k * 3)
            dst = shared_accs[(k + 20) % n_shared]
            txns_d2.append(_make_txn(f"D2_STRUCT_{tid}", acc, dst,
                                      950_000 + k * 5_000, ts, is_laundering=1))
            tid += 1

    # Day 2: new accounts doing round-trip fraud
    for k in range(0, 10, 2):
        src = new_day2_accs[k]
        dst = new_day2_accs[k + 1]
        for rep in range(6):
            ts_fwd = base_d2 + timedelta(hours=rep * 2)
            ts_ret = ts_fwd + timedelta(minutes=45)
            txns_d2.append(_make_txn(f"D2_RT_FWD_{tid}", src, dst,
                                      100_000, ts_fwd, is_laundering=1))
            tid += 1
            txns_d2.append(_make_txn(f"D2_RT_RET_{tid}", dst, src,
                                      92_000, ts_ret, is_laundering=1))
            tid += 1

    # Day 2: dormant accounts burst
    for acc in dormant_accs:
        for b in range(25):
            ts = base_d2 + timedelta(hours=b)
            dst = shared_accs[b % n_shared]
            txns_d2.append(_make_txn(f"D2_DORM_{tid}", acc, dst,
                                      80_000, ts, is_laundering=1))
            tid += 1

    # Day 2: remaining new accounts — normal
    for i, acc in enumerate(new_day2_accs[10:]):
        for j in range(3):
            dst = new_day2_accs[(i + j + 11) % n_new_day2]
            ts = base_d2 + timedelta(hours=i % 23, minutes=j * 20)
            txns_d2.append(_make_txn(f"D2_NEW_{tid}", acc, dst,
                                      rng.uniform(1_000, 50_000), ts, is_laundering=0))
            tid += 1

    all_d1_accounts = shared_accs + dormant_accs
    all_d2_accounts = shared_accs + new_day2_accs + dormant_accs

    accs_d1 = _make_accounts(all_d1_accounts)
    accs_d2 = _make_accounts(all_d2_accounts)

    return (
        accs_d1, _txns_to_df(txns_d1),
        accs_d2, _txns_to_df(txns_d2),
        shared_accs, new_day2_accs, dormant_accs,
        struct_accs_d2,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Pytest fixtures
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def layering_dataset():
    return build_layering_data()


@pytest.fixture(scope="session")
def round_trip_dataset():
    return build_round_trip_data()


@pytest.fixture(scope="session")
def structuring_dataset():
    return build_structuring_data()


@pytest.fixture(scope="session")
def dormancy_dataset():
    return build_dormancy_data()


@pytest.fixture(scope="session")
def profile_dataset():
    return build_profile_mismatch_data()


@pytest.fixture(scope="session")
def incremental_dataset():
    return build_incremental_data(n_shared=400, n_new_day2=400, seed=42)
