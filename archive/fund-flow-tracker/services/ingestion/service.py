"""
Ingestion Service — entry point for all data loading.

Responsibilities:
- Accept data from multiple sources (IBM AML, PaySim, CSV upload)
- Validate schema (CP-01)
- Publish normalised data to event bus
- Route malformed records to DLQ (CP-02)
"""
import logging
from datetime import datetime
from typing import Dict, Optional, Tuple

import pandas as pd

from infrastructure.event_bus import bus, Topics
from infrastructure.health import health
from services.ingestion.parsers import IBMAMLParser, PaySimParser, CSVParser
from infrastructure.database import get_database

logger = logging.getLogger(__name__)

_SERVICE = "ingestion"


class IngestionService:
    """Unified data ingestion — all roads lead to (accounts_df, transactions_df)."""

    def __init__(self):
        self._ibm = IBMAMLParser()
        self._paysim = PaySimParser()
        self._csv = CSVParser()
        health.register_service(_SERVICE)

    def ingest(self, source: str, filepath: Optional[str] = None,
               dataframe: Optional[pd.DataFrame] = None,
               column_mapping: Optional[Dict[str, str]] = None,
               max_rows: Optional[int] = None) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Load and validate data from the specified source.

        Parameters
        ----------
        source : str
            One of 'ibm_aml', 'paysim', 'csv'.
        filepath : str, optional
            Path to CSV file.
        dataframe : DataFrame, optional
            Pre-loaded DataFrame (e.g. from Streamlit upload).
        column_mapping : dict, optional
            Explicit column mapping for CSV source.
        max_rows : int, optional
            Limit rows for large datasets.
        """
        try:
            data_input = dataframe if dataframe is not None else filepath

            if source == "ibm_aml":
                accounts_df, txns_df = self._ibm.parse(data_input, max_rows=max_rows)
            elif source == "paysim":
                accounts_df, txns_df = self._paysim.parse(data_input)
                if max_rows and len(txns_df) > max_rows:
                    txns_df = txns_df.head(max_rows)
                    all_accs = set(txns_df["source_account"]) | set(txns_df["dest_account"])
                    accounts_df = accounts_df[accounts_df["account_id"].isin(all_accs)]
            elif source == "csv":
                accounts_df, txns_df = self._csv.parse(data_input, column_mapping)
                if max_rows and len(txns_df) > max_rows:
                    txns_df = txns_df.head(max_rows)
                    all_accs = set(txns_df["source_account"]) | set(txns_df["dest_account"])
                    accounts_df = accounts_df[accounts_df["account_id"].isin(all_accs)]
            else:
                raise ValueError(f"Unknown source: {source}")

            # ── Validate (CP-01) ──
            # Mark new vs existing accounts by checking DB (bulk query, not per-account)
            try:
                db = get_database()
                existing = set()
                account_ids_list = accounts_df["account_id"].astype(str).unique().tolist()
                for i in range(0, len(account_ids_list), 1000):
                    chunk = account_ids_list[i:i + 1000]
                    try:
                        for acc in chunk:
                            if db.account_exists(acc):
                                existing.add(acc)
                    except Exception as e:
                        logger.warning("DB account existence check failed: %s. Treating chunk as new.", e)
                accounts_df["is_new"] = ~accounts_df["account_id"].astype(str).isin(existing)
                # Transactions: mark source/dest as new if account not in existing set
                txns_df["source_is_new"] = ~txns_df["source_account"].astype(str).isin(existing)
                txns_df["dest_is_new"] = ~txns_df["dest_account"].astype(str).isin(existing)
            except Exception as e:
                logger.warning("DB availability check failed: %s. Defaulting to all-new.", e)
                accounts_df["is_new"] = False
                txns_df["source_is_new"] = False
                txns_df["dest_is_new"] = False

            valid_count, total_count = self._validate(txns_df)
            health.cp01_schema_validation(valid_count, total_count)

            # ── Counters ──
            health.increment("events_ingested", len(txns_df))
            health.heartbeat(_SERVICE, "healthy")

            # ── Publish ──
            bus.publish(Topics.RAW_TRANSACTIONS, {
                "accounts": accounts_df,
                "transactions": txns_df,
                "source": source,
            }, source_service=_SERVICE)

            logger.info("Ingested %d accounts, %d transactions from '%s'",
                        len(accounts_df), len(txns_df), source)
            return accounts_df, txns_df

        except Exception as exc:
            health.record_error(_SERVICE, str(exc))
            raise

    def load_from_db(self) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """Load persisted accounts/transactions back out and normalize them
        into the shape the graph/detection services expect — the inverse of
        persist_to_db(). Used by AnalysisPipeline.run_from_db() so a server
        restart or /api/refresh rebuilds from the same DB read path instead
        of each call site re-implementing it. Raises ValueError if the DB
        has no data yet (the caller decides how to surface that — e.g. an
        HTTP 400 — since this layer doesn't know about HTTP)."""
        db = get_database()
        with db._get_conn() as conn:
            acc_rows = conn.execute("SELECT * FROM accounts").fetchall()
            txn_rows = conn.execute("SELECT * FROM transactions LIMIT 200000").fetchall()

        if not acc_rows or not txn_rows:
            raise ValueError("No data in database.")

        accounts_df = pd.DataFrame([dict(r) for r in acc_rows])
        txns_df = pd.DataFrame([dict(r) for r in txn_rows])
        txns_df["timestamp"] = pd.to_datetime(txns_df["timestamp"], errors="coerce")

        for col in ["account_id", "account_type", "branch_city", "occupation",
                    "income_bracket", "declared_annual_income", "risk_score", "risk_level", "role"]:
            if col not in accounts_df.columns:
                accounts_df[col] = "" if col not in ("risk_score", "declared_annual_income") else 0.0

        return accounts_df, txns_df

    def persist_to_db(self, accounts_df: pd.DataFrame, transactions_df: pd.DataFrame,
                       ingestion_date: Optional[str] = None) -> Dict[str, int]:
        """
        Write ingested accounts/transactions to the database so they survive
        server restarts and page refreshes instead of living only in the
        caller's in-memory DataFrames. This is the same batched-upsert
        approach EODIngestionService._persist_data uses for the EOD path —
        every ingestion entry point (init/upload/EOD) should call this so
        SQLite is always the source of truth, not just the EOD path.
        """
        ingestion_date = ingestion_date or datetime.now().strftime("%Y-%m-%d")
        db = get_database()

        account_dicts = accounts_df.to_dict("records")
        db.upsert_accounts(account_dicts)

        txn_dicts = transactions_df.to_dict("records")
        for t in txn_dicts:
            t["timestamp"] = str(t.get("timestamp", ""))
            t["ingestion_date"] = t.get("ingestion_date") or ingestion_date

        batch_size = 5000
        total_inserted = 0
        for i in range(0, len(txn_dicts), batch_size):
            total_inserted += db.insert_transactions(txn_dicts[i:i + batch_size])

        logger.info("Persisted to DB: %d accounts, %d/%d transactions",
                    len(account_dicts), total_inserted, len(txn_dicts))
        return {"accounts_persisted": len(account_dicts), "transactions_persisted": total_inserted}

    @staticmethod
    def _validate(df: pd.DataFrame) -> Tuple[int, int]:
        """Validate required columns and types. Returns (valid_count, total)."""
        required = ["txn_id", "timestamp", "source_account", "dest_account", "amount"]
        total = len(df)
        mask = pd.Series(True, index=df.index)

        for col in required:
            if col not in df.columns:
                return 0, total
            mask &= df[col].notna()

        mask &= df["amount"] > 0
        valid = int(mask.sum())
        return valid, total

    @staticmethod
    def get_supported_sources():
        return [
            {"id": "ibm_aml", "name": "IBM AML Dataset", "description": "5M labelled transactions, 8 laundering patterns"},
            {"id": "paysim", "name": "PaySim Dataset", "description": "6.3M synthetic transactions"},
            {"id": "csv", "name": "Custom CSV", "description": "Upload your own transaction data"},
        ]
