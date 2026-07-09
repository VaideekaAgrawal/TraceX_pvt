from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


def make_synthetic_dataset(
    n_accounts: int = 60, n_fraud_accounts: int = 15, seed: int = 7
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """A small but learnable synthetic labeled transaction set: the first
    `n_fraud_accounts` accounts send high-value (900K+) transactions all
    marked `is_laundering=1`; the rest send low-value (1K-50K) clean
    transactions. Separable enough for XGBoost to actually learn something
    on a handful of rows, instead of just "doesn't crash"."""
    rng = np.random.default_rng(seed)
    accounts = [f"ACC{i}" for i in range(n_accounts)]
    rows = []
    base = pd.Timestamp("2026-01-01")
    for i, acc in enumerate(accounts):
        is_fraud_acc = i < n_fraud_accounts
        for j in range(8):
            dest = accounts[(i + j + 1) % n_accounts]
            if is_fraud_acc:
                amount = float(rng.integers(500_000, 999_000))
            else:
                amount = float(rng.integers(1_000, 50_000))
            ts = base + pd.Timedelta(
                days=int(rng.integers(0, 60)), hours=int(rng.integers(0, 23))
            )
            rows.append({
                "source_account": acc,
                "dest_account": dest,
                "amount": amount,
                "timestamp": ts,
                "channel": "UPI",
                "is_laundering": 1 if is_fraud_acc else 0,
                "from_bank": "1",
                "to_bank": "2",
            })
    transactions_df = pd.DataFrame(rows)
    accounts_df = pd.DataFrame({"account_id": accounts})
    return accounts_df, transactions_df


@pytest.fixture()
def synthetic_dataset() -> tuple[pd.DataFrame, pd.DataFrame]:
    return make_synthetic_dataset()
