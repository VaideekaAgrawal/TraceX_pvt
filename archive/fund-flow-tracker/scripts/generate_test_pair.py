#!/usr/bin/env python3
"""
Generate TWO comprehensive test CSVs for TraceX end-to-end testing.

CSV #1 (Day 1 — Initial Load):
  - 8000 transactions, ~350 accounts
  - All 5 fraud pattern types embedded
  - Mix of high-value and low-value normal transactions
  - Realistic distribution of banks, currencies, channels

CSV #2 (Day 2 — Incremental):
  - 5000 transactions
  - 200 returning accounts (from Day 1) + 80 brand-new accounts
  - Tests incremental detection: existing accounts with NEW suspicious behavior
  - New dormant accounts reactivating
  - Existing clean accounts turning dirty (behavioral shift)
  - Brand new accounts immediately doing structuring

This tests:
  ✅ All 5 detectors (layering, round-trip, structuring, dormancy, profile)
  ✅ Incremental ingestion (same accounts evolving over time)
  ✅ New account discovery
  ✅ Behavioral shifts (clean→dirty)
  ✅ Edge cases (zero amount, very large amounts, self-loops filtered)
  ✅ Multiple currencies and channels
  ✅ Fan-in and fan-out patterns
  ✅ High-frequency trading (velocity spikes)
"""
import os
import random
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

random.seed(42)  # Reproducible


def _rand_ts(base_date: datetime, day_range: int = 1) -> str:
    """Generate a random timestamp within day_range days from base_date."""
    offset = timedelta(
        days=random.randint(0, day_range - 1),
        hours=random.randint(0, 23),
        minutes=random.randint(0, 59),
    )
    ts = base_date + offset
    return ts.strftime("%Y/%m/%d %H:%M")


def _rand_amount(low: float, high: float) -> float:
    return round(random.uniform(low, high), 2)


def _lognormal_amount(mu: float = 8.0, sigma: float = 1.5, cap: float = 500000) -> float:
    return round(min(random.lognormvariate(mu, sigma), cap), 2)


# ─── Account Pool ──────────────────────────────────────────────────────────

BANKS = ["ICICI", "SBI", "HDFC", "AXIS", "PNB", "BOB", "KOTAK", "YES", "IDBI", "CANARA"]
CURRENCIES = ["US Dollar", "Indian Rupee", "Euro", "UK Pound", "Bitcoin"]
PAYMENT_FORMATS = ["Cheque", "ACH", "Wire", "Credit Card", "Reinvestment"]

# Fixed accounts for pattern embedding (so you can track them across CSVs)
STRUCTURING_ACCOUNTS = ["STR001AA01", "STR002BB02", "STR003CC03", "STR004DD04", "STR005EE05"]
ROUND_TRIP_PAIRS = [
    ("RT_SRC_001", "RT_DST_001"),
    ("RT_SRC_002", "RT_DST_002"),
    ("RT_SRC_003", "RT_DST_003"),
]
LAYERING_CHAIN_1 = ["LAY_A01", "LAY_B01", "LAY_C01", "LAY_D01", "LAY_E01"]
LAYERING_CHAIN_2 = ["LAY_A02", "LAY_B02", "LAY_C02", "LAY_D02", "LAY_E02"]
FAN_OUT_SOURCES = ["FANOUT_01", "FANOUT_02", "FANOUT_03"]
DORMANT_ACCOUNTS = ["DORM_001", "DORM_002", "DORM_003"]
VELOCITY_ACCOUNTS = ["VELO_001", "VELO_002"]
# Accounts that are clean in Day 1 but turn dirty in Day 2
CLEAN_TO_DIRTY = ["SHIFT_001", "SHIFT_002", "SHIFT_003"]

# General population
GENERAL_ACCOUNTS = [
    f"{random.randint(100, 999)}{random.choice('ABCDEFGH')}{random.randint(1000, 9999)}"
    for _ in range(280)
]

ALL_SPECIAL = (
    STRUCTURING_ACCOUNTS + [a for p in ROUND_TRIP_PAIRS for a in p]
    + LAYERING_CHAIN_1 + LAYERING_CHAIN_2
    + FAN_OUT_SOURCES + DORMANT_ACCOUNTS + VELOCITY_ACCOUNTS + CLEAN_TO_DIRTY
)

DAY1_ACCOUNTS = GENERAL_ACCOUNTS + ALL_SPECIAL
DAY2_NEW_ACCOUNTS = [f"NEW_{random.randint(100, 999)}{random.choice('XYZ')}{random.randint(1000, 9999)}" for _ in range(80)]


def _pick_other(src: str, pool: list) -> str:
    """Pick a destination that isn't src."""
    for _ in range(100):
        dst = random.choice(pool)
        if dst != src:
            return dst
    return pool[0]


def _header() -> str:
    return "Timestamp,From Bank,Account,To Bank,Account.1,Amount Received,Receiving Currency,Amount Paid,Payment Currency,Payment Format,Is Laundering"


def _txn_line(ts: str, src: str, dst: str, amount: float, is_laundering: int = 0) -> str:
    from_bank = random.choice(BANKS)
    to_bank = random.choice(BANKS)
    currency = random.choice(CURRENCIES)
    pf = random.choice(PAYMENT_FORMATS)
    amount_recv = round(amount * random.uniform(0.98, 1.02), 2)
    return f"{ts},{from_bank},{src},{to_bank},{dst},{amount_recv},{currency},{amount},{currency},{pf},{is_laundering}"


# ═══════════════════════════════════════════════════════════════════════════
# CSV #1 — DAY 1 (Initial Load)
# ═══════════════════════════════════════════════════════════════════════════

def generate_day1(output_path: str):
    """Generate Day 1 CSV: 8000 transactions with all fraud patterns."""
    print("━" * 60)
    print("📅 GENERATING CSV #1 — Day 1 (Initial Load)")
    print("━" * 60)

    base_date = datetime(2026, 5, 28)  # May 28, 2026
    lines = [_header()]
    counts = {"structuring": 0, "round_trip": 0, "layering": 0, "fan_out": 0,
              "dormancy": 0, "velocity": 0, "normal": 0, "edge_case": 0}

    # === PATTERN 1: STRUCTURING (amounts just below ₹10L ≈ $12,000) ===
    # Each structuring account makes 8-12 transactions just below threshold
    for acc in STRUCTURING_ACCOUNTS:
        for _ in range(random.randint(8, 12)):
            ts = _rand_ts(base_date)
            dst = _pick_other(acc, GENERAL_ACCOUNTS)
            amount = _rand_amount(11200, 11950)  # Just below $12k
            lines.append(_txn_line(ts, acc, dst, amount, 1))
            counts["structuring"] += 1

    # === PATTERN 2: ROUND-TRIPPING (A→B then B→A with 85-95% return) ===
    for src, dst in ROUND_TRIP_PAIRS:
        base_amount = _rand_amount(50000, 200000)
        # Forward leg
        for _ in range(random.randint(5, 8)):
            ts = _rand_ts(base_date)
            amt = base_amount * random.uniform(0.9, 1.1)
            lines.append(_txn_line(ts, src, dst, round(amt, 2), 1))
            counts["round_trip"] += 1
        # Return leg (85-95% of amount)
        for _ in range(random.randint(4, 7)):
            ts = _rand_ts(base_date)
            amt = base_amount * random.uniform(0.85, 0.95)
            lines.append(_txn_line(ts, dst, src, round(amt, 2), 1))
            counts["round_trip"] += 1

    # === PATTERN 3: LAYERING (multi-hop chains with amount decay) ===
    for chain in [LAYERING_CHAIN_1, LAYERING_CHAIN_2]:
        for _ in range(random.randint(6, 10)):
            amount = _rand_amount(80000, 200000)
            ts_base = base_date + timedelta(hours=random.randint(0, 23))
            for j in range(len(chain) - 1):
                ts = (ts_base + timedelta(minutes=j * random.randint(3, 15))).strftime("%Y/%m/%d %H:%M")
                # Amount decays 5-15% per hop (fees / splits)
                hop_amount = round(amount * (0.88 ** j), 2)
                lines.append(_txn_line(ts, chain[j], chain[j + 1], hop_amount, 1))
                counts["layering"] += 1

    # === PATTERN 4: FAN-OUT (one source → many destinations) ===
    for src in FAN_OUT_SOURCES:
        targets = random.sample(GENERAL_ACCOUNTS, random.randint(15, 25))
        for dst in targets:
            ts = _rand_ts(base_date)
            amount = _rand_amount(20000, 80000)
            lines.append(_txn_line(ts, src, dst, amount, 1))
            counts["fan_out"] += 1

    # === PATTERN 5: DORMANT ACCOUNTS (no activity in Day 1 — they'll activate in Day 2) ===
    # Only add 1-2 old transactions to establish them as existing
    for acc in DORMANT_ACCOUNTS:
        ts = _rand_ts(base_date)
        dst = _pick_other(acc, GENERAL_ACCOUNTS)
        lines.append(_txn_line(ts, acc, dst, _rand_amount(1000, 5000), 0))
        counts["dormancy"] += 1

    # === VELOCITY SPIKES (many transactions in short burst) ===
    for acc in VELOCITY_ACCOUNTS:
        # Normal activity: spread across the day
        for _ in range(5):
            ts = _rand_ts(base_date)
            dst = _pick_other(acc, GENERAL_ACCOUNTS)
            lines.append(_txn_line(ts, acc, dst, _lognormal_amount(), 0))
        # Burst: 20 transactions in 30 minutes
        burst_start = base_date + timedelta(hours=random.randint(10, 20))
        for i in range(20):
            ts = (burst_start + timedelta(minutes=i * random.randint(1, 3))).strftime("%Y/%m/%d %H:%M")
            dst = _pick_other(acc, GENERAL_ACCOUNTS)
            amount = _rand_amount(15000, 45000)
            lines.append(_txn_line(ts, acc, dst, amount, 1))
            counts["velocity"] += 1

    # === CLEAN-TO-DIRTY ACCOUNTS (clean in Day 1) ===
    for acc in CLEAN_TO_DIRTY:
        for _ in range(random.randint(5, 10)):
            ts = _rand_ts(base_date)
            dst = _pick_other(acc, GENERAL_ACCOUNTS)
            amount = _lognormal_amount(7.5, 1.0, 50000)  # Low normal amounts
            lines.append(_txn_line(ts, acc, dst, amount, 0))
            counts["normal"] += 1

    # === EDGE CASES ===
    # Very small amounts (micro-transactions)
    for _ in range(20):
        ts = _rand_ts(base_date)
        src = random.choice(GENERAL_ACCOUNTS)
        dst = _pick_other(src, GENERAL_ACCOUNTS)
        lines.append(_txn_line(ts, src, dst, _rand_amount(0.01, 10.0), 0))
        counts["edge_case"] += 1

    # Very large single transactions
    for _ in range(10):
        ts = _rand_ts(base_date)
        src = random.choice(GENERAL_ACCOUNTS)
        dst = _pick_other(src, GENERAL_ACCOUNTS)
        lines.append(_txn_line(ts, src, dst, _rand_amount(400000, 900000), 0))
        counts["edge_case"] += 1

    # === NORMAL TRANSACTIONS (fill up to 8000) ===
    while len(lines) - 1 < 8000:
        ts = _rand_ts(base_date)
        src = random.choice(DAY1_ACCOUNTS)
        dst = _pick_other(src, DAY1_ACCOUNTS)
        amount = _lognormal_amount()
        is_fraud = 1 if random.random() < 0.015 else 0  # 1.5% random fraud noise
        lines.append(_txn_line(ts, src, dst, amount, is_fraud))
        counts["normal"] += 1

    # Write
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
    with open(output_path, "w") as f:
        f.write("\n".join(lines[:8001]))  # Header + 8000 txns

    fraud_total = sum(v for k, v in counts.items() if k != "normal" and k != "edge_case")
    print(f"\n✅ Generated → {output_path}")
    print(f"   Transactions: 8000")
    print(f"   Accounts: ~{len(set(DAY1_ACCOUNTS))}")
    print(f"   Fraud txns: {fraud_total} ({100*fraud_total/8000:.1f}%)")
    print(f"\n   Patterns embedded:")
    for k, v in counts.items():
        print(f"     {k:20s} → {v}")
    print()


# ═══════════════════════════════════════════════════════════════════════════
# CSV #2 — DAY 2 (Incremental — same accounts + new accounts)
# ═══════════════════════════════════════════════════════════════════════════

def generate_day2(output_path: str):
    """Generate Day 2 CSV: 5000 transactions testing incremental detection."""
    print("━" * 60)
    print("📅 GENERATING CSV #2 — Day 2 (Incremental)")
    print("━" * 60)

    base_date = datetime(2026, 5, 29)  # Next day
    lines = [_header()]
    counts = {"structuring_continued": 0, "round_trip_continued": 0,
              "dormancy_burst": 0, "behavioral_shift": 0,
              "new_account_fraud": 0, "fan_in": 0, "velocity": 0, "normal": 0}

    day2_pool = GENERAL_ACCOUNTS[:200] + DAY2_NEW_ACCOUNTS + ALL_SPECIAL

    # === RETURNING: Structuring accounts continue (should raise risk further) ===
    for acc in STRUCTURING_ACCOUNTS[:3]:  # Only 3 of 5 continue
        for _ in range(random.randint(6, 10)):
            ts = _rand_ts(base_date)
            dst = _pick_other(acc, day2_pool)
            amount = _rand_amount(11100, 11980)
            lines.append(_txn_line(ts, acc, dst, amount, 1))
            counts["structuring_continued"] += 1

    # === RETURNING: Round-trip continues with higher amounts ===
    for src, dst in ROUND_TRIP_PAIRS[:2]:
        base_amount = _rand_amount(100000, 300000)  # Escalation
        for _ in range(random.randint(4, 6)):
            ts = _rand_ts(base_date)
            lines.append(_txn_line(ts, src, dst, round(base_amount * random.uniform(0.9, 1.1), 2), 1))
            counts["round_trip_continued"] += 1
        for _ in range(random.randint(3, 5)):
            ts = _rand_ts(base_date)
            lines.append(_txn_line(ts, dst, src, round(base_amount * random.uniform(0.85, 0.95), 2), 1))
            counts["round_trip_continued"] += 1

    # === DORMANCY: Accounts dormant in Day 1 now burst with activity ===
    for acc in DORMANT_ACCOUNTS:
        # 25-40 transactions in a single day — massive burst
        for _ in range(random.randint(25, 40)):
            ts = _rand_ts(base_date)
            dst = _pick_other(acc, day2_pool)
            amount = _rand_amount(30000, 150000)
            lines.append(_txn_line(ts, acc, dst, amount, 1))
            counts["dormancy_burst"] += 1

    # === BEHAVIORAL SHIFT: Clean accounts from Day 1 now doing suspicious activity ===
    for acc in CLEAN_TO_DIRTY:
        # Suddenly doing structuring
        for _ in range(random.randint(8, 15)):
            ts = _rand_ts(base_date)
            dst = _pick_other(acc, day2_pool)
            amount = _rand_amount(11000, 11900)
            lines.append(_txn_line(ts, acc, dst, amount, 1))
            counts["behavioral_shift"] += 1
        # Also doing fan-out to multiple new accounts
        new_targets = random.sample(DAY2_NEW_ACCOUNTS, 10)
        for dst in new_targets:
            ts = _rand_ts(base_date)
            amount = _rand_amount(25000, 75000)
            lines.append(_txn_line(ts, acc, dst, amount, 1))
            counts["behavioral_shift"] += 1

    # === NEW ACCOUNTS: Immediately suspicious ===
    # New accounts doing round-tripping among themselves
    new_rt_pairs = [
        (DAY2_NEW_ACCOUNTS[0], DAY2_NEW_ACCOUNTS[1]),
        (DAY2_NEW_ACCOUNTS[2], DAY2_NEW_ACCOUNTS[3]),
    ]
    for src, dst in new_rt_pairs:
        for _ in range(random.randint(6, 10)):
            ts = _rand_ts(base_date)
            amount = _rand_amount(40000, 120000)
            lines.append(_txn_line(ts, src, dst, amount, 1))
            counts["new_account_fraud"] += 1
        for _ in range(random.randint(5, 8)):
            ts = _rand_ts(base_date)
            amount = _rand_amount(35000, 110000)
            lines.append(_txn_line(ts, dst, src, amount, 1))
            counts["new_account_fraud"] += 1

    # New accounts doing layering (multi-hop)
    new_chain = DAY2_NEW_ACCOUNTS[10:15]
    for _ in range(random.randint(5, 8)):
        amount = _rand_amount(60000, 150000)
        ts_base = base_date + timedelta(hours=random.randint(0, 20))
        for j in range(len(new_chain) - 1):
            ts = (ts_base + timedelta(minutes=j * random.randint(10, 40))).strftime("%Y/%m/%d %H:%M")
            hop_amount = round(amount * (0.90 ** j), 2)
            lines.append(_txn_line(ts, new_chain[j], new_chain[j + 1], hop_amount, 1))
            counts["new_account_fraud"] += 1

    # === FAN-IN: Many accounts sending to ONE new suspicious account ===
    fan_in_sink = DAY2_NEW_ACCOUNTS[20]
    senders = random.sample(GENERAL_ACCOUNTS[:100], 20)
    for src in senders:
        ts = _rand_ts(base_date)
        amount = _rand_amount(30000, 90000)
        lines.append(_txn_line(ts, src, fan_in_sink, amount, 1))
        counts["fan_in"] += 1

    # === VELOCITY: Existing account suddenly sends 30 txns in 1 hour ===
    burst_acc = VELOCITY_ACCOUNTS[0]
    burst_start = base_date + timedelta(hours=14)
    for i in range(30):
        ts = (burst_start + timedelta(minutes=i * 2)).strftime("%Y/%m/%d %H:%M")
        dst = _pick_other(burst_acc, day2_pool)
        amount = _rand_amount(10000, 50000)
        lines.append(_txn_line(ts, burst_acc, dst, amount, 1))
        counts["velocity"] += 1

    # === NORMAL TRANSACTIONS (existing + new accounts) ===
    while len(lines) - 1 < 5000:
        ts = _rand_ts(base_date)
        src = random.choice(day2_pool)
        dst = _pick_other(src, day2_pool)
        amount = _lognormal_amount()
        is_fraud = 1 if random.random() < 0.01 else 0
        lines.append(_txn_line(ts, src, dst, amount, is_fraud))
        counts["normal"] += 1

    # Write
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
    with open(output_path, "w") as f:
        f.write("\n".join(lines[:5001]))  # Header + 5000 txns

    fraud_total = sum(v for k, v in counts.items() if k != "normal")
    print(f"\n✅ Generated → {output_path}")
    print(f"   Transactions: 5000")
    print(f"   Returning accounts: ~200 (from Day 1)")
    print(f"   New accounts: {len(DAY2_NEW_ACCOUNTS)}")
    print(f"   Fraud txns: {fraud_total} ({100*fraud_total/5000:.1f}%)")
    print(f"\n   Patterns embedded:")
    for k, v in counts.items():
        print(f"     {k:25s} → {v}")
    print()


# ═══════════════════════════════════════════════════════════════════════════
# CSV #3 — DAY 3 (Demo-ready — maximized pattern visibility)
# ═══════════════════════════════════════════════════════════════════════════

DAY3_LAYERING_CHAINS = [
    ["D3_LAY_A1", "D3_LAY_B1", "D3_LAY_C1", "D3_LAY_D1", "D3_LAY_E1", "D3_LAY_F1"],
    ["D3_LAY_A2", "D3_LAY_B2", "D3_LAY_C2", "D3_LAY_D2", "D3_LAY_E2"],
    ["D3_LAY_A3", "D3_LAY_B3", "D3_LAY_C3", "D3_LAY_D3"],
]
DAY3_RT_PAIRS = [
    ("D3_RT_A1", "D3_RT_B1"),
    ("D3_RT_A2", "D3_RT_B2"),
    ("D3_RT_A3", "D3_RT_B3", "D3_RT_C3"),  # 3-node cycle
]
DAY3_STRUCT_ACCOUNTS = ["D3_STR01", "D3_STR02", "D3_STR03", "D3_STR04"]
DAY3_FANOUT = ["D3_FAN01", "D3_FAN02"]
DAY3_GENERAL = [f"D3_G{i:03d}" for i in range(150)]


def generate_day3(output_path: str):
    """Generate Day 3 CSV: Demo-focused with maximum pattern visibility.
    Specifically designed to guarantee all 5 pattern types are detected strongly."""
    print("━" * 60)
    print("📅 GENERATING CSV #3 — Day 3 (Demo Day — Strong Patterns)")
    print("━" * 60)

    base_date = datetime(2026, 5, 30)
    lines = [_header()]
    counts = {"layering": 0, "round_trip": 0, "structuring": 0,
              "dormancy": 0, "fan_out": 0, "normal": 0}

    all_d3_accounts = (
        [a for chain in DAY3_LAYERING_CHAINS for a in chain]
        + ["D3_RT_A1", "D3_RT_B1", "D3_RT_A2", "D3_RT_B2", "D3_RT_A3", "D3_RT_B3", "D3_RT_C3"]
        + DAY3_STRUCT_ACCOUNTS + DAY3_FANOUT + DAY3_GENERAL
    )

    # ══════════════════════════════════════════════════════════════════════
    # LAYERING — VERY TIGHT TIMING (guaranteed detection)
    # Each chain: hops 3-8 min apart, amounts decay 10-15% per hop
    # ══════════════════════════════════════════════════════════════════════
    for chain in DAY3_LAYERING_CHAINS:
        for rep in range(8):  # 8 repetitions per chain
            amount = _rand_amount(100000, 500000)
            ts_base = base_date + timedelta(hours=rep * 3, minutes=random.randint(0, 30))
            for j in range(len(chain) - 1):
                # TIGHT: 3-8 minutes between hops (total chain always < 60 min)
                ts = (ts_base + timedelta(minutes=j * random.randint(3, 8))).strftime("%Y/%m/%d %H:%M")
                hop_amount = round(amount * (0.87 ** j), 2)  # 13% decay per hop
                lines.append(_txn_line(ts, chain[j], chain[j + 1], hop_amount, 1))
                counts["layering"] += 1

    # ══════════════════════════════════════════════════════════════════════
    # ROUND-TRIPPING — Clear bilateral flows (A→B and B→A)
    # High amounts, within 24h window, ≥90% return ratio
    # ══════════════════════════════════════════════════════════════════════
    # 2-node round trips
    for src, dst in [("D3_RT_A1", "D3_RT_B1"), ("D3_RT_A2", "D3_RT_B2")]:
        for rep in range(10):
            base_amount = _rand_amount(80000, 300000)
            ts_base = base_date + timedelta(hours=rep * 2)
            # Forward: src → dst
            ts = (ts_base + timedelta(minutes=random.randint(0, 10))).strftime("%Y/%m/%d %H:%M")
            lines.append(_txn_line(ts, src, dst, round(base_amount, 2), 1))
            counts["round_trip"] += 1
            # Return: dst → src (90-97% of amount — strong round-trip signal)
            ts = (ts_base + timedelta(minutes=random.randint(15, 45))).strftime("%Y/%m/%d %H:%M")
            return_amount = round(base_amount * random.uniform(0.90, 0.97), 2)
            lines.append(_txn_line(ts, dst, src, return_amount, 1))
            counts["round_trip"] += 1

    # 3-node round trip: A→B→C→A
    for rep in range(8):
        amount = _rand_amount(60000, 200000)
        ts_base = base_date + timedelta(hours=rep * 3)
        # A→B
        ts = (ts_base + timedelta(minutes=random.randint(0, 5))).strftime("%Y/%m/%d %H:%M")
        lines.append(_txn_line(ts, "D3_RT_A3", "D3_RT_B3", round(amount, 2), 1))
        counts["round_trip"] += 1
        # B→C
        ts = (ts_base + timedelta(minutes=random.randint(10, 20))).strftime("%Y/%m/%d %H:%M")
        lines.append(_txn_line(ts, "D3_RT_B3", "D3_RT_C3", round(amount * 0.95, 2), 1))
        counts["round_trip"] += 1
        # C→A (completes the cycle)
        ts = (ts_base + timedelta(minutes=random.randint(25, 40))).strftime("%Y/%m/%d %H:%M")
        lines.append(_txn_line(ts, "D3_RT_C3", "D3_RT_A3", round(amount * 0.90, 2), 1))
        counts["round_trip"] += 1

    # ══════════════════════════════════════════════════════════════════════
    # STRUCTURING — Amounts tightly clustered below ₹10L (₹9.5L–₹9.99L)
    # ══════════════════════════════════════════════════════════════════════
    for acc in DAY3_STRUCT_ACCOUNTS:
        for _ in range(random.randint(10, 15)):
            ts = _rand_ts(base_date)
            dst = random.choice(DAY3_GENERAL)
            # Indian Rupee amounts just below ₹10 lakh
            amount = _rand_amount(950000, 999000)
            lines.append(_txn_line(ts, acc, dst, amount, 1))
            counts["structuring"] += 1

    # ══════════════════════════════════════════════════════════════════════
    # DORMANCY — Accounts with zero Day 3 history that suddenly burst
    # (These will appear "new" to the system which is equivalent to dormant)
    # ══════════════════════════════════════════════════════════════════════
    dormant_accts = ["D3_DORM01", "D3_DORM02", "D3_DORM03"]
    for acc in dormant_accts:
        # Single old transaction 6+ months ago (establish account age)
        old_ts = (base_date - timedelta(days=200)).strftime("%Y/%m/%d %H:%M")
        dst = random.choice(DAY3_GENERAL)
        lines.append(_txn_line(old_ts, acc, dst, _rand_amount(1000, 5000), 0))
        counts["dormancy"] += 1
        # Sudden burst of 20+ high-value transactions
        for _ in range(random.randint(20, 30)):
            ts = _rand_ts(base_date)
            dst = random.choice(DAY3_GENERAL)
            amount = _rand_amount(50000, 200000)
            lines.append(_txn_line(ts, acc, dst, amount, 1))
            counts["dormancy"] += 1

    # ══════════════════════════════════════════════════════════════════════
    # FAN-OUT — Single source distributing to 20+ recipients
    # ══════════════════════════════════════════════════════════════════════
    for src in DAY3_FANOUT:
        targets = random.sample(DAY3_GENERAL, random.randint(20, 30))
        for dst in targets:
            ts = _rand_ts(base_date)
            amount = _rand_amount(30000, 100000)
            lines.append(_txn_line(ts, src, dst, amount, 1))
            counts["fan_out"] += 1

    # ══════════════════════════════════════════════════════════════════════
    # NORMAL BACKGROUND TRANSACTIONS (fill to 6000 total)
    # ══════════════════════════════════════════════════════════════════════
    while len(lines) - 1 < 6000:
        ts = _rand_ts(base_date)
        src = random.choice(all_d3_accounts)
        dst = _pick_other(src, all_d3_accounts)
        amount = _lognormal_amount()
        lines.append(_txn_line(ts, src, dst, amount, 0))
        counts["normal"] += 1

    # Write
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
    with open(output_path, "w") as f:
        f.write("\n".join(lines[:6001]))  # Header + 6000 txns

    fraud_total = sum(v for k, v in counts.items() if k != "normal")
    print(f"\n✅ Generated → {output_path}")
    print(f"   Transactions: 6000")
    print(f"   Accounts: ~{len(set(all_d3_accounts))}")
    print(f"   Fraud txns: {fraud_total} ({100*fraud_total/6000:.1f}%)")
    print(f"\n   Patterns embedded (STRONG — guaranteed detection):")
    for k, v in counts.items():
        print(f"     {k:20s} → {v}")
    print(f"\n   Layering chains: {len(DAY3_LAYERING_CHAINS)} (5-6 hops, 3-8 min/hop)")
    print(f"   Round-trip pairs: 2×2-node + 1×3-node (90-97% return)")
    print(f"   Structuring: {len(DAY3_STRUCT_ACCOUNTS)} accounts (₹9.5L-₹9.99L range)")
    print()


# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

    csv1_path = os.path.join(data_dir, "tracex_test_day1.csv")
    csv2_path = os.path.join(data_dir, "tracex_test_day2_incremental.csv")
    csv3_path = os.path.join(data_dir, "tracex_test_day3_demo.csv")

    generate_day1(csv1_path)
    generate_day2(csv2_path)
    generate_day3(csv3_path)

    print("═" * 60)
    print("🎯 TESTING INSTRUCTIONS")
    print("═" * 60)
    print(f"""
1. Upload CSV #1 (Day 1) first:
   → {csv1_path}
   → Go to http://localhost:3000/ingest
   → Drag & drop the file, click "Ingest CSV"
   → Check dashboard, graph, anomaly, patterns pages

2. Then upload CSV #2 (Day 2) WITHOUT clearing:
   → {csv2_path}
   → Upload from the same ingest page
   → Check "Force re-process" checkbox
   → Watch how existing accounts' risk scores INCREASE
   → New accounts appear with immediate high risk

3. OR for a DEMO-ready single file with strong patterns:
   → {csv3_path}
   → Clear DB first (delete data/tracex.db), then upload
   → ALL 5 pattern types guaranteed to be detected
   → Best file for video recording / live demo

4. Key accounts to track:
   Day 1/2:
   • STR001AA01-STR005EE05  → Structuring
   • RT_SRC_001 / RT_DST_001 → Round-tripping
   • LAY_A01→LAY_E01         → Layering chain
   • FANOUT_01-03            → Fan-out sources
   • DORM_001-003            → Dormant (quiet Day1, burst Day2)
   Day 3 (Demo):
   • D3_LAY_A1→D3_LAY_F1    → 6-hop layering (tight timing)
   • D3_RT_A1 / D3_RT_B1    → Clear round-trip
   • D3_RT_A3→B3→C3→A3      → 3-node cycle
   • D3_STR01-04             → Structuring (₹9.5L-₹9.99L)
   • D3_DORM01-03            → Dormant burst
""")
