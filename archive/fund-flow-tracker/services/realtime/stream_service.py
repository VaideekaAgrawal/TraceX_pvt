"""
Realtime Stream Service — replays a small demo CSV one transaction at a time,
feeding each row through the *real* incremental detection pipeline
(EODIngestionService.ingest_transaction_rows) with a short delay between rows.

This is not a canned replay of pre-computed alerts: every alert published on
REALTIME_ALERT is the live output of genuine pattern detection running against
whatever has actually been persisted to the database so far.
"""
import asyncio
import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional

import pandas as pd

from infrastructure.event_bus import bus, Topics

logger = logging.getLogger(__name__)

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEMO_CSV_PATH = os.path.join(_PROJECT_ROOT, "data", "tracex_realtime_demo.csv")

ROW_DELAY_SEC = 1.2
RESET_PREFIX = "RTD"


class AlreadyRunningError(Exception):
    """Raised by start() when a stream is already in progress."""


class RealtimeStreamService:
    """Streams the real-time demo CSV through the real ingestion/detection pipeline."""

    def __init__(self):
        self.demo_df: pd.DataFrame = self._load_demo_csv()
        self._running: bool = False
        self._processed: int = 0
        self._total: int = len(self.demo_df)
        self._task: Optional[asyncio.Task] = None

    @staticmethod
    def _load_demo_csv() -> pd.DataFrame:
        try:
            df = pd.read_csv(DEMO_CSV_PATH)
            df["_ts_sort"] = pd.to_datetime(df["Timestamp"], errors="coerce")
            df = df.sort_values("_ts_sort").drop(columns=["_ts_sort"]).reset_index(drop=True)
            return df
        except Exception as e:
            logger.error("Could not load realtime demo CSV at %s: %s", DEMO_CSV_PATH, e)
            return pd.DataFrame()

    def start(self, eod_svc) -> None:
        """Start streaming the demo CSV. Raises AlreadyRunningError if a stream
        is already in progress (caller should turn this into an HTTP 409)."""
        if self._running:
            raise AlreadyRunningError("Realtime stream is already running")
        if self.demo_df.empty:
            self.demo_df = self._load_demo_csv()
        self._reset_demo_data(eod_svc)
        self._processed = 0
        self._total = len(self.demo_df)
        self._running = True
        self._task = asyncio.create_task(self._run(eod_svc))

    def _reset_demo_data(self, eod_svc) -> None:
        """Make the demo repeatable: wipe any RTD-prefixed transactions/accounts/
        alerts left over from a previous run, and forget their alert_ids from
        eod_svc's in-process dedup cache (see EODIngestionService._raised_alert_ids)
        so this run's genuine detections aren't suppressed as "already raised
        today". Without this, back-to-back runs on the same calendar day
        accumulate DB rows across runs — inflating transaction counts enough to
        trip unrelated detectors (e.g. velocity_spike) and, independently,
        suppressing the real 4 alerts because their deterministic alert_ids were
        already raised by the prior run.
        """
        try:
            demo_accounts = sorted(set(self.demo_df.get("Account", pd.Series(dtype=str))) |
                                    set(self.demo_df.get("Account.1", pd.Series(dtype=str))))
            deleted = eod_svc.db.delete_by_account_prefix(RESET_PREFIX)
            eod_svc.forget_alerts_for_accounts(demo_accounts)
            logger.info("Realtime demo self-reset: %s (forgot %d cached alert_ids scope)",
                        deleted, len(demo_accounts))
        except Exception as e:
            logger.error("Realtime demo self-reset failed (continuing anyway): %s", e, exc_info=True)

    async def _run(self, eod_svc) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        try:
            for _, row in self.demo_df.iterrows():
                await asyncio.sleep(ROW_DELAY_SEC)

                row_df = pd.DataFrame([row.to_dict()])
                try:
                    result = eod_svc.ingest_transaction_rows(row_df, date=today)
                except Exception as e:
                    logger.error("Realtime ingest failed for row %s: %s", row.get("Account"), e)
                    result = {"alerts_generated": 0, "patterns_detected": {}}

                self._processed += 1

                txn_payload: Dict[str, Any] = {
                    "timestamp": str(row.get("Timestamp", "")),
                    "source_account": str(row.get("Account", "")),
                    "dest_account": str(row.get("Account.1", "")),
                    "amount": float(row.get("Amount Paid", 0) or 0),
                    "payment_format": str(row.get("Payment Format", "")),
                    "new_accounts": result.get("new_accounts", 0),
                    "alerts_generated": result.get("alerts_generated", 0),
                    "processed": self._processed,
                    "total": self._total,
                }
                bus.publish(Topics.REALTIME_TRANSACTION, txn_payload, source_service="realtime")

                if result.get("alerts_generated", 0) > 0:
                    for pattern_type, count in result.get("patterns_detected", {}).items():
                        alert_payload: Dict[str, Any] = {
                            "pattern_type": pattern_type,
                            "count": count,
                            "source_account": str(row.get("Account", "")),
                            "dest_account": str(row.get("Account.1", "")),
                            "amount": float(row.get("Amount Paid", 0) or 0),
                            "timestamp": str(row.get("Timestamp", "")),
                            "processed": self._processed,
                            "total": self._total,
                        }
                        bus.publish(Topics.REALTIME_ALERT, alert_payload, source_service="realtime")

            bus.publish(Topics.REALTIME_DONE, {"processed": self._processed}, source_service="realtime")
        except Exception as e:
            logger.error("Realtime stream failed: %s", e, exc_info=True)
            bus.publish(Topics.REALTIME_DONE, {"processed": self._processed, "error": str(e)},
                        source_service="realtime")
        finally:
            self._running = False

    def status(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "processed": self._processed,
            "total": self._total,
        }
