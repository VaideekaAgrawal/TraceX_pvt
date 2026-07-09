"""
Dormancy Detector — rule-based, scored: account inactive for a threshold
number of days, followed by a burst of transactions well above its
historical average.

Ported unchanged (vectorised via pandas groupby, no Python account loop)
from `archive/fund-flow-tracker/services/detection/dormancy.py`.
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


class DormancyDetector:
    """Detect dormant accounts that suddenly become active with high-value transactions."""

    def __init__(
        self,
        params: dict[str, Any] | None = None,
        config: DetectionConfig | None = None,
    ):
        """`params` (used by the Rule Engine's `inactivity_then_burst`
        primitive) overrides individual thresholds without touching the
        shared default config -- omit it to get today's exact configured
        behavior."""
        base = config or DEFAULT_DETECTION_CONFIG
        p = params or {}
        self.cfg = SimpleNamespace(
            dormancy_threshold_days=p.get("threshold_days", base.dormancy_threshold_days),
            dormancy_burst_min_txns=p.get("min_burst_txns", base.dormancy_burst_min_txns),
            dormancy_multiplier=p.get("multiplier", base.dormancy_multiplier),
        )

    def detect(
        self, graph_store: GraphStore, transactions_df: pd.DataFrame
    ) -> list[DetectionResult]:
        """Vectorised dormancy detection using pandas groupby -- no Python
        account loop."""
        src = transactions_df[["source_account", "timestamp", "amount"]].rename(
            columns={"source_account": "account_id"}
        )
        dst = transactions_df[["dest_account", "timestamp", "amount"]].rename(
            columns={"dest_account": "account_id"}
        )
        acc_txns = pd.concat([src, dst], ignore_index=True)
        acc_txns = acc_txns.sort_values(["account_id", "timestamp"]).reset_index(drop=True)

        min_txns = self.cfg.dormancy_burst_min_txns + 1
        threshold_days = self.cfg.dormancy_threshold_days

        grp = acc_txns.groupby("account_id")
        counts = grp.size()
        valid_accounts = counts[counts >= min_txns].index
        acc_txns = acc_txns[acc_txns["account_id"].isin(valid_accounts)]

        acc_txns = acc_txns.sort_values(["account_id", "timestamp"]).reset_index(drop=True)
        acc_txns["prev_ts"] = acc_txns.groupby("account_id")["timestamp"].shift(1)
        gap_seconds = (acc_txns["timestamp"] - acc_txns["prev_ts"]).dt.total_seconds()
        acc_txns["gap_days"] = gap_seconds / 86400.0
        acc_txns["gap_days"] = acc_txns["gap_days"].fillna(0)

        idx_max_gap = acc_txns.groupby("account_id")["gap_days"].idxmax()
        gap_rows = acc_txns.loc[idx_max_gap, ["account_id", "gap_days", "timestamp"]].copy()
        gap_rows = gap_rows[gap_rows["gap_days"] >= threshold_days]

        if gap_rows.empty:
            logger.info("Dormancy: found 0 activations")
            return []

        gap_rows = gap_rows.rename(columns={"timestamp": "burst_start_ts"})

        acc_txns["_row"] = acc_txns.groupby("account_id").cumcount()
        gap_rows["_max_gap_row"] = acc_txns.loc[gap_rows.index, "_row"].values

        results = []
        for _, row in gap_rows.iterrows():
            account_id = row["account_id"]
            split_row = int(row["_max_gap_row"])
            max_gap_days = float(row["gap_days"])
            burst_start = row["burst_start_ts"]

            sub = acc_txns[acc_txns["account_id"] == account_id]
            pre = sub[sub["_row"] < split_row]["amount"]
            post = sub[sub["_row"] >= split_row]["amount"]

            if len(post) < self.cfg.dormancy_burst_min_txns:
                continue

            pre_avg = pre.mean() if len(pre) > 0 else 0
            if pre_avg == 0 and len(pre) < 2:
                continue
            post_avg = post.mean()
            if pre_avg > 0:
                burst_multiplier = post_avg / pre_avg
            else:
                burst_multiplier = self.cfg.dormancy_multiplier + 1

            if burst_multiplier < self.cfg.dormancy_multiplier:
                continue

            post_ts = sub[sub["_row"] >= split_row]["timestamp"]
            burst_days = (post_ts.max() - post_ts.min()).total_seconds() / 86400

            score = min(
                1.0,
                min(max_gap_days / 365, 0.3)
                + min(burst_multiplier / 50, 0.4)
                + min(post.sum() / 5_000_000, 0.3),
            )

            severity = (
                "CRITICAL" if max_gap_days > 365 and burst_multiplier > 20
                else "HIGH" if max_gap_days > 180
                else "MEDIUM"
            )

            results.append(DetectionResult(
                detection_type="dormancy",
                account_ids=[account_id],
                score=round(score, 3),
                severity=severity,
                details={
                    "dormancy_days": round(max_gap_days, 1),
                    "dormancy_end": str(burst_start),
                    "pre_dormancy_avg_amount": round(pre_avg, 2),
                    "post_dormancy_avg_amount": round(post_avg, 2),
                    "burst_multiplier": round(burst_multiplier, 1),
                    "burst_txn_count": len(post),
                    "burst_total_amount": round(post.sum(), 2),
                    "burst_span_days": round(burst_days, 1),
                },
                indicators=[
                    f"Dormant for {max_gap_days:.0f} days",
                    f"Burst: {len(post)} txns, {burst_multiplier:.0f}x historical average",
                    f"Post-dormancy total: {post.sum():,.0f}",
                ],
            ))

        results.sort(key=lambda r: r.score, reverse=True)
        logger.info("Dormancy: found %d activations", len(results))
        return results
