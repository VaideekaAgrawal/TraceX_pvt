"""
Round-Trip Detector — detects circular transaction flows using Johnson's algorithm.

Detection method:
- Run bounded cycle detection on temporal graph slices
- Flag cycles where final credit ≥ 85% of originating debit
- Batch job: runs on 72-hour windows to manage graph query cost
"""
import logging
from collections import defaultdict
from types import SimpleNamespace
from typing import Dict, List, Optional

import pandas as pd

from infrastructure.config import config
from services.common.models import DetectionResult

logger = logging.getLogger(__name__)


class RoundTripDetector:
    """Detect circular transaction flows (A→B→C→A) using Johnson's algorithm."""

    def __init__(self, params: Optional[Dict] = None):
        """`params` (used by the Rule Engine's `cycle` primitive) overrides
        individual thresholds without touching the global config singleton —
        omit it (the default) to get today's exact configured behavior."""
        base = config.detection
        p = params or {}
        self.cfg = SimpleNamespace(
            round_trip_max_cycle_length=p.get("max_length", base.round_trip_max_cycle_length),
            round_trip_max_cycles=p.get("max_cycles", base.round_trip_max_cycles),
            round_trip_amount_return_ratio=p.get("min_return_ratio", base.round_trip_amount_return_ratio),
        )

    def detect(self, graph_engine, transactions_df: pd.DataFrame) -> List[DetectionResult]:
        cycles = graph_engine.detect_cycles(
            max_length=self.cfg.round_trip_max_cycle_length,
            max_cycles=self.cfg.round_trip_max_cycles,
        )

        results = []
        for cycle_nodes in cycles:
            cycle_txns = []
            total_amount = 0.0

            for i in range(len(cycle_nodes)):
                src = cycle_nodes[i]
                dst = cycle_nodes[(i + 1) % len(cycle_nodes)]
                edge_txns = transactions_df[
                    (transactions_df["source_account"] == src) &
                    (transactions_df["dest_account"] == dst)
                ]
                for _, txn in edge_txns.iterrows():
                    cycle_txns.append({
                        "from": src, "to": dst,
                        "amount": txn["amount"],
                        "timestamp": txn["timestamp"],
                        "channel": txn.get("channel", ""),
                    })
                    total_amount += txn["amount"]

            if not cycle_txns:
                continue

            timestamps = [t["timestamp"] for t in cycle_txns]
            time_span_hours = (max(timestamps) - min(timestamps)).total_seconds() / 3600

            # Check amount return ratio — key signal
            # Money sent from cycle_nodes[0] vs money received back
            sent = sum(t["amount"] for t in cycle_txns if t["from"] == cycle_nodes[0])
            received = sum(t["amount"] for t in cycle_txns if t["to"] == cycle_nodes[0])
            return_ratio = received / sent if sent > 0 else 0

            is_tight_loop = return_ratio >= self.cfg.round_trip_amount_return_ratio

            score = min(1.0,
                        (0.4 if is_tight_loop else 0.1) +
                        min(len(cycle_nodes) / 10, 0.3) +
                        min(total_amount / 5_000_000, 0.3))

            severity = "CRITICAL" if is_tight_loop and len(cycle_nodes) >= 3 else \
                       "HIGH" if is_tight_loop else "MEDIUM"

            results.append(DetectionResult(
                detection_type="round_trip",
                account_ids=cycle_nodes,
                score=round(score, 3),
                severity=severity,
                details={
                    "cycle_nodes": cycle_nodes,
                    "cycle_length": len(cycle_nodes),
                    "transactions": cycle_txns,
                    "total_amount": round(total_amount, 2),
                    "time_span_hours": round(time_span_hours, 2),
                    "return_ratio": round(return_ratio, 4),
                    "iteration_count": len(cycle_txns) // max(len(cycle_nodes), 1),
                },
                indicators=[
                    f"{len(cycle_nodes)}-node cycle",
                    f"Return ratio: {return_ratio:.1%}",
                    f"Total circulated: INR {total_amount:,.0f}",
                    f"Time span: {time_span_hours:.1f} hours",
                ],
            ))

        results.sort(key=lambda r: r.score, reverse=True)
        logger.info("Round-trip: found %d cycles", len(results))
        return results
