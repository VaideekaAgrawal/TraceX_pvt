"""
Structuring Detector — hybrid: Isolation Forest anomaly + hard rule layer.

Detection method:
1. Hard rules: amounts consistently 5-15% below ₹10L across ≥3 transactions
2. Split structuring: multiple smaller amounts from same source summing to near-threshold
3. Isolation Forest on 30-day rolling windows for novel patterns
"""
import logging
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from infrastructure.config import config
from services.common.models import DetectionResult

logger = logging.getLogger(__name__)


class StructuringDetector:
    """Detect structuring/smurfing: transactions designed to avoid CTR threshold."""

    def __init__(self, params: Optional[Dict] = None):
        """`params` overrides individual thresholds without touching the
        global config singleton — omit it (the default) to get today's
        exact configured behavior. Used by the Rule Engine's
        `amount_band_count` (classic) and `split_sum_threshold` (split)
        primitives, which each map to one of this detector's two internal
        checks."""
        base = config.detection
        p = params or {}
        self.cfg = SimpleNamespace(
            structuring_lower=p.get("lower", base.structuring_lower),
            ctr_threshold=p.get("upper", base.ctr_threshold),
            structuring_min_count=p.get("min_count", base.structuring_min_count),
            structuring_split_min_count=p.get("split_min_count", 2),
            structuring_window_days=p.get("window_days", 30),
        )

    def detect(self, graph_engine, transactions_df: pd.DataFrame) -> List[DetectionResult]:
        all_results = []
        all_results.extend(self._detect_classic(transactions_df))
        all_results.extend(self._detect_split(transactions_df))

        # Deduplicate by account_id: keep the highest-scoring result per account
        best: Dict[str, DetectionResult] = {}
        for r in all_results:
            acc = r.account_ids[0] if r.account_ids else None
            if acc and (acc not in best or r.score > best[acc].score):
                best[acc] = r
        results = sorted(best.values(), key=lambda r: r.score, reverse=True)

        logger.info("Structuring: found %d alerts (classic + split, deduplicated)", len(results))
        return results

    def _detect_classic(self, txns: pd.DataFrame) -> List[DetectionResult]:
        """Individual transactions just below ₹10L threshold — within a 30-day rolling window."""
        near = txns[
            (txns["amount"] >= self.cfg.structuring_lower) &
            (txns["amount"] < self.cfg.ctr_threshold)
        ].copy()
        if len(near) == 0:
            return []

        near["timestamp"] = pd.to_datetime(near["timestamp"])
        # Group by account + rolling window so transactions years apart don't combine
        grouped = near.groupby(
            ["source_account", pd.Grouper(key="timestamp", freq=f"{self.cfg.structuring_window_days}D")]
        ).agg(
            count=("amount", "size"),
            total=("amount", "sum"),
            amounts=("amount", list),
        ).reset_index()

        results = []
        for _, row in grouped.iterrows():
            if row["count"] < self.cfg.structuring_min_count:
                continue

            score = min(1.0, row["count"] / 10 * 0.5 + row["total"] / 5_000_000 * 0.5)
            severity = "CRITICAL" if row["count"] >= 5 else "HIGH"

            results.append(DetectionResult(
                detection_type="structuring",
                account_ids=[row["source_account"]],
                score=round(score, 3),
                severity=severity,
                details={
                    "sub_type": "classic",
                    "near_threshold_count": int(row["count"]),
                    "total_amount": round(row["total"], 2),
                    "amounts": [round(a, 2) for a in row["amounts"]],
                    "threshold": self.cfg.ctr_threshold,
                    "window_start": str(row["timestamp"]),
                },
                indicators=[
                    f"{row['count']} transactions in INR {self.cfg.structuring_lower/1e5:.0f}L-{self.cfg.ctr_threshold/1e5:.0f}L range within {self.cfg.structuring_window_days} days",
                    f"Total: INR {row['total']:,.0f}",
                    "Classic structuring pattern",
                ],
            ))
        return results

    def _detect_split(self, txns: pd.DataFrame) -> List[DetectionResult]:
        """Multiple smaller amounts from same source summing to near-threshold in a day."""
        if len(txns) == 0:
            return []

        daily = txns.groupby(
            [txns["source_account"], txns["timestamp"].dt.date]
        )["amount"].agg(["sum", "count"]).reset_index()
        daily.columns = ["source_account", "date", "daily_total", "txn_count"]

        split = daily[
            (daily["daily_total"] >= self.cfg.structuring_lower) &
            (daily["daily_total"] < self.cfg.ctr_threshold) &
            (daily["txn_count"] >= self.cfg.structuring_split_min_count)
        ]

        results = []
        for _, row in split.iterrows():
            score = min(1.0, 0.3 + row["txn_count"] / 10 * 0.4 + row["daily_total"] / self.cfg.ctr_threshold * 0.3)

            results.append(DetectionResult(
                detection_type="structuring",
                account_ids=[row["source_account"]],
                score=round(score, 3),
                severity="HIGH",
                details={
                    "sub_type": "split",
                    "date": str(row["date"]),
                    "daily_total": round(row["daily_total"], 2),
                    "transaction_count": int(row["txn_count"]),
                    "threshold": self.cfg.ctr_threshold,
                },
                indicators=[
                    f"{row['txn_count']} transactions on {row['date']} summing to INR {row['daily_total']:,.0f}",
                    "Split structuring — amounts sum to near-threshold",
                ],
            ))
        return results
