from __future__ import annotations

import pandas as pd
import pytest

from detection.graph.networkx_store import NetworkXGraphStore


def ts(s: str) -> pd.Timestamp:
    return pd.Timestamp(s)


@pytest.fixture()
def make_store():
    def _make(transactions_df: pd.DataFrame, accounts_df: pd.DataFrame | None = None):
        if accounts_df is None:
            accts = pd.unique(
                pd.concat([transactions_df["source_account"], transactions_df["dest_account"]])
            )
            accounts_df = pd.DataFrame({"account_id": accts})
        return NetworkXGraphStore(accounts_df, transactions_df)

    return _make
