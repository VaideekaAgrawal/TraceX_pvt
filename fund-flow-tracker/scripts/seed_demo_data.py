"""
Seed a small, curated demo dataset into the database.

Why this exists: judges pointed out that TraceX's dashboards look empty
until someone manually uploads a CSV, and that a server restart wipes
whatever was there. This script gives a fresh install a realistic,
non-empty system out of the box — a *small* dataset (not the 8000-row
generator in generate_test_pair.py) that still exercises every one of the
6 detector code paths, plus a "control" (should NOT flag) case for the
structuring detector's hard amount-band threshold.

It writes through IngestionService.persist_to_db() — the same DB-write
path every other ingestion route now uses — so it's a real exercise of the
persistence fix, not a side-channel SQL insert.

Usage:
    python -m scripts.seed_demo_data           # seeds only if DB is empty
    python -m scripts.seed_demo_data --force    # re-seeds unconditionally
"""
import logging
import random
import sys
from datetime import datetime, timedelta
from typing import List, Dict

import pandas as pd

logger = logging.getLogger(__name__)

_CHANNELS = ["UPI", "NEFT", "IMPS", "net_banking", "ATM", "branch_cash"]


def _account(account_id: str, *, occupation="Salaried", income_bracket="medium",
             declared_annual_income=1_200_000.0, account_type="savings",
             branch_city="Mumbai") -> Dict:
    return {
        "account_id": account_id,
        "account_type": account_type,
        "branch_city": branch_city,
        "occupation": occupation,
        "income_bracket": income_bracket,
        "declared_annual_income": declared_annual_income,
        "risk_score": 0.0,
        "risk_level": "LOW",
        "role": "NORMAL",
    }


class _TxnBuilder:
    """Accumulates transaction rows and the accounts they reference."""

    def __init__(self):
        self.rows: List[Dict] = []
        self._seen_accounts: set = set()
        self._counter = 0

    def add(self, src: str, dst: str, amount: float, ts: datetime,
            channel: str = "UPI", is_laundering: int = 0):
        self._counter += 1
        self._seen_accounts.add(src)
        self._seen_accounts.add(dst)
        self.rows.append({
            "txn_id": f"SEED-{self._counter:05d}",
            "timestamp": ts,
            "source_account": src,
            "dest_account": dst,
            "amount": float(amount),
            "channel": channel,
            "txn_type": "transfer",
            "is_laundering": int(is_laundering),
            "ingestion_date": ts.strftime("%Y-%m-%d"),
        })

    @property
    def accounts(self) -> set:
        return self._seen_accounts


def build_seed_dataframes(anchor: datetime = None):
    """Build (accounts_df, transactions_df) covering all 6 detector patterns
    plus a control and a boundary case for each threshold-driven one."""
    now = anchor or datetime.now()
    b = _TxnBuilder()
    rng = random.Random(20260701)  # deterministic — same seed data every run

    # ── Background "normal" traffic — makes the graph look like a real
    #    system, not a set of isolated pattern islands. 18 accounts doing
    #    everyday small transfers over the last ~45 days. Deliberately kept
    #    as 9 disjoint one-directional pairs (never A->B *and* B->A, never
    #    >1 counterparty per account) so this traffic can never accidentally
    #    form a cycle, a 3+ hop chain, or a fan-out/fan-in degree — it stays
    #    a genuinely clean baseline rather than incidental noise.
    normals = [f"NORM_{i:03d}" for i in range(1, 19)]
    for pair_idx in range(0, len(normals), 2):
        src, dst = normals[pair_idx], normals[pair_idx + 1]
        for _ in range(rng.randint(6, 10)):
            ts = now - timedelta(days=rng.randint(1, 45), hours=rng.randint(0, 23))
            b.add(src, dst, rng.randint(500, 45_000), ts, channel=rng.choice(_CHANNELS))

    # ── 1. Round-trip — a clear circular flow well above the 0.85
    #    return-ratio threshold. (A precise "just under the threshold"
    #    boundary case turned out not to be reliably constructible here —
    #    RoundTripDetector computes the return ratio relative to whichever
    #    cycle member the underlying cycle-search happens to treat as the
    #    start node, which isn't a property callers can pin down from the
    #    input data alone. The Rule Engine's dry-run preview, Phase 5, is
    #    the reliable way to show a threshold edit's impact instead.)
    b.add("RT_TIGHT_A", "RT_TIGHT_B", 500_000, now - timedelta(days=2, hours=4))
    b.add("RT_TIGHT_B", "RT_TIGHT_A", 480_000, now - timedelta(days=2, hours=1))  # ratio 0.96

    # ── 2. Structuring — HIT (4 txns in the ₹9L-₹9.99L band, min_count=3)
    for i, amt in enumerate([950_000, 962_000, 971_000, 985_000]):
        b.add("STRUCT_HIT", "STRUCT_DEST", amt, now - timedelta(days=10 - i * 2), channel="NEFT", is_laundering=1)

    # Structuring — CONTROL (below the ₹9L lower bound; must NOT flag)
    for i, amt in enumerate([800_000, 810_000, 795_000, 805_000]):
        b.add("STRUCT_CTRL", "STRUCT_DEST", amt, now - timedelta(days=10 - i * 2), channel="NEFT")

    # ── 3. Layering — 3-hop decreasing-amount chain within 90 minutes
    #    (min_hops=3, decay_ratio must be >= 0.5 within the 120-min window)
    b.add("LAYER_1", "LAYER_2", 500_000, now - timedelta(days=1, minutes=90), is_laundering=1)
    b.add("LAYER_2", "LAYER_3", 450_000, now - timedelta(days=1, minutes=60), is_laundering=1)
    b.add("LAYER_3", "LAYER_4", 400_000, now - timedelta(days=1, minutes=30), is_laundering=1)

    # ── 4. Dormancy — pre-dormancy baseline, a >180-day gap, then a burst
    #    averaging >10x the pre-dormancy average (dormancy_multiplier=10.0)
    dorm_pre_start = now - timedelta(days=400)
    for i in range(3):
        b.add("DORM_1", f"DORM_CP_{i + 1}", 20_000, dorm_pre_start + timedelta(days=i * 30))
    burst_start = now - timedelta(days=6)
    for i in range(6):
        b.add("DORM_1", f"DORM_CP_{i + 4}", 300_000, burst_start + timedelta(hours=i * 5), is_laundering=1)

    # ── 5. Fan-out — 1 source to 4 unique destinations within a week
    #    (fan_out_min_degree=3)
    for i, dst in enumerate(["FANOUT_D1", "FANOUT_D2", "FANOUT_D3", "FANOUT_D4"]):
        b.add("FANOUT_SRC", dst, 120_000 + i * 5_000, now - timedelta(days=4 - i), is_laundering=1)

    # ── 6. Profile mismatch — declared income ₹2L but ₹3M+ actual volume
    #    (ratio > 10x triggers _detect_income_mismatch)
    for i in range(5):
        b.add("PROFILE_1", f"PROFILE_CP_{i + 1}", 600_000, now - timedelta(days=20 - i * 3), is_laundering=1)

    txns_df = pd.DataFrame(b.rows)

    account_overrides = {
        "PROFILE_1": _account("PROFILE_1", occupation="Retired", income_bracket="low",
                               declared_annual_income=200_000.0),
    }
    accounts = []
    for acc_id in sorted(b.accounts):
        if acc_id in account_overrides:
            accounts.append(account_overrides[acc_id])
        elif acc_id.startswith("NORM_"):
            # A single homogeneous peer group for the clean background
            # accounts, so none of them show up as peer-deviation outliers.
            accounts.append(_account(acc_id, occupation="Salaried", income_bracket="medium",
                                      declared_annual_income=1_200_000.0))
        else:
            # Pattern accounts get their own peer group (and generous
            # declared income) so they don't get lumped in with — and don't
            # skew — the clean NORM_* peer group.
            accounts.append(_account(acc_id, occupation="Business", income_bracket="high",
                                      declared_annual_income=5_000_000.0))
    accounts_df = pd.DataFrame(accounts)

    return accounts_df, txns_df


def seed_if_empty(db=None) -> bool:
    """Seed the demo dataset only if the accounts table is currently empty.
    Returns True if seeding happened."""
    from infrastructure.database import get_database
    from services.ingestion.service import IngestionService

    db = db or get_database()
    if db.get_account_count() > 0:
        logger.info("Seed skipped: database already has data.")
        return False

    accounts_df, txns_df = build_seed_dataframes()
    IngestionService().persist_to_db(accounts_df, txns_df)
    logger.info("Seeded demo data: %d accounts, %d transactions", len(accounts_df), len(txns_df))
    return True


def seed_force() -> None:
    """Seed unconditionally (used by the --force CLI flag)."""
    from infrastructure.database import get_database
    from services.ingestion.service import IngestionService

    db = get_database()
    accounts_df, txns_df = build_seed_dataframes()
    IngestionService().persist_to_db(accounts_df, txns_df)
    logger.info("Force-seeded demo data: %d accounts, %d transactions", len(accounts_df), len(txns_df))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    if "--force" in sys.argv:
        seed_force()
    else:
        seeded = seed_if_empty()
        if not seeded:
            print("Database already has data — use --force to re-seed anyway.")
