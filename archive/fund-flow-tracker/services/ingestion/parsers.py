"""
Dataset parsers — IBM AML, PaySim, and custom CSV.
Each parser produces (accounts_df, transactions_df) in canonical format.
"""
import logging
import os
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

from services.common.constants import (
    ACCOUNT_TYPES, BRANCH_CITIES, CHANNELS, FX_RATES,
    IBM_CHANNEL_MAP, INCOME_BRACKETS, OCCUPATIONS,
)

logger = logging.getLogger(__name__)


class IBMAMLParser:
    """
    Parse IBM Transactions for Anti Money Laundering dataset.
    Source: https://www.kaggle.com/datasets/ealtman2019/ibm-transactions-for-anti-money-laundering-aml
    License: CDLA Sharing 1.0
    """

    def parse(self, source, max_rows: int = None) -> Tuple[pd.DataFrame, pd.DataFrame]:
        df = _read_source(source, nrows=max_rows)
        logger.info("Loaded IBM AML data: %d rows, columns: %s", len(df), list(df.columns))

        # ── Column normalisation ──
        col_map = {
            "Timestamp": "timestamp",
            "From Bank": "from_bank",
            "Account": "source_account",
            "To Bank": "to_bank",
            "Account.1": "dest_account",
            "Amount Received": "amount_received",
            "Receiving Currency": "receiving_currency",
            "Amount Paid": "amount_paid",
            "Payment Currency": "payment_currency",
            "Payment Format": "channel",
            "Is Laundering": "is_laundering",
        }
        if "From Bank" in df.columns:
            df = df.rename(columns=col_map)
        else:
            df.columns = [c.strip() for c in df.columns]
            lower_map = {c.lower().replace(" ", "_"): c for c in df.columns}
            renames = {}
            for target, original in col_map.items():
                key = target.lower().replace(" ", "_")
                if original not in df.columns and key in lower_map:
                    renames[lower_map[key]] = original
            df = df.rename(columns=renames)

        df["source_account"] = df["source_account"].astype(str).str.strip()
        df["dest_account"] = df["dest_account"].astype(str).str.strip()

        # Channel mapping to Indian context
        if "channel" in df.columns:
            df["channel"] = df["channel"].map(IBM_CHANNEL_MAP).fillna("net_banking")
        else:
            rng = np.random.default_rng(42)
            df["channel"] = rng.choice(CHANNELS, size=len(df))

        # Currency → INR (VECTORIZED — no row-by-row apply)
        if "amount_paid" in df.columns and "payment_currency" in df.columns:
            # Map currencies to FX rates, default to 83.0 (USD/INR)
            fx_series = df["payment_currency"].astype(str).map(FX_RATES).fillna(83.0)
            df["amount"] = df["amount_paid"].astype(float) * fx_series
        elif "amount_paid" in df.columns:
            df["amount"] = df["amount_paid"].astype(float) * 83.0
        elif "amount" not in df.columns:
            num_cols = df.select_dtypes(include=[np.number]).columns
            if len(num_cols) == 0:
                raise ValueError("No numeric amount column found in IBM AML data")
            df["amount"] = df[num_cols[0]] * 83.0

        # Timestamp
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        nat_mask = df["timestamp"].isna()
        if nat_mask.any():
            base = pd.Timestamp("2024-01-01")
            n_nat = int(nat_mask.sum())
            df.loc[nat_mask, "timestamp"] = pd.date_range(base, periods=n_nat, freq="min")

        df["txn_id"] = "IBM_" + pd.RangeIndex(len(df)).astype(str)
        df["is_laundering"] = df.get("is_laundering", pd.Series(0, index=df.index)).astype(int)
        df["txn_type"] = "transfer"

        keep_cols = ["txn_id", "timestamp", "source_account", "dest_account",
                     "amount", "channel", "txn_type", "is_laundering"]
        if "from_bank" in df.columns:
            keep_cols.append("from_bank")
        if "to_bank" in df.columns:
            keep_cols.append("to_bank")

        transactions_df = df[[c for c in keep_cols if c in df.columns]].copy()
        del df   # free raw DataFrame (~1–2 GB) before building account profiles
        accounts_df = _build_accounts(transactions_df)

        logger.info("IBM AML parsed: %d accounts, %d transactions, %d laundering",
                     len(accounts_df), len(transactions_df),
                     int(transactions_df["is_laundering"].sum()))
        return accounts_df, transactions_df


class PaySimParser:
    """Parse PaySim synthetic financial dataset."""

    def parse(self, source) -> Tuple[pd.DataFrame, pd.DataFrame]:
        df = _read_source(source)
        logger.info("Loaded PaySim data: %d rows", len(df))

        col_map = {
            "step": "step", "type": "txn_type", "amount": "amount",
            "nameOrig": "source_account", "nameDest": "dest_account",
            "isFraud": "is_laundering", "isFlaggedFraud": "is_flagged",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

        base = pd.Timestamp("2024-01-01")
        df["timestamp"] = base + pd.to_timedelta(df["step"].astype(int), unit="h")

        type_channel = {
            "CASH_IN": "branch_cash", "CASH_OUT": "ATM",
            "DEBIT": "net_banking", "PAYMENT": "UPI", "TRANSFER": "NEFT",
        }
        df["channel"] = df["txn_type"].map(type_channel).fillna("net_banking")
        df["txn_id"] = "PS_" + pd.RangeIndex(len(df)).astype(str)
        df["source_account"] = df["source_account"].astype(str)
        df["dest_account"] = df["dest_account"].astype(str)

        transactions_df = df[["txn_id", "timestamp", "source_account", "dest_account",
                              "amount", "channel", "txn_type", "is_laundering"]].copy()
        accounts_df = _build_accounts(transactions_df)

        logger.info("PaySim parsed: %d accounts, %d transactions", len(accounts_df), len(transactions_df))
        return accounts_df, transactions_df


class CSVParser:
    """Parse user-uploaded CSV with auto-detected or explicit column mapping."""

    REQUIRED = ["source_account", "dest_account", "amount", "timestamp"]

    def parse(self, source, column_mapping: Optional[Dict[str, str]] = None) -> Tuple[pd.DataFrame, pd.DataFrame]:
        df = _read_source(source)

        if column_mapping:
            df = df.rename(columns=column_mapping)
        else:
            df = self._auto_detect(df)

        missing = [c for c in self.REQUIRED if c not in df.columns]
        if missing:
            raise ValueError(f"Missing required columns after mapping: {missing}")

        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0)
        df["source_account"] = df["source_account"].astype(str)
        df["dest_account"] = df["dest_account"].astype(str)

        if "txn_id" not in df.columns:
            df["txn_id"] = "CSV_" + pd.RangeIndex(len(df)).astype(str)
        if "channel" not in df.columns:
            df["channel"] = "unknown"
        if "is_laundering" not in df.columns:
            df["is_laundering"] = 0
        if "txn_type" not in df.columns:
            df["txn_type"] = "transfer"

        transactions_df = df[["txn_id", "timestamp", "source_account", "dest_account",
                              "amount", "channel", "txn_type", "is_laundering"]].copy()
        accounts_df = _build_accounts(transactions_df)
        return accounts_df, transactions_df

    @staticmethod
    def auto_detect_columns(df: pd.DataFrame) -> Dict[str, str]:
        """Heuristic column mapping — returns {csv_col: canonical_col}."""
        mapping = {}
        for col in df.columns:
            cl = col.lower().strip()
            if any(w in cl for w in ["from", "source", "sender", "payer", "orig"]) and "source_account" not in mapping.values():
                mapping[col] = "source_account"
            elif any(w in cl for w in ["to", "dest", "receiver", "payee", "beneficiary"]) and "dest_account" not in mapping.values():
                mapping[col] = "dest_account"
            elif any(w in cl for w in ["amount", "value", "sum"]) and "amount" not in mapping.values():
                mapping[col] = "amount"
            elif any(w in cl for w in ["time", "date", "timestamp"]) and "timestamp" not in mapping.values():
                mapping[col] = "timestamp"
            elif any(w in cl for w in ["type", "channel", "method", "format"]) and "channel" not in mapping.values():
                mapping[col] = "channel"
            elif any(w in cl for w in ["fraud", "laundering", "label", "suspicious"]) and "is_laundering" not in mapping.values():
                mapping[col] = "is_laundering"
        return mapping

    def _auto_detect(self, df: pd.DataFrame) -> pd.DataFrame:
        mapping = self.auto_detect_columns(df)
        return df.rename(columns=mapping)


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

# Dtype map for the IBM AML CSV — cuts raw-load memory by ~40 %
_IBMAML_DTYPES = {
    "From Bank":           "category",
    "To Bank":             "category",
    "Receiving Currency":  "category",
    "Payment Currency":    "category",
    "Payment Format":      "category",
    "Amount Received":     "float32",
    "Amount Paid":         "float32",
    "Is Laundering":       "int8",
}


def _read_source(source, nrows: int = None) -> pd.DataFrame:
    """Read from filepath or pass-through DataFrame."""
    if isinstance(source, pd.DataFrame):
        return source.head(nrows).copy() if nrows else source.copy()
    if isinstance(source, str):
        if not os.path.isfile(source):
            raise FileNotFoundError(f"Data file not found: {source}")
        logger.info("Reading CSV: %s (nrows=%s)...", source, nrows or "ALL")
        # Only apply IBM-AML dtypes when the header matches; fall back to defaults
        try:
            header = pd.read_csv(source, nrows=0).columns.tolist()
            dtypes = {k: v for k, v in _IBMAML_DTYPES.items() if k in header}
        except Exception:
            dtypes = {}
        return pd.read_csv(source, nrows=nrows, dtype=dtypes)
    raise TypeError(f"Expected str or DataFrame, got {type(source)}")


def _build_accounts(transactions_df: pd.DataFrame) -> pd.DataFrame:
    """Synthesise account metadata from transaction data (vectorized)."""
    rng = np.random.default_rng(42)

    # Get unique accounts
    all_accounts = pd.concat([
        transactions_df["source_account"],
        transactions_df["dest_account"],
    ]).unique()  # returns ndarray; no Python-set overhead
    n = len(all_accounts)
    logger.info("Building account profiles for %d unique accounts...", n)

    # Compute in/out flows using groupby (vectorized)
    out_flow = transactions_df.groupby("source_account")["amount"].sum()
    in_flow = transactions_df.groupby("dest_account")["amount"].sum()
    out_count = transactions_df.groupby("source_account").size()
    in_count = transactions_df.groupby("dest_account").size()

    # Build DataFrame directly
    acc_df = pd.DataFrame({"account_id": all_accounts})
    acc_df["total_out_flow"] = acc_df["account_id"].map(out_flow).fillna(0).round(2)
    acc_df["total_in_flow"] = acc_df["account_id"].map(in_flow).fillna(0).round(2)
    acc_df["txn_count"] = (acc_df["account_id"].map(out_count).fillna(0) +
                           acc_df["account_id"].map(in_count).fillna(0)).astype(int)

    total_volume = acc_df["total_out_flow"] + acc_df["total_in_flow"]

    # Income bracket based on volume
    conditions = [
        total_volume > 5_000_000,
        total_volume > 1_500_000,
        total_volume > 500_000,
    ]
    choices = ["very_high", "high", "medium"]
    acc_df["income_bracket"] = np.select(conditions, choices, default="low")

    # Random metadata
    acc_df["account_type"] = rng.choice(ACCOUNT_TYPES, size=n)
    acc_df["branch_city"] = rng.choice(BRANCH_CITIES, size=n)
    acc_df["occupation"] = rng.choice(OCCUPATIONS, size=n)

    # Declared income — fully vectorised (no Python loop)
    lo_map = {k: v[0] for k, v in INCOME_BRACKETS.items()}
    hi_map = {k: v[1] for k, v in INCOME_BRACKETS.items()}
    lo_arr = acc_df["income_bracket"].map(lo_map).values.astype(float)
    hi_arr = acc_df["income_bracket"].map(hi_map).values.astype(float)
    acc_df["declared_annual_income"] = np.round(
        lo_arr + rng.random(n) * (hi_arr - lo_arr), 2
    )

    logger.info("Account profiles built: %d accounts", n)
    return acc_df
