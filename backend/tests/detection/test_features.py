from __future__ import annotations

import pandas as pd
import pytest

from detection.features import FeatureExtractor, channel_entropy, gini_coefficient, safe_ratio
from detection.graph.networkx_store import NetworkXGraphStore


def _ts(s: str) -> pd.Timestamp:
    return pd.Timestamp(s)


@pytest.fixture()
def accounts_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "account_id": ["A", "B", "C"],
            "declared_annual_income": [1_200_000.0, 600_000.0, 0.0],
        }
    )


@pytest.fixture()
def transactions_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "source_account": "A",
                "dest_account": "B",
                "amount": 100_000.0,
                "timestamp": _ts("2026-01-01 10:00"),
                "channel": "NEFT",
                "from_bank": "1",
                "to_bank": "2",
            },
            {
                "source_account": "B",
                "dest_account": "C",
                "amount": 50_000.0,
                "timestamp": _ts("2026-01-02 11:00"),
                "channel": "UPI",
                "from_bank": "2",
                "to_bank": "3",
            },
            {
                "source_account": "B",
                "dest_account": "A",
                "amount": 20_000.0,
                "timestamp": _ts("2026-01-03 12:00"),
                "channel": "UPI",
                "from_bank": "2",
                "to_bank": "1",
            },
        ]
    )


@pytest.fixture()
def extractor(accounts_df, transactions_df) -> FeatureExtractor:
    store = NetworkXGraphStore(accounts_df, transactions_df)
    return FeatureExtractor(store, accounts_df, transactions_df)


def test_extract_all_has_the_28_dim_feature_columns(extractor: FeatureExtractor) -> None:
    df = extractor.extract_all()
    assert list(df.columns) == FeatureExtractor._FEATURE_COLS
    assert len(FeatureExtractor._FEATURE_COLS) == 28


def test_extract_all_indexed_by_every_graph_account(extractor: FeatureExtractor) -> None:
    df = extractor.extract_all()
    assert set(df.index) == {"A", "B", "C"}


def test_extract_all_degrees_match_transactions(extractor: FeatureExtractor) -> None:
    df = extractor.extract_all()
    # A: 1 outgoing (A->B), 1 incoming (B->A)
    assert df.loc["A", "out_degree"] == 1
    assert df.loc["A", "in_degree"] == 1
    # B: 2 outgoing (B->C, B->A), 1 incoming (A->B)
    assert df.loc["B", "out_degree"] == 2
    assert df.loc["B", "in_degree"] == 1
    # C: 0 outgoing, 1 incoming (B->C)
    assert df.loc["C", "out_degree"] == 0
    assert df.loc["C", "in_degree"] == 1


def test_extract_all_flows_and_amounts(extractor: FeatureExtractor) -> None:
    df = extractor.extract_all()
    assert df.loc["A", "total_out_flow"] == pytest.approx(100_000.0)
    assert df.loc["A", "total_in_flow"] == pytest.approx(20_000.0)
    assert df.loc["A", "net_flow"] == pytest.approx(20_000.0 - 100_000.0)
    assert df.loc["B", "txn_count"] == 3  # 2 outgoing + 1 incoming


def test_extract_all_clustering_coeff_is_the_documented_proxy_zero(
    extractor: FeatureExtractor,
) -> None:
    df = extractor.extract_all()
    assert (df["clustering_coeff"] == 0.0).all()


def test_extract_all_no_nans_no_infs(extractor: FeatureExtractor) -> None:
    df = extractor.extract_all()
    assert not df.isna().any().any()
    assert not (df.abs() == float("inf")).any().any()


def test_extract_all_handles_no_declared_income_column() -> None:
    accounts = pd.DataFrame({"account_id": ["X", "Y"]})
    txns = pd.DataFrame(
        [
            {
                "source_account": "X",
                "dest_account": "Y",
                "amount": 1_000.0,
                "timestamp": _ts("2026-01-01 09:00"),
                "channel": "UPI",
            }
        ]
    )
    store = NetworkXGraphStore(accounts, txns)
    df = FeatureExtractor(store, accounts, txns).extract_all()
    assert (df["income_volume_ratio"] == 0.0).all()


def test_safe_ratio_zero_denominator() -> None:
    assert safe_ratio(5, 0) == 0.0
    assert safe_ratio(5, 0, default=-1.0) == -1.0
    assert safe_ratio(10, 2) == 5.0


def test_safe_ratio_nan_denominator() -> None:
    import numpy as np

    assert safe_ratio(5, float("nan")) == 0.0
    assert safe_ratio(5, np.nan, default=-1.0) == -1.0


def test_channel_entropy_single_channel_is_zero() -> None:
    assert channel_entropy({"UPI": 10}) == 0.0


def test_channel_entropy_two_even_channels() -> None:
    # -0.5*log2(0.5) - 0.5*log2(0.5) = 1.0
    assert channel_entropy({"UPI": 5, "NEFT": 5}) == pytest.approx(1.0)


def test_gini_coefficient_equal_values_is_zero() -> None:
    import numpy as np

    assert gini_coefficient(np.array([10.0, 10.0, 10.0])) == pytest.approx(0.0)


def test_gini_coefficient_empty_is_zero() -> None:
    import numpy as np

    assert gini_coefficient(np.array([])) == 0.0
