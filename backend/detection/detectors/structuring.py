"""
Structuring Detector — hard-rule detection of transactions designed to
avoid the CTR reporting threshold.

Ported unchanged from `archive/fund-flow-tracker/services/detection/
structuring.py`:
1. Classic: individual transactions just below the CTR threshold, >= a
   minimum count within a rolling window.
2. Split: multiple smaller amounts from the same source summing to near-
   threshold in a single day.

(The archive's module docstring also claims an Isolation Forest pass over
30-day windows; the actual code only ever implements `_detect_classic` +
`_detect_split` — ported as the archive's real behavior, not its docstring.)
"""
from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import pandas as pd

from detection.config import DEFAULT_DETECTION_CONFIG, DetectionConfig
from detection.graph.store import GraphStore
from detection.types import DetectionResult

logger = logging.getLogger(__name__)


class StructuringDetector:
    """Detect structuring/smurfing: transactions designed to avoid the CTR threshold."""

    def __init__(
        self,
        params: dict[str, Any] | None = None,
        config: DetectionConfig | None = None,
    ):
        """`params` overrides individual thresholds without touching the
        shared default config -- omit it to get today's exact configured
        behavior. Used by the Rule Engine's `amount_band_count` (classic)
        and `split_sum_threshold` (split) primitives, which each map to one
        of this detector's two internal checks."""
        base = config or DEFAULT_DETECTION_CONFIG
        p = params or {}
        self.cfg = SimpleNamespace(
            structuring_lower=p.get("lower", base.structuring_lower),
            ctr_threshold=p.get("upper", base.ctr_threshold),
            structuring_min_count=p.get("min_count", base.structuring_min_count),
            structuring_split_min_count=p.get("split_min_count", 2),
            structuring_window_days=p.get("window_days", 30),
        )

    def detect(
        self, graph_store: GraphStore, transactions_df: pd.DataFrame
    ) -> list[DetectionResult]:
        all_results = []
        all_results.extend(self._detect_classic(transactions_df))
        all_results.extend(self._detect_split(transactions_df))

        best: dict[str, DetectionResult] = {}
        for r in all_results:
            acc = r.account_ids[0] if r.account_ids else None
            if acc and (acc not in best or r.score > best[acc].score):
                best[acc] = r
        results = sorted(best.values(), key=lambda r: r.score, reverse=True)

        logger.info("Structuring: found %d alerts (classic + split, deduplicated)", len(results))
        return results

    def _detect_classic(self, txns: pd.DataFrame) -> list[DetectionResult]:
        """Individual transactions just below the CTR threshold — within a
        rolling window."""
        near = txns[
            (txns["amount"] >= self.cfg.structuring_lower)
            & (txns["amount"] < self.cfg.ctr_threshold)
        ].copy()
        if len(near) == 0:
            return []

        near["timestamp"] = pd.to_datetime(near["timestamp"])
        window_freq = f"{self.cfg.structuring_window_days}D"
        grouped = near.groupby(
            ["source_account", pd.Grouper(key="timestamp", freq=window_freq)]
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
                    f"{row['count']} transactions in "
                    f"{self.cfg.structuring_lower / 1e5:.0f}L-{self.cfg.ctr_threshold / 1e5:.0f}L "
                    f"range within {self.cfg.structuring_window_days} days",
                    f"Total: {row['total']:,.0f}",
                    "Classic structuring pattern",
                ],
            ))
        return results

    def _detect_split(self, txns: pd.DataFrame) -> list[DetectionResult]:
        """Multiple smaller amounts from the same source summing to
        near-threshold in a day."""
        if len(txns) == 0:
            return []

        daily = txns.groupby(
            [txns["source_account"], txns["timestamp"].dt.date]
        )["amount"].agg(["sum", "count"]).reset_index()
        daily.columns = ["source_account", "date", "daily_total", "txn_count"]

        split = daily[
            (daily["daily_total"] >= self.cfg.structuring_lower)
            & (daily["daily_total"] < self.cfg.ctr_threshold)
            & (daily["txn_count"] >= self.cfg.structuring_split_min_count)
        ]

        results = []
        for _, row in split.iterrows():
            count_term = row["txn_count"] / 10 * 0.4
            amount_term = row["daily_total"] / self.cfg.ctr_threshold * 0.3
            score = min(1.0, 0.3 + count_term + amount_term)

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
                    f"{row['txn_count']} transactions on {row['date']} summing to "
                    f"{row['daily_total']:,.0f}",
                    "Split structuring — amounts sum to near-threshold",
                ],
            ))
        return results
