"""
EOD (End-of-Day) Ingestion Service — daily CSV ingestion with incremental analysis.

This service handles:
1. Accept daily transaction CSV dumps (same format as training data)
2. Validate CSV schema against expected columns
3. Idempotent processing (skip already-ingested files via hash)
4. For new accounts: ingest and run detection on today's data
5. For existing accounts: fetch last 7 days from DB + today, run incremental detection
6. Store all transactions and accounts in the database
7. Generate new alerts from incremental detections
"""
import hashlib
import logging
import os
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from infrastructure.config import config
from infrastructure.database import get_database, compute_file_hash, DB_BACKEND, NEO4J_URI
from services.ingestion.service import IngestionService

logger = logging.getLogger(__name__)

# Expected columns matching training data format (IBM AML)
EXPECTED_COLUMNS = [
    "Timestamp", "From Bank", "Account", "To Bank", "Account.1",
    "Amount Received", "Receiving Currency", "Amount Paid",
    "Payment Currency", "Payment Format", "Is Laundering"
]

# Alternative normalized column names
NORMALIZED_COLUMNS = [
    "timestamp", "source_account", "dest_account", "amount",
    "channel", "is_laundering"
]


# These three checks (round-trip's ratio/3-hop mode, fan-in, profile-mismatch) do
# dict/groupby joins that are cheap on the small per-row batches the real-time
# streaming demo produces, but scale poorly in *alert quality* (not just perf) on
# large, densely-interconnected multi-thousand-row daily batches — a dense graph
# makes coincidental 3-hop return-ratio matches and >10x cumulative-volume ratios
# common even in non-fraudulent data. Cap them to genuinely small/incremental
# batches; large batches fall back to the original, already-production-proven
# 2-hop round-trip check and simply skip fan-in/profile-mismatch (unchanged from
# pre-existing behaviour) to avoid alert-storming a full EOD file ingest.
_SMALL_BATCH_ROW_CAP = 300


def _make_alert_id(account_id: str, pattern: str, date_str: str) -> str:
    """Deterministic alert ID for a single-account alert — see
    make_deterministic_alert_id for the shared multi-account scheme both
    this (realtime lightweight) path and the full pipeline path write into
    the same `alerts` table with."""
    from services.common.models import make_deterministic_alert_id
    return make_deterministic_alert_id([account_id], pattern, date_str)


class EODIngestionService:
    """Handles daily EOD transaction file ingestion with incremental analysis."""

    def __init__(self):
        self._db = None
        self._ingestion_svc = IngestionService()
        # Tracks alert_ids already raised in this process, so re-detecting the same
        # (account, pattern, date) — which is expected as more incremental evidence
        # streams in — refreshes the existing alert instead of being reported/
        # published as a brand-new one. See _record_new_alerts.
        self._raised_alert_ids: set = set()

    @property
    def db(self):
        if self._db is None:
            self._db = get_database()
        return self._db

    def ingest_daily_file(
        self,
        filepath: str,
        date: Optional[str] = None,
        max_rows: Optional[int] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        """
        Ingest a daily transaction CSV file.

        Parameters
        ----------
        filepath : str
            Path to the CSV file (same format as training data).
        date : str, optional
            Date of the transactions (YYYY-MM-DD). Defaults to today.
        max_rows : int, optional
            Limit rows for testing.
        force : bool
            Skip idempotency check and re-ingest.

        Returns
        -------
        dict with ingestion summary including new accounts, existing accounts,
        alerts generated, etc.
        """
        start_time = time.time()
        date = date or datetime.now().strftime("%Y-%m-%d")

        logger.info("=" * 60)
        logger.info("EOD INGESTION STARTING — date=%s, file=%s", date, filepath)
        logger.info("=" * 60)

        # 1. Validate file exists
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"File not found: {filepath}")

        # 2. Idempotency check
        file_hash = compute_file_hash(filepath)
        if not force and self.db.is_file_ingested(file_hash):
            logger.info("File already ingested (hash=%s). Skipping.", file_hash[:16])
            return {
                "status": "skipped",
                "reason": "already_ingested",
                "file_hash": file_hash[:16],
            }

        # 3. Load and validate CSV
        logger.info("┌─ Step 1: Loading and validating CSV...")
        df = self._load_and_validate(filepath, max_rows)
        logger.info("└─ Step 1: ✅ Loaded %d transactions", len(df))

        # 4. Normalize to internal format
        logger.info("┌─ Step 2: Normalizing data...")
        txns_df, accounts_df = self._normalize(df, date, file_hash=file_hash)
        logger.info("└─ Step 2: ✅ %d transactions, %d unique accounts",
                    len(txns_df), len(accounts_df))

        # 5. Classify accounts as new or existing
        logger.info("┌─ Step 3: Classifying accounts (new vs existing)...")
        new_accounts, existing_accounts = self._classify_accounts(accounts_df)
        logger.info("└─ Step 3: ✅ %d new accounts, %d existing accounts",
                    len(new_accounts), len(existing_accounts))

        # 6. Store transactions and accounts in DB
        logger.info("┌─ Step 4: Persisting to database...")
        self._persist_data(txns_df, accounts_df, date)
        logger.info("└─ Step 4: ✅ Data persisted")

        # 7. Record ingestion. Detection itself does NOT happen here — the
        # caller (api/server.py's /api/ingest routes) runs the full
        # pipeline once over the cumulative DB dataset after this returns
        # (via AnalysisPipeline.run_from_db()). This used to also call
        # _run_incremental_analysis() here, running the 7 lightweight
        # inline detectors over just this file, followed immediately by a
        # second, full 6-detector+ML pass over the whole DB — duplicated
        # work whose deterministic alert IDs silently overwrote each
        # other. _run_incremental_analysis() (and the lightweight
        # detectors it calls) is NOT dead code: ingest_transaction_rows()
        # below still uses it for the real-time streaming demo, which
        # needs a genuinely fast per-row path rather than the full
        # pipeline. It must stay reachable only from that path.
        self.db.record_ingestion(
            file_hash=file_hash,
            filename=os.path.basename(filepath),
            date=date,
            num_transactions=len(txns_df),
            num_accounts=len(accounts_df),
        )

        elapsed = time.time() - start_time
        summary = {
            "status": "completed",
            "date": date,
            "file": os.path.basename(filepath),
            "file_hash": file_hash[:16],
            "total_transactions": len(txns_df),
            "total_accounts": len(accounts_df),
            "new_accounts": len(new_accounts),
            "existing_accounts": len(existing_accounts),
            "processing_time_sec": round(elapsed, 2),
        }

        logger.info("=" * 60)
        logger.info("EOD INGESTION COMPLETE — %.1fs", elapsed)
        logger.info("  Transactions: %d | New accounts: %d — detection runs next via AnalysisPipeline",
                    len(txns_df), len(new_accounts))
        logger.info("=" * 60)

        return summary

    def ingest_transaction_rows(self, rows_df: pd.DataFrame, date: str) -> Dict[str, Any]:
        """
        Ingest an in-memory batch of transaction rows (IBM-AML-shaped, same columns
        as ingest_daily_file's CSV input) directly through the same normalize →
        classify → persist → incremental-analysis pipeline — without the file-hash
        idempotency check, since there's no file to dedupe against.

        Used by the real-time streaming demo (services/realtime/stream_service.py)
        to push one transaction at a time through genuine detection logic.

        Returns the same summary shape as ingest_daily_file().
        """
        start_time = time.time()

        # _normalize() derives txn_id from file_hash[:8] + a positional index that
        # restarts at 0 for every call — without a per-call-unique hash here, two
        # single-row batches ingested back-to-back (as the real-time stream does)
        # would generate the SAME txn_id and the second row would be silently
        # dropped by the DB's INSERT OR IGNORE on the txn_id primary key. A fresh
        # uuid per call guarantees uniqueness across repeated streaming calls.
        synthetic_hash = uuid.uuid4().hex
        txns_df, accounts_df = self._normalize(rows_df, date, file_hash=synthetic_hash)
        new_accounts, existing_accounts = self._classify_accounts(accounts_df)
        self._persist_data(txns_df, accounts_df, date)
        analysis_results = self._run_incremental_analysis(
            txns_df, new_accounts, existing_accounts, date
        )

        elapsed = time.time() - start_time
        return {
            "status": "completed",
            "date": date,
            "total_transactions": len(txns_df),
            "total_accounts": len(accounts_df),
            "new_accounts": len(new_accounts),
            "existing_accounts": len(existing_accounts),
            "alerts_generated": analysis_results.get("alerts_generated", 0),
            "patterns_detected": analysis_results.get("patterns_detected", {}),
            "processing_time_sec": round(elapsed, 3),
        }

    def _load_and_validate(self, filepath: str, max_rows: Optional[int] = None) -> pd.DataFrame:
        """Load CSV and validate it matches expected format."""
        # Try reading with different possible formats
        df = pd.read_csv(filepath, nrows=max_rows)

        # Check if it matches IBM AML format
        if all(col in df.columns for col in ["Timestamp", "From Bank", "Account"]):
            logger.info("Detected IBM AML format")
            return df

        # Check if it's already normalized
        if all(col in df.columns for col in ["timestamp", "source_account", "dest_account", "amount"]):
            logger.info("Detected normalized format")
            return df

        # Try to find required columns by fuzzy matching
        col_lower = {c.lower().strip(): c for c in df.columns}
        required_found = 0
        for req in ["timestamp", "amount"]:
            if req in col_lower:
                required_found += 1

        if required_found < 2:
            raise ValueError(
                f"CSV format not recognized. Expected columns matching IBM AML format "
                f"or normalized format. Found: {list(df.columns)}"
            )

        return df

    def _normalize(self, df: pd.DataFrame, date: str, file_hash: str = "") -> Tuple[pd.DataFrame, pd.DataFrame]:
        """Normalize raw CSV to internal transaction format."""
        from utils.constants import IBM_CHANNEL_MAP, FX_RATES, CHANNELS

        # IBM AML format
        if "From Bank" in df.columns or "Account" in df.columns:
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
            df = df.rename(columns=col_map)

            df["source_account"] = df["source_account"].astype(str).str.strip()
            df["dest_account"] = df["dest_account"].astype(str).str.strip()

            if "channel" in df.columns:
                df["channel"] = df["channel"].map(IBM_CHANNEL_MAP).fillna("net_banking")

            if "amount_paid" in df.columns and "payment_currency" in df.columns:
                df["amount"] = df.apply(
                    lambda r: r["amount_paid"] * FX_RATES.get(str(r.get("payment_currency", "")), 83.0),
                    axis=1
                )
            elif "amount" not in df.columns:
                df["amount"] = df.get("amount_paid", pd.Series([0] * len(df)))

        # Ensure required columns
        df["source_account"] = df["source_account"].astype(str).str.strip()
        df["dest_account"] = df["dest_account"].astype(str).str.strip()

        if "timestamp" not in df.columns:
            df["timestamp"] = datetime.now().isoformat()
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")

        if "amount" not in df.columns:
            df["amount"] = 0.0
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0)

        if "channel" not in df.columns:
            df["channel"] = np.random.choice(CHANNELS, size=len(df))

        if "is_laundering" not in df.columns:
            df["is_laundering"] = 0

        # Generate txn_ids — use file_hash to guarantee uniqueness across files uploaded on the same date
        _fpath_hash = file_hash[:8] if file_hash else hashlib.md5(str(date).encode()).hexdigest()[:8]
        df["txn_id"] = [
            f"TXN-{date}-{_fpath_hash}-{i:08d}" for i in range(len(df))
        ]
        df["txn_type"] = "transfer"
        df["ingestion_date"] = date

        # Create transactions dataframe
        txns_df = df[["txn_id", "timestamp", "source_account", "dest_account",
                      "amount", "channel", "txn_type", "is_laundering", "ingestion_date"]].copy()

        # Create accounts dataframe
        all_accounts = set(txns_df["source_account"]) | set(txns_df["dest_account"])
        accounts_df = pd.DataFrame({"account_id": list(all_accounts)})
        accounts_df["account_type"] = "savings"
        accounts_df["branch_city"] = "Unknown"
        accounts_df["risk_score"] = 0.0
        accounts_df["risk_level"] = "LOW"
        accounts_df["role"] = "NORMAL"

        _BRACKETS = {
            "Business": "High", "Salaried": "Medium", "Self-Employed": "Medium-High",
            "Trader": "High", "Professional": "High", "Retired": "Low-Medium", "Farmer": "Low",
        }

        if "Source_Occupation" in df.columns and "Source_Declared_Income" in df.columns:
            # Real profile columns exist in CSV — extract per-account attributes
            src_prof = df[["source_account", "Source_Occupation", "Source_Declared_Income"]].rename(
                columns={"source_account": "account_id", "Source_Occupation": "occupation",
                         "Source_Declared_Income": "declared_annual_income"}
            ).drop_duplicates("account_id")
            dst_prof = df[["dest_account", "Dest_Occupation", "Dest_Declared_Income"]].rename(
                columns={"dest_account": "account_id", "Dest_Occupation": "occupation",
                         "Dest_Declared_Income": "declared_annual_income"}
            ).drop_duplicates("account_id")
            acc_prof = pd.concat([src_prof, dst_prof]).drop_duplicates("account_id").set_index("account_id")
            accounts_df["occupation"] = accounts_df["account_id"].map(acc_prof["occupation"]).fillna("Unknown")
            accounts_df["declared_annual_income"] = pd.to_numeric(
                accounts_df["account_id"].map(acc_prof["declared_annual_income"]), errors="coerce"
            ).fillna(0.0)
            accounts_df["income_bracket"] = accounts_df["occupation"].map(_BRACKETS).fillna("Medium")
        else:
            # Fallback: deterministic synthetic profiles seeded by account_id
            _OCCUPATIONS = ["Business", "Salaried", "Self-Employed", "Trader", "Professional", "Retired", "Farmer"]
            _INCOME_RANGES = {
                "Business":      (800_000,  5_000_000),
                "Salaried":      (300_000,  1_200_000),
                "Self-Employed": (400_000,  2_000_000),
                "Trader":        (600_000,  3_000_000),
                "Professional":  (700_000,  2_500_000),
                "Retired":       (200_000,    600_000),
                "Farmer":        (150_000,    500_000),
            }

            def _synth_income(acc_id: str):
                seed = int(hashlib.md5(acc_id.encode()).hexdigest(), 16)
                occ = _OCCUPATIONS[seed % len(_OCCUPATIONS)]
                lo, hi = _INCOME_RANGES[occ]
                income = lo + (seed % (hi - lo))
                return occ, _BRACKETS[occ], income

            synth = [_synth_income(str(aid)) for aid in accounts_df["account_id"]]
            accounts_df["occupation"]             = [s[0] for s in synth]
            accounts_df["income_bracket"]         = [s[1] for s in synth]
            accounts_df["declared_annual_income"] = [float(s[2]) for s in synth]

        return txns_df, accounts_df

    def _classify_accounts(self, accounts_df: pd.DataFrame) -> Tuple[List[str], List[str]]:
        """Classify accounts as new (not in DB) or existing (already in DB). Uses chunked bulk queries."""
        all_ids = accounts_df["account_id"].astype(str).tolist()
        existing_set: set = set()
        try:
            for i in range(0, len(all_ids), 1000):
                chunk = all_ids[i:i + 1000]
                for acc_id in chunk:
                    try:
                        if self.db.account_exists(acc_id):
                            existing_set.add(acc_id)
                    except Exception as e:
                        logger.warning("DB check failed for account %s: %s", acc_id, e)
        except Exception as e:
            logger.warning("_classify_accounts DB error: %s. Treating all as new.", e)
        new_accounts = [a for a in all_ids if a not in existing_set]
        existing_accounts = [a for a in all_ids if a in existing_set]
        return new_accounts, existing_accounts

    def _persist_data(self, txns_df: pd.DataFrame, accounts_df: pd.DataFrame, date: str):
        """Store transactions and accounts in database (delegates to the shared
        IngestionService.persist_to_db so every ingestion path — init/upload/EOD —
        writes through the same code)."""
        txns_df = txns_df.copy()
        txns_df["ingestion_date"] = date
        result = self._ingestion_svc.persist_to_db(accounts_df, txns_df, ingestion_date=date)
        logger.info("  Total persisted: %d transactions, %d accounts",
                    result["transactions_persisted"], result["accounts_persisted"])

    def _run_incremental_analysis(
        self,
        today_txns: pd.DataFrame,
        new_accounts: List[str],
        existing_accounts: List[str],
        date: str,
    ) -> Dict[str, Any]:
        """
        Run incremental fraud detection:
        - New accounts: analyze today's transactions only
        - Existing accounts: analyze today + last 7 days transactions
        """
        alerts_generated = 0
        patterns_detected: Dict[str, int] = {}

        # For new accounts: detect patterns in today's transactions
        if new_accounts:
            new_acc_txns = today_txns[
                today_txns["source_account"].isin(new_accounts) |
                today_txns["dest_account"].isin(new_accounts)
            ]
            if len(new_acc_txns) > 0:
                new_alerts, new_patterns = self._detect_patterns(new_acc_txns, "new_account")
                alerts_generated += new_alerts
                for k, v in new_patterns.items():
                    patterns_detected[k] = patterns_detected.get(k, 0) + v

        # For existing accounts: fetch 7-day window + today and detect
        if existing_accounts:
            # Sample existing accounts to avoid processing too many
            sample_size = min(len(existing_accounts), 10000)
            sampled = existing_accounts[:sample_size]

            # Fetch historical transactions from DB for these accounts
            historical_txns = []
            batch_size = 100
            for i in range(0, len(sampled), batch_size):
                batch_accounts = sampled[i:i + batch_size]
                for acc_id in batch_accounts:
                    hist = self.db.get_transactions_for_account(acc_id, days=7)
                    historical_txns.extend(hist)

            if historical_txns:
                hist_df = pd.DataFrame(historical_txns)
                # Merge with today's transactions for these accounts
                existing_today = today_txns[
                    today_txns["source_account"].isin(sampled) |
                    today_txns["dest_account"].isin(sampled)
                ]
                # Combine historical + today. _persist_data() already wrote today's
                # rows to the DB before this runs, so hist_df (fetched from the DB)
                # can already include them alongside existing_today's in-memory copy
                # of the same rows — dedupe by txn_id so pattern detectors don't
                # double-count a transaction that appears via both sources.
                if "timestamp" in hist_df.columns:
                    combined = pd.concat([hist_df, existing_today], ignore_index=True)
                    if "txn_id" in combined.columns:
                        combined = combined.drop_duplicates(subset="txn_id", keep="last")
                else:
                    combined = existing_today

                if len(combined) > 0:
                    existing_alerts, existing_patterns = self._detect_patterns(
                        combined, "incremental_7day"
                    )
                    alerts_generated += existing_alerts
                    for k, v in existing_patterns.items():
                        patterns_detected[k] = patterns_detected.get(k, 0) + v

        return {
            "alerts_generated": alerts_generated,
            "patterns_detected": patterns_detected,
        }

    def forget_alerts_for_accounts(self, account_ids: List[str], date: Optional[str] = None) -> None:
        """Discard any cached alert_ids for these accounts (across all known pattern
        types, for the given date — defaults to today) from the in-process dedup set
        populated by _record_new_alerts.

        alert_id is a deterministic hash of (account_id, pattern, date), so re-firing
        the same underlying detection on the same calendar day normally gets
        suppressed as "already raised" — which is correct for a single ingestion
        run, but wrong for the real-time demo, which is meant to be re-run
        repeatably: after resetting an account's DB rows (see
        DatabaseAdapter.delete_by_account_prefix), its previously-raised alert_ids
        must also be forgotten here, or a second run would silently produce zero
        alerts for accounts that already fired once today.
        """
        date = date or datetime.now().strftime("%Y-%m-%d")
        all_patterns = (
            "structuring", "velocity_spike", "round_trip", "fan_out",
            "mule_suspect", "fan_in", "profile_mismatch",
        )
        for acc_id in account_ids:
            for pattern in all_patterns:
                self._raised_alert_ids.discard(_make_alert_id(str(acc_id), pattern, date))

    def _record_new_alerts(self, alert_list: List[Dict]) -> List[Dict]:
        """Upsert every alert in alert_list (so the DB row's risk_score/level always
        reflects the latest evidence), but return only the ones being raised for the
        first time this process.

        Each alert_id is deterministic per (account, pattern, date) — see
        _make_alert_id — so the same account re-qualifying for the same pattern on
        a later incremental call (e.g. a 4th near-threshold transaction after a 3rd
        already triggered structuring) produces the identical alert_id. Without this
        dedup, _run_incremental_analysis would report/publish that as a brand-new
        alert every time it re-fires, which both inflates alerts_generated/
        patterns_detected for a single underlying alert and — for the real-time
        stream — would emit a duplicate realtime.alert event for evidence that just
        strengthened an already-known alert rather than a genuinely new detection.
        """
        new_alerts = []
        for alert_info in alert_list:
            alert_id = alert_info.get("alert_id")
            # Tag distinctly from the full-pipeline path (AnalysisPipeline /
            # CaseManager) so it's always clear which detector produced a
            # given alert row, even though both write into the same table.
            alert_info.setdefault("source", "realtime_lightweight")
            self.db.upsert_alert(alert_info)
            if alert_id and alert_id not in self._raised_alert_ids:
                self._raised_alert_ids.add(alert_id)
                new_alerts.append(alert_info)
        return new_alerts

    def _detect_patterns(self, txns_df: pd.DataFrame, context: str) -> Tuple[int, Dict[str, int]]:
        """
        Run pattern detection on a batch of transactions.
        Returns (num_alerts, pattern_counts) — counting only newly-raised alerts,
        not re-fires of an alert already raised earlier in this process (see
        _record_new_alerts).
        """
        alerts = 0
        patterns: Dict[str, int] = {}

        try:
            detectors = (
                ("structuring", self._detect_structuring),
                ("velocity_spike", self._detect_velocity_spikes),
                ("round_trip", self._detect_round_trips),
                ("fan_out", self._detect_fan_out),
                ("mule_suspect", self._detect_mule_pattern),
                ("fan_in", self._detect_fan_in),
                ("profile_mismatch", self._detect_profile_mismatch),
            )
            for pattern_key, detector_fn in detectors:
                detected = detector_fn(txns_df)
                new_alerts = self._record_new_alerts(detected)
                if new_alerts:
                    patterns[pattern_key] = len(new_alerts)
                    alerts += len(new_alerts)

        except Exception as e:
            logger.error("Error in pattern detection (%s): %s", context, e)

        return alerts, patterns

    def _detect_structuring(self, txns_df: pd.DataFrame) -> List[Dict]:
        """Detect transactions structured just below reporting threshold (₹10L)."""
        CTR = 1_000_000  # ₹10 lakh
        LOWER = 900_000  # ₹9 lakh
        date = datetime.now().strftime("%Y-%m-%d")
        alerts = []
        # Group by source account and count near-threshold transactions
        for acc_id, group in txns_df.groupby("source_account"):
            near_threshold = group[(group["amount"] >= LOWER) & (group["amount"] < CTR)]
            if len(near_threshold) >= 3:
                alerts.append({
                    "alert_id": _make_alert_id(str(acc_id), "structuring", date),
                    "account_id": str(acc_id),
                    "risk_score": min(85.0, 50.0 + len(near_threshold) * 5),
                    "risk_level": "HIGH" if len(near_threshold) >= 5 else "MEDIUM",
                    "pattern_type": "structuring",
                    "status": "open",
                })
        return alerts

    def _detect_velocity_spikes(self, txns_df: pd.DataFrame) -> List[Dict]:
        """Detect accounts with abnormally high transaction frequency (rate-normalised)."""
        alerts = []
        date = datetime.now().strftime("%Y-%m-%d")
        ts_col = "timestamp" if "timestamp" in txns_df.columns else None
        for acc_id, group in txns_df.groupby("source_account"):
            if len(group) >= 20:
                if ts_col:
                    ts = pd.to_datetime(group[ts_col], errors="coerce").dropna()
                    if len(ts) >= 2:
                        span_hours = max(1.0, (ts.max() - ts.min()).total_seconds() / 3600)
                    else:
                        span_hours = 24.0
                    txn_rate = len(group) / span_hours
                    if txn_rate < 5:
                        continue
                alerts.append({
                    "alert_id": _make_alert_id(str(acc_id), "velocity_spike", date),
                    "account_id": str(acc_id),
                    "risk_score": min(90.0, 40.0 + len(group) * 2),
                    "risk_level": "HIGH" if len(group) >= 50 else "MEDIUM",
                    "pattern_type": "velocity_spike",
                    "status": "open",
                })
        return alerts

    def _detect_round_trips(self, txns_df: pd.DataFrame) -> List[Dict]:
        """Detect round-trip (money-returns-to-origin) patterns.

        Small batches (the real-time streaming path) get the stricter 2-3 hop
        return-ratio/time-window check. Large batches (full-day EOD files) fall
        back to the original, already-proven simple 2-hop reciprocal check to
        avoid alert-storming on dense daily transaction graphs — see
        _SMALL_BATCH_ROW_CAP.
        """
        if len(txns_df) > _SMALL_BATCH_ROW_CAP:
            return self._detect_round_trips_legacy(txns_df)
        return self._detect_round_trips_tight_loop(txns_df)

    def _detect_round_trips_legacy(self, txns_df: pd.DataFrame) -> List[Dict]:
        """Detect A->B->A round-trip patterns with 48-hour temporal constraint.
        No return-ratio requirement — original EOD incremental check, kept as the
        fallback for large batches."""
        alerts = []
        date = datetime.now().strftime("%Y-%m-%d")
        edge_times: dict = {}
        ts_col = "timestamp" if "timestamp" in txns_df.columns else None
        for _, row in txns_df.iterrows():
            src, dst = str(row["source_account"]), str(row["dest_account"])
            if ts_col:
                ts = pd.to_datetime(row[ts_col], errors="coerce")
                if pd.isna(ts):
                    ts = None
            else:
                ts = None
            key = (src, dst)
            if key not in edge_times or (ts is not None and edge_times[key] is not None and ts < edge_times[key]):
                edge_times[key] = ts

        flagged = set()
        for (src, dst), t1 in edge_times.items():
            if (dst, src) in edge_times and src not in flagged:
                t2 = edge_times[(dst, src)]
                if t1 is not None and t2 is not None:
                    time_diff_h = abs((t2 - t1).total_seconds()) / 3600
                    if time_diff_h > 48:
                        continue
                flagged.add(src)
                alerts.append({
                    "alert_id": _make_alert_id(src, "round_trip", date),
                    "account_id": src,
                    "risk_score": 70.0,
                    "risk_level": "HIGH",
                    "pattern_type": "round_trip",
                    "status": "open",
                })
        return alerts

    def _detect_round_trips_tight_loop(self, txns_df: pd.DataFrame) -> List[Dict]:
        """Detect A->B->A and A->B->C->A round-trip cycles: money returns to the
        origin account within the configured batch window at a high return ratio.

        This mirrors the "tight loop" signal from the real RoundTripDetector
        (services/detection/round_trip.py) — same config thresholds
        (round_trip_amount_return_ratio, round_trip_batch_window_hours) — but is
        scoped to cheap 2-3 hop lookups (dict joins over the incremental batch)
        instead of full Johnson's-algorithm cycle search, since this runs on every
        incremental ingest rather than as a batch job.
        """
        alerts = []
        date = datetime.now().strftime("%Y-%m-%d")
        window_hours = config.detection.round_trip_batch_window_hours
        ratio_threshold = config.detection.round_trip_amount_return_ratio

        ts_col = "timestamp" if "timestamp" in txns_df.columns else None
        df = txns_df.copy()
        if ts_col:
            df[ts_col] = pd.to_datetime(df[ts_col], errors="coerce")

        # Earliest (amount, timestamp) per (src, dst) edge in this batch
        edges: Dict[Tuple[str, str], Tuple[float, Any]] = {}
        for _, row in df.iterrows():
            key = (str(row["source_account"]), str(row["dest_account"]))
            amt = float(row.get("amount", 0))
            ts = row[ts_col] if ts_col else None
            ts = None if (ts is not None and pd.isna(ts)) else ts
            if key not in edges or (ts is not None and edges[key][1] is not None and ts < edges[key][1]):
                edges[key] = (amt, ts)

        flagged = set()

        def _try_flag(cycle_nodes: List[str], cycle_edges: List[Tuple[str, str]]):
            origin = cycle_nodes[0]
            if origin in flagged:
                return
            first_amt, _ = edges[cycle_edges[0]]
            last_amt, _ = edges[cycle_edges[-1]]
            if first_amt <= 0:
                return
            return_ratio = last_amt / first_amt
            if return_ratio < ratio_threshold:
                return
            timestamps = [edges[e][1] for e in cycle_edges if edges[e][1] is not None]
            if len(timestamps) >= 2:
                span_hours = (max(timestamps) - min(timestamps)).total_seconds() / 3600
                if span_hours > window_hours:
                    return
            flagged.add(origin)
            alerts.append({
                "alert_id": _make_alert_id(origin, "round_trip", date),
                "account_id": origin,
                "risk_score": round(min(95.0, 70.0 + return_ratio * 20), 1),
                "risk_level": "CRITICAL" if len(cycle_nodes) >= 3 else "HIGH",
                "pattern_type": "round_trip",
                "status": "open",
            })

        def _earliest_ts(edge: Tuple[str, str]) -> Any:
            ts = edges[edge][1]
            return ts if ts is not None else pd.Timestamp.max

        edge_keys = list(edges.keys())

        # 2-hop: A -> B -> A. A reciprocal pair is discoverable from both (a,b) and
        # (b,a) — dedupe by the unordered pair and pick whichever direction's edge
        # fired first as the canonical "origin" (the actual start of the loop),
        # rather than flagging both A and B for the same physical round-trip.
        seen_2hop = set()
        for (a, b) in edge_keys:
            if (b, a) not in edges:
                continue
            pair_key = frozenset((a, b))
            if pair_key in seen_2hop:
                continue
            seen_2hop.add(pair_key)
            rotations = [([a, b], [(a, b), (b, a)]), ([b, a], [(b, a), (a, b)])]
            best_nodes, best_edges = min(rotations, key=lambda r: _earliest_ts(r[1][0]))
            _try_flag(best_nodes, best_edges)

        # 3-hop: A -> B -> C -> A. Same cycle is discoverable from any of its 3
        # nodes — dedupe by node-set and pick the rotation starting at whichever
        # hop fired first chronologically.
        by_src: Dict[str, List[str]] = {}
        for (s, d) in edge_keys:
            by_src.setdefault(s, []).append(d)
        seen_3hop = set()
        for (a, b) in edge_keys:
            for c in by_src.get(b, []):
                if c == a:
                    continue
                if (c, a) not in edges:
                    continue
                cycle_key = frozenset((a, b, c))
                if cycle_key in seen_3hop:
                    continue
                seen_3hop.add(cycle_key)
                rotations = [
                    ([a, b, c], [(a, b), (b, c), (c, a)]),
                    ([b, c, a], [(b, c), (c, a), (a, b)]),
                    ([c, a, b], [(c, a), (a, b), (b, c)]),
                ]
                best_nodes, best_edges = min(rotations, key=lambda r: _earliest_ts(r[1][0]))
                _try_flag(best_nodes, best_edges)

        return alerts

    def _detect_fan_in(self, txns_df: pd.DataFrame) -> List[Dict]:
        """Detect accounts receiving from many distinct senders (smurfing collection
        point) — mirrors FanOutFanInDetector's fan-in direction
        (services/detection/fan_out.py), using the same fan_out_min_degree threshold.
        Skipped on large batches — see _SMALL_BATCH_ROW_CAP."""
        if len(txns_df) > _SMALL_BATCH_ROW_CAP:
            return []
        alerts = []
        date = datetime.now().strftime("%Y-%m-%d")
        min_fan = config.detection.fan_out_min_degree
        src_counts = txns_df.groupby("dest_account")["source_account"].nunique()
        for acc_id, n_srcs in src_counts.items():
            if n_srcs >= min_fan:
                alerts.append({
                    "alert_id": _make_alert_id(str(acc_id), "fan_in", date),
                    "account_id": str(acc_id),
                    "risk_score": min(85.0, 50.0 + n_srcs * 5),
                    "risk_level": "HIGH" if n_srcs >= 5 else "MEDIUM",
                    "pattern_type": "fan_in",
                    "status": "open",
                })
        return alerts

    def _detect_profile_mismatch(self, txns_df: pd.DataFrame) -> List[Dict]:
        """Detect destination accounts receiving amounts wildly disproportionate to
        their declared income — a lightweight incremental analogue of
        ProfileMismatchDetector._detect_income_mismatch (services/detection/profile.py),
        reusing the same volume/income ratio rule (>10x). The full peer-cohort
        z-score variant (profile_mismatch_z_threshold) needs a batch of ≥5 same
        occupation/income-bracket accounts to compute a meaningful peer mean/std,
        which isn't available on a single incrementally-ingested row/account — the
        income-ratio check is the robust single-account signal for this context.
        Skipped on large batches — see _SMALL_BATCH_ROW_CAP."""
        if len(txns_df) > _SMALL_BATCH_ROW_CAP:
            return []
        alerts = []
        date = datetime.now().strftime("%Y-%m-%d")
        dst_amounts = txns_df.groupby("dest_account")["amount"].sum()
        for acc_id, amount in dst_amounts.items():
            acc = None
            try:
                acc = self.db.get_account(str(acc_id))
            except Exception as e:
                logger.warning("Profile lookup failed for %s: %s", acc_id, e)
            if not acc:
                continue
            declared = float(acc.get("declared_annual_income") or 0)
            if declared <= 0:
                continue
            ratio = amount / declared
            if ratio > 10:
                alerts.append({
                    "alert_id": _make_alert_id(str(acc_id), "profile_mismatch", date),
                    "account_id": str(acc_id),
                    "risk_score": round(min(95.0, 55.0 + min(ratio, 40)), 1),
                    "risk_level": "CRITICAL" if ratio > 50 else "HIGH" if ratio > 20 else "MEDIUM",
                    "pattern_type": "profile_mismatch",
                    "status": "open",
                })
        return alerts

    def _detect_fan_out(self, txns_df: pd.DataFrame) -> List[Dict]:
        """Detect accounts sending to many recipients (potential layering)."""
        date = datetime.now().strftime("%Y-%m-%d")
        alerts = []
        dest_counts = txns_df.groupby("source_account")["dest_account"].nunique()
        for acc_id, n_dests in dest_counts.items():
            if n_dests >= 10:  # Sending to 10+ unique accounts
                alerts.append({
                    "alert_id": _make_alert_id(str(acc_id), "fan_out", date),
                    "account_id": str(acc_id),
                    "risk_score": min(80.0, 45.0 + n_dests * 3),
                    "risk_level": "HIGH" if n_dests >= 20 else "MEDIUM",
                    "pattern_type": "fan_out",
                    "status": "open",
                })
        return alerts

    def _detect_mule_pattern(self, txns_df: pd.DataFrame) -> List[Dict]:
        """Detect mule behavior: receive money and quickly forward most of it."""
        date = datetime.now().strftime("%Y-%m-%d")
        alerts = []
        txns_df = txns_df.copy()
        if "timestamp" in txns_df.columns:
            txns_df["timestamp"] = pd.to_datetime(txns_df["timestamp"], errors="coerce")

        # For each account: compare inflows vs outflows
        in_flow = txns_df.groupby("dest_account")["amount"].sum()
        out_flow = txns_df.groupby("source_account")["amount"].sum()

        for acc_id in set(in_flow.index) & set(out_flow.index):
            total_in = in_flow.get(acc_id, 0)
            total_out = out_flow.get(acc_id, 0)
            if total_in > 100000 and total_out > 0:  # Minimum ₹1L inflow
                pass_through_ratio = total_out / total_in
                if pass_through_ratio >= 0.8:  # Passes through 80%+ of received funds
                    alerts.append({
                        "alert_id": _make_alert_id(str(acc_id), "mule_suspect", date),
                        "account_id": str(acc_id),
                        "risk_score": min(95.0, 60.0 + pass_through_ratio * 30),
                        "risk_level": "CRITICAL" if pass_through_ratio >= 0.95 else "HIGH",
                        "pattern_type": "mule_suspect",
                        "status": "open",
                    })
        return alerts

    def get_ingestion_status(self) -> Dict[str, Any]:
        """Get current ingestion status and statistics."""
        history = self.db.get_ingestion_history(limit=10)
        return {
            "db_backend": DB_BACKEND if (DB_BACKEND == "neo4j" and NEO4J_URI) else "sqlite",
            "total_accounts_in_db": self.db.get_account_count(),
            "total_transactions_in_db": self.db.get_transaction_count(),
            "recent_ingestions": history,
        }
