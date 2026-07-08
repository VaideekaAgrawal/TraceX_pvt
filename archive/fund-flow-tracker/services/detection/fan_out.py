"""
Fan-Out / Fan-In Detector — detects hub-and-spoke AML patterns.

Covers IBM AML pattern types:
  FAN-OUT:        1 source → N unique destinations in a time window
  FAN-IN:         N unique sources → 1 destination in a time window
  GATHER-SCATTER: many sources → hub → many destinations (hub flagged via both)
  SCATTER-GATHER: 1 source → N intermediaries → 1 destination

Detection method:
  For each account, slide a W-day window and count unique counterparties.
  Flag if max window unique-counterparties ≥ threshold.
"""
import logging
from types import SimpleNamespace
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from infrastructure.config import config
from services.common.models import DetectionResult

logger = logging.getLogger(__name__)


class FanOutFanInDetector:
    """Detect high-fan-degree AML patterns: fan-out, fan-in, gather-scatter."""

    def __init__(self, params: Optional[Dict] = None):
        """`params` overrides individual thresholds without touching the
        global config singleton — omit it (the default) to get today's
        exact configured behavior. Used by the Rule Engine's `fan_degree`
        and `bipartite_scatter_gather` primitives, which each map to one of
        this detector's internal checks."""
        base = config.detection
        p = params or {}
        self.cfg = SimpleNamespace(
            fan_out_min_degree=p.get("min_degree", base.fan_out_min_degree),
            fan_out_time_window_days=p.get("window_days", base.fan_out_time_window_days),
            bipartite_min_side=p.get("min_side", 3),
        )

    def detect(self, graph_engine, transactions_df: pd.DataFrame) -> List[DetectionResult]:
        df = transactions_df.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp").reset_index(drop=True)

        min_fan = self.cfg.fan_out_min_degree
        window_ns = int(self.cfg.fan_out_time_window_days * 86_400 * 1e9)  # nanoseconds

        fan_out_results = self._detect_fan(
            df, group_col="source_account", target_col="dest_account",
            min_fan=min_fan, window_ns=window_ns, direction="fan_out",
        )
        fan_in_results = self._detect_fan(
            df, group_col="dest_account", target_col="source_account",
            min_fan=min_fan, window_ns=window_ns, direction="fan_in",
        )
        bipartite_results = self._detect_bipartite(df, min_side=self.cfg.bipartite_min_side, window_ns=window_ns)

        results = fan_out_results + fan_in_results + bipartite_results
        results.sort(key=lambda r: r.score, reverse=True)
        logger.info("FanOut/FanIn: %d fan-out + %d fan-in + %d bipartite = %d total",
                    len(fan_out_results), len(fan_in_results), len(bipartite_results), len(results))
        return results

    def _detect_bipartite(
        self,
        df: pd.DataFrame,
        min_side: int,
        window_ns: int,
    ) -> List[DetectionResult]:
        """Detect BIPARTITE patterns: M sources × N destinations, densely cross-connected.

        A bipartite AML structure (IBM pattern type BIPARTITE) is characterised by:
        - A group of source accounts (left side, |L| ≥ min_side)
        - A group of destination accounts (right side, |R| ≥ min_side)
        - Each account in L sends to ≥2 accounts in R
        - Each account in R receives from ≥2 accounts in L

        Detection heuristic: find pairs of destination accounts that share ≥min_side common
        senders within the time window. The shared-sender group and its shared destinations
        form the bipartite structure.
        """
        results = []
        window_days = self.cfg.fan_out_time_window_days

        ts_ns = df["timestamp"].values.astype(np.int64)
        src_arr = df["source_account"].values
        dst_arr = df["dest_account"].values

        # Build destination → set of senders mapping within sliding windows
        dst_to_senders: dict = {}
        for i in range(len(ts_ns)):
            in_win = (ts_ns >= ts_ns[i]) & (ts_ns <= ts_ns[i] + window_ns)
            d = dst_arr[i]
            senders_in_win = set(src_arr[in_win & (dst_arr == d)])
            if len(senders_in_win) >= min_side:
                if d not in dst_to_senders or len(senders_in_win) > len(dst_to_senders[d]):
                    dst_to_senders[d] = senders_in_win

        if len(dst_to_senders) < 2:
            return results

        # Find pairs of destinations that share ≥min_side common senders → bipartite structure
        dst_list = list(dst_to_senders.items())
        seen_clusters: set = set()

        for i in range(len(dst_list)):
            d1, s1 = dst_list[i]
            for j in range(i + 1, len(dst_list)):
                d2, s2 = dst_list[j]
                shared = s1 & s2
                if len(shared) < min_side:
                    continue

                cluster_key = frozenset(shared | {d1, d2})
                if cluster_key in seen_clusters:
                    continue
                seen_clusters.add(cluster_key)

                # Expand: all destinations that these shared senders also target
                right_side = {d for d, senders in dst_to_senders.items()
                              if len(shared & senders) >= 2}
                if len(right_side) < 2:
                    continue

                all_accs = list(shared) + list(right_side)
                bipartite_df = df[df["source_account"].isin(shared) & df["dest_account"].isin(right_side)]
                total_amount = float(bipartite_df["amount"].sum())

                score = round(min(
                    min(len(shared) / 8, 0.4) +
                    min(len(right_side) / 8, 0.3) +
                    min(total_amount / 5_000_000, 0.3),
                    1.0,
                ), 3)

                severity = ("CRITICAL" if len(shared) >= 5 and len(right_side) >= 5 else
                            "HIGH" if len(shared) >= 3 and len(right_side) >= 3 else "MEDIUM")

                results.append(DetectionResult(
                    detection_type="fan_out",
                    account_ids=all_accs[:50],
                    score=score,
                    severity=severity,
                    details={
                        "sub_type": "bipartite",
                        "left_size": len(shared),
                        "right_size": len(right_side),
                        "left_accounts": list(shared)[:20],
                        "right_accounts": list(right_side)[:20],
                        "total_amount": round(total_amount, 2),
                    },
                    indicators=[
                        f"Bipartite: {len(shared)} sources × {len(right_side)} destinations",
                        f"Total flow: {total_amount:,.0f}",
                    ],
                ))

        return results

    def _detect_fan(
        self,
        df: pd.DataFrame,
        group_col: str,
        target_col: str,
        min_fan: int,
        window_ns: int,
        direction: str,
    ) -> List[DetectionResult]:
        results = []
        window_days = self.cfg.fan_out_time_window_days

        # Pre-filter: only accounts with enough unique counterparties globally
        unique_per_acc = df.groupby(group_col)[target_col].nunique()
        candidates = unique_per_acc[unique_per_acc >= min_fan].index

        for account_id in candidates:
            group = df[df[group_col] == account_id].sort_values("timestamp")
            if len(group) < min_fan:
                continue

            ts_ns = group["timestamp"].values.astype(np.int64)
            targets = group[target_col].values
            amounts = group["amount"].values

            # Sliding window: for each txn as window start, count unique targets
            max_unique = 0
            best_mask = None
            for i in range(len(ts_ns)):
                window_end = ts_ns[i] + window_ns
                in_win = (ts_ns >= ts_ns[i]) & (ts_ns <= window_end)
                uniq = len(set(targets[in_win]))
                if uniq > max_unique:
                    max_unique = uniq
                    best_mask = in_win

            if max_unique < min_fan:
                continue

            win_targets = list(dict.fromkeys(targets[best_mask]))  # unique, order preserved
            win_amounts = amounts[best_mask]
            win_ts = ts_ns[best_mask]
            time_span_days = (win_ts.max() - win_ts.min()) / 1e9 / 86400
            total_amount = float(win_amounts.sum())

            # Score: degree (0-0.4) + amount (0-0.3) + time-compression (0-0.3)
            degree_frac = min((max_unique - min_fan) / 12, 1.0)
            amount_frac = min(total_amount / 10_000_000, 1.0)
            time_frac = max(0.0, 1.0 - time_span_days / window_days)
            score = round(min(degree_frac * 0.4 + amount_frac * 0.3 + time_frac * 0.3, 1.0), 3)

            if max_unique >= 10:
                severity = "CRITICAL"
            elif max_unique >= 6:
                severity = "HIGH"
            else:
                severity = "MEDIUM"

            account_ids = [account_id] + win_targets[:30]

            if direction == "fan_out":
                indicators = [
                    f"Sends to {max_unique} unique accounts in {time_span_days:.1f} days",
                    f"Total dispersal: {total_amount:,.0f}",
                ]
                detail_key, detail_list = "destinations", win_targets[:30]
            else:
                indicators = [
                    f"Receives from {max_unique} unique accounts in {time_span_days:.1f} days",
                    f"Total collection: {total_amount:,.0f}",
                ]
                detail_key, detail_list = "sources", win_targets[:30]

            results.append(DetectionResult(
                detection_type=direction,
                account_ids=account_ids,
                score=score,
                severity=severity,
                details={
                    "hub_account": account_id,
                    f"unique_{detail_key.rstrip('s')}s": max_unique,
                    "time_span_days": round(time_span_days, 2),
                    "total_amount": round(total_amount, 2),
                    detail_key: detail_list,
                    "sub_type": direction,
                },
                indicators=indicators,
            ))

        return results
