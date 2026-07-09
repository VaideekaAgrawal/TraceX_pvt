"""
Feature Extraction — 30 graph + behavioural features per account.
Fully vectorised — no Python loop over accounts. Scales to millions of rows.
"""
import logging
import time as _time
from typing import Dict

import networkx as nx
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def safe_ratio(num: float, den: float, default: float = 0.0) -> float:
    if den == 0 or np.isnan(den):
        return default
    return num / den


def channel_entropy(counts: dict) -> float:
    if len(counts) <= 1:
        return 0.0
    total = sum(counts.values())
    if total == 0:
        return 0.0
    probs = [c / total for c in counts.values() if c > 0]
    return -sum(p * np.log2(p) for p in probs if p > 0)


def gini_coefficient(values: np.ndarray) -> float:
    if len(values) == 0 or np.sum(values) == 0:
        return 0.0
    s = np.sort(values)
    n = len(s)
    idx = np.arange(1, n + 1)
    return float((2 * np.sum(idx * s) / (n * np.sum(s)) - (n + 1) / n))


class FeatureExtractor:
    """Extract 30 features per account from graph + transaction data."""

    def __init__(self, graph_engine, accounts_df: pd.DataFrame, transactions_df: pd.DataFrame):
        self.graph = graph_engine
        self.accounts_df = accounts_df
        self.txns = transactions_df.copy()
        self.txns["timestamp"] = pd.to_datetime(self.txns["timestamp"])

    _FEATURE_COLS = [
        "in_degree", "out_degree", "total_in_flow", "total_out_flow", "net_flow",
        "pagerank", "betweenness", "clustering_coeff",
        "avg_txn_amount", "std_txn_amount", "max_txn_amount", "txn_count",
        "unique_channels", "channel_entropy",
        "velocity_1hour", "near_threshold_count",
        "dormancy_days", "income_volume_ratio",
        "is_weekend_heavy", "night_txn_ratio",
        "reciprocity_ratio", "geographic_dispersion", "max_daily_txn_count",
        "round_number_ratio", "temporal_regularity", "new_counterparty_ratio",
        "cross_bank_ratio", "amount_concentration",
    ]

    def extract_all(self) -> pd.DataFrame:
        """
        Fully vectorised feature extraction — no Python loop over accounts.
        Scales to millions of rows in O(N_transactions) time.
        """
        t0 = _time.time()
        txns = self.txns
        G = self.graph.G
        n_nodes = len(G)

        # ── A. Graph centrality (bulk NetworkX) ──────────────────────────────
        logger.info("  ├─ Features: Computing graph centrality (%d nodes)...", n_nodes)
        centrality = self.graph.compute_centrality()
        pr = centrality["pagerank"]
        bc = centrality["betweenness"]

        in_deg_s  = pd.Series(dict(G.in_degree()),  name="in_degree")
        out_deg_s = pd.Series(dict(G.out_degree()), name="out_degree")
        pr_s      = pd.Series(pr, name="pagerank")
        bc_s      = pd.Series(bc, name="betweenness")

        logger.info("  ├─ Features: Vectorised aggregations over %d transactions...", len(txns))

        # ── B. Outgoing (source_account) aggregations ────────────────────────
        # Compute indicator series WITHOUT copying the full 5M-row DataFrame
        has_banks = "from_bank" in txns.columns and "to_bank" in txns.columns
        _is_cross = (
            (txns["from_bank"].astype(str) != txns["to_bank"].astype(str)).astype("float32")
            if has_banks else pd.Series(0.0, index=txns.index, dtype="float32")
        )
        _is_round = (txns["amount"] % 10_000 == 0).astype("float32")
        _is_near  = ((txns["amount"] >= 900_000) & (txns["amount"] < 1_000_000)).astype("float32")

        src_agg = pd.DataFrame({
            "source_account": txns["source_account"],
            "amount":         txns["amount"],
            "dest_account":   txns["dest_account"],
            "_is_cross":      _is_cross,
            "_is_round":      _is_round,
            "_is_near":       _is_near,
        }).groupby("source_account").agg(
            total_out_flow     =("amount",       "sum"),
            txn_count_out      =("amount",       "count"),
            out_partners       =("dest_account", "nunique"),
            cross_bank_ratio   =("_is_cross",    "mean"),
            near_threshold_count=("_is_near",    "sum"),
            round_number_ratio =("_is_round",    "mean"),
        )
        src_agg.index.name = "account_id"
        del _is_cross, _is_round, _is_near

        # ── C. Incoming (dest_account) aggregations ──────────────────────────
        dst_agg = txns.groupby("dest_account").agg(
            total_in_flow=("amount",         "sum"),
            txn_count_in =("amount",         "count"),
            in_partners  =("source_account", "nunique"),
        )
        dst_agg.index.name = "account_id"

        # ── D. All-transactions aggregations (source + dest view) ────────────
        # Build both views with only the 4 needed columns, then concat and process
        sv = txns[["source_account", "amount", "channel", "timestamp"]].rename(
            columns={"source_account": "account_id"})
        dv = txns[["dest_account", "amount", "channel", "timestamp"]].rename(
            columns={"dest_account": "account_id"})
        av = pd.concat([sv, dv], ignore_index=True)
        del sv, dv   # free the views immediately

        av["_is_wkend"] = (av["timestamp"].dt.dayofweek >= 5).astype("float32")
        av["_is_night"] = av["timestamp"].dt.hour.isin([23, 0, 1, 2, 3, 4]).astype("float32")

        all_agg = av.groupby("account_id").agg(
            avg_txn_amount  =("amount",    "mean"),
            std_txn_amount  =("amount",    "std"),
            max_txn_amount  =("amount",    "max"),
            txn_count       =("amount",    "count"),
            unique_channels =("channel",   "nunique"),
            is_weekend_heavy=("_is_wkend", "mean"),
            night_txn_ratio =("_is_night", "mean"),
            _t_min          =("timestamp", "min"),
            _t_max          =("timestamp", "max"),
        )
        all_agg["dormancy_days"] = (
            (all_agg["_t_max"] - all_agg["_t_min"]).dt.total_seconds() / 86_400
        ).fillna(0)
        all_agg.drop(columns=["_t_min", "_t_max"], inplace=True)

        # channel_entropy: approx via unique_channels / log2(txn_count+1)
        all_agg["channel_entropy"] = (
            all_agg["unique_channels"]
            / np.log2(all_agg["txn_count"].clip(lower=1) + 1)
        )
        # amount_concentration: coefficient of variation as Gini proxy
        all_agg["amount_concentration"] = (
            all_agg["std_txn_amount"] / all_agg["avg_txn_amount"].replace(0, 1)
        ).clip(upper=10).fillna(0)
        # temporal_regularity: avg seconds between txns
        all_agg["temporal_regularity"] = (
            all_agg["dormancy_days"] * 86_400
            / all_agg["txn_count"].clip(lower=1)
        )

        # ── E. Max daily transaction count ───────────────────────────────────
        logger.info("  ├─ Features: Computing daily velocity...")
        av["_date"] = av["timestamp"].dt.date
        daily_counts = av.groupby(["account_id", "_date"]).size()
        max_daily = daily_counts.groupby(level="account_id").max().rename("max_daily_txn_count")
        del av, daily_counts  # free the 10M-row DataFrame

        # ── F. Reciprocity ───────────────────────────────────────────────────
        logger.info("  ├─ Features: Computing reciprocity...")
        # Use only the unique pairs (much smaller than full 5M rows)
        pairs_fwd = txns[["source_account", "dest_account"]].drop_duplicates()
        pairs_bwd = pairs_fwd.rename(
            columns={"source_account": "dest_account", "dest_account": "source_account"})
        reciprocal = pairs_fwd.merge(pairs_bwd, on=["source_account", "dest_account"])
        recip_count = (
            reciprocal.groupby("source_account").size()
            .rename("reciprocal_count")
        )
        recip_count.index.name = "account_id"
        del pairs_fwd, pairs_bwd, reciprocal

        # ── G. Declared income ───────────────────────────────────────────────
        if "declared_annual_income" in self.accounts_df.columns:
            income_s = (
                self.accounts_df.set_index("account_id")["declared_annual_income"]
                .astype(float)
                .rename("_declared_income")
            )
        else:
            income_s = pd.Series(dtype=float, name="_declared_income")

        # ── H. Assemble ──────────────────────────────────────────────────────
        logger.info("  ├─ Features: Assembling final feature matrix...")
        all_accounts = pd.Index(list(G.nodes()), name="account_id")
        df = pd.DataFrame(index=all_accounts)

        for s in [in_deg_s, out_deg_s, pr_s, bc_s]:
            df = df.join(s, how="left")
        df["clustering_coeff"] = 0.0   # too expensive for large graphs

        df = df.join(src_agg, how="left")
        df = df.join(dst_agg, how="left")
        df = df.join(all_agg, how="left")
        df = df.join(max_daily, how="left")
        df = df.join(recip_count, how="left")
        df = df.join(income_s, how="left")

        # ── I. Derived features ──────────────────────────────────────────────
        df["net_flow"] = df["total_in_flow"].fillna(0) - df["total_out_flow"].fillna(0)
        monthly_vol = df["total_in_flow"].fillna(0) + df["total_out_flow"].fillna(0)
        df["income_volume_ratio"] = (
            df["_declared_income"].fillna(0) / 12
        ) / monthly_vol.replace(0, 1)

        total_partners = df["out_partners"].fillna(0) + df["in_partners"].fillna(0)
        df["reciprocity_ratio"] = (
            df["reciprocal_count"].fillna(0) / total_partners.replace(0, 1)
        )
        df["new_counterparty_ratio"] = total_partners / df["txn_count"].fillna(1).replace(0, 1)
        # Geographic dispersion: unique counterparty bank codes per account (proxy for geography)
        if "to_bank" in self.txns.columns or "from_bank" in self.txns.columns:
            bank_parts = []
            if "to_bank" in self.txns.columns:
                s = self.txns.groupby("source_account")["to_bank"].nunique()
                s.index.name = "account_id"
                bank_parts.append(s)
            if "from_bank" in self.txns.columns:
                s = self.txns.groupby("dest_account")["from_bank"].nunique()
                s.index.name = "account_id"
                bank_parts.append(s)
            geo_div = bank_parts[0]
            if len(bank_parts) > 1:
                geo_div = geo_div.add(bank_parts[1], fill_value=0)
            geo_div = (geo_div.clip(upper=50) / 50.0).rename("geographic_dispersion")
            df = df.join(geo_div, how="left")
            df["geographic_dispersion"] = df["geographic_dispersion"].fillna(0.0)
        else:
            df["geographic_dispersion"] = 0.0
        # velocity proxy — max_daily captures burst behaviour
        df["velocity_1hour"]  = df["max_daily_txn_count"].fillna(0)
        df["cross_bank_ratio"] = df["cross_bank_ratio"].fillna(0.5)

        df = df.reindex(columns=self._FEATURE_COLS).fillna(0).astype("float32")

        # Free intermediate DataFrames before returning
        import gc
        gc.collect()

        elapsed = _time.time() - t0
        logger.info("  ├─ Features: ✅ %d features × %d accounts (%.1fs)",
                    len(self._FEATURE_COLS), len(df), elapsed)
        return df

