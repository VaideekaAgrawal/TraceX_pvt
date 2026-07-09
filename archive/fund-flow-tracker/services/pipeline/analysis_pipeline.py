"""
Analysis Pipeline — the single place that owns the "ingest → persist →
build graph → detect → create alerts" workflow.

Before this existed, every route that loaded data (/api/init, /api/upload,
/api/refresh, the startup rebuild hook, the EOD ingest routes) duplicated
this sequence inline. That made it easy for one copy to drift from another
(e.g. one persisting to DB and another not) and meant the same detect →
create-alerts orchestration logic lived in the API layer instead of a
service. Every one of those call sites should now call `run()` or
`run_from_db()` instead of re-implementing the sequence.
"""
import logging
from datetime import datetime
from typing import Any, Dict, Optional

import pandas as pd

from infrastructure.database import get_database

logger = logging.getLogger(__name__)


class AnalysisPipeline:
    """Wires IngestionService, GraphService, DetectionService and
    InvestigationService into one reusable pipeline."""

    def __init__(self, ingestion_svc, graph_svc, detection_svc, investigation_svc):
        self.ingestion_svc = ingestion_svc
        self.graph_svc = graph_svc
        self.detection_svc = detection_svc
        self.investigation_svc = investigation_svc

    def run(self, accounts_df: pd.DataFrame, transactions_df: pd.DataFrame,
            persist: bool = True, ingestion_date: Optional[str] = None) -> Dict[str, Any]:
        """Run the full pipeline over the given data: optionally persist it,
        then build the graph, run detection, and create/refresh alerts.
        Returns {pipeline_summary, alert_diff}."""
        if persist:
            self.ingestion_svc.persist_to_db(accounts_df, transactions_df, ingestion_date=ingestion_date)

        self.graph_svc.build(accounts_df, transactions_df)
        pipeline_summary = self.detection_svc.run_full_pipeline(self.graph_svc, accounts_df, transactions_df)
        alert_diff = self.investigation_svc.create_alerts_from_detections(self.detection_svc.detection_results)
        self._record_daily_run_summary(accounts_df, transactions_df, pipeline_summary, alert_diff)

        return {
            "accounts_df": accounts_df,
            "transactions_df": transactions_df,
            "pipeline_summary": pipeline_summary,
            "alert_diff": alert_diff,
        }

    @staticmethod
    def _record_daily_run_summary(accounts_df: pd.DataFrame, transactions_df: pd.DataFrame,
                                   pipeline_summary: Dict[str, Any], alert_diff: Dict[str, Any]) -> None:
        """One row per calendar day distinguishing accounts/alerts flagged
        for the first time today from ones still active, seen again — the
        basis for the dashboard's "Today's Activity" panel."""
        today = datetime.now().strftime("%Y-%m-%d")
        flagged_accounts = {
            acc_id for alert in alert_diff.get("alerts", []) for acc_id in alert.account_ids
        }
        try:
            get_database().record_daily_run_summary({
                "run_date": today,
                "run_at": datetime.now().isoformat(),
                "new_alert_ids": alert_diff.get("new_ids", []),
                "reactivated_alert_ids": alert_diff.get("reactivated_ids", []),
                "stale_alert_ids": alert_diff.get("stale_ids", []),
                "total_accounts_flagged": len(flagged_accounts),
                "total_alerts_open": len(alert_diff.get("alerts", [])),
                "accounts_ingested": len(accounts_df),
                "transactions_ingested": len(transactions_df),
                "pipeline_summary": pipeline_summary,
            })
        except Exception:
            logger.exception("Failed to record daily run summary (non-fatal)")

    def run_from_db(self) -> Dict[str, Any]:
        """Reload accounts/transactions from the DB and run the pipeline
        over them (no re-persist needed — they're already there). Used by
        /api/refresh, the startup rebuild hook, and EOD ingest routes."""
        accounts_df, transactions_df = self.ingestion_svc.load_from_db()
        return self.run(accounts_df, transactions_df, persist=False)
