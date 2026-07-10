"""
Layering Detector — detects rapid multi-hop fund transfers with amount decay.

Ported unchanged from `archive/fund-flow-tracker/services/detection/
layering.py`: A->B->C->D with decreasing amounts in a short window (tight
mode), or a longer multi-day chain deep enough to be a STACK pattern
(extended mode, no decay requirement — see class docstring below).
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


class LayeringDetector:
    """Detect layering: A->B->C->D with decreasing amounts in short time."""

    def __init__(
        self,
        params: dict[str, Any] | None = None,
        config: DetectionConfig | None = None,
    ):
        """`params` (used by the Rule Engine's `chain` primitive) overrides
        individual thresholds without touching the shared default config --
        omit it to get today's exact configured behavior."""
        base = config or DEFAULT_DETECTION_CONFIG
        p = params or {}
        self.cfg = SimpleNamespace(
            layering_min_hops=p.get("min_hops", base.layering_min_hops),
            layering_time_window_minutes=p.get(
                "time_window_minutes", base.layering_time_window_minutes
            ),
            layering_extended_min_hops=p.get(
                "extended_min_hops", base.layering_extended_min_hops
            ),
            layering_extended_window_minutes=p.get(
                "extended_window_minutes", base.layering_extended_window_minutes
            ),
            layering_decay_ratio_threshold=p.get("decay_ratio_threshold", 0.5),
        )

    def detect(
        self, graph_store: GraphStore, transactions_df: pd.DataFrame
    ) -> list[DetectionResult]:
        # Pass 1: tight window (same-day / intra-day chains, min 3 hops)
        chains = graph_store.get_transaction_chains(
            min_hops=self.cfg.layering_min_hops,
            time_window_minutes=self.cfg.layering_time_window_minutes,
        )
        # Pass 2: extended window (multi-day STACK chains, min 4 hops).
        chains_extended = graph_store.get_transaction_chains(
            min_hops=self.cfg.layering_extended_min_hops,
            time_window_minutes=self.cfg.layering_extended_window_minutes,
            max_chains=3000,
            shuffle_starts=True,
        )
        seen = {tuple(txn["from"] for txn in c) + (c[-1]["to"],) for c in chains}
        for c in chains_extended:
            fp = tuple(txn["from"] for txn in c) + (c[-1]["to"],)
            if fp not in seen:
                chains.append(c)
                seen.add(fp)

        results = []
        for chain in chains:
            amounts = [step["amount"] for step in chain]
            if len(amounts) < 2:
                continue

            decreasing = sum(1 for i in range(1, len(amounts)) if amounts[i] < amounts[i - 1])
            decay_ratio = decreasing / (len(amounts) - 1)

            timestamps = [step["timestamp"] for step in chain if step.get("timestamp") is not None]
            time_span = 0.0
            if len(timestamps) >= 2:
                time_span = (max(timestamps) - min(timestamps)).total_seconds() / 60

            total_decay = (amounts[0] - amounts[-1]) / amounts[0] if amounts[0] > 0 else 0
            preservation = amounts[-1] / amounts[0] if amounts[0] > 0 else 0

            is_tight = time_span <= self.cfg.layering_time_window_minutes
            is_extended = (
                time_span <= self.cfg.layering_extended_window_minutes
                and len(chain) >= self.cfg.layering_extended_min_hops
            )

            passes_tight = is_tight and decay_ratio >= self.cfg.layering_decay_ratio_threshold
            passes_extended = is_extended

            if not (passes_tight or passes_extended):
                continue

            accounts = []
            for step in chain:
                accounts.append(step["from"])
            accounts.append(chain[-1]["to"])
            accounts = list(dict.fromkeys(accounts))

            chain_mode = "tight" if passes_tight else "extended"
            score = max(
                0.0,
                min(1.0, decay_ratio * 0.4 + min(len(chain) / 10, 0.3) + (1 - preservation) * 0.3),
            )

            severity = (
                "CRITICAL" if len(chain) >= 5 and total_decay >= 0.15
                else "HIGH" if len(chain) >= 4
                else "MEDIUM"
            )

            results.append(DetectionResult(
                detection_type="layering",
                account_ids=accounts,
                score=round(score, 3),
                severity=severity,
                details={
                    "chain": chain,
                    "hops": len(chain),
                    "time_span_minutes": round(time_span, 2),
                    "total_amount": sum(amounts),
                    "amount_decay": round(total_decay, 4),
                    "preservation_ratio": round(preservation, 4),
                    "start_amount": amounts[0],
                    "end_amount": amounts[-1],
                    "chain_mode": chain_mode,
                },
                indicators=[
                    f"{len(chain)}-hop {chain_mode} chain in {time_span:.0f} minutes",
                    f"Amount decay: {total_decay:.1%}",
                    f"Preservation ratio: {preservation:.1%}",
                ],
            ))

        results.sort(key=lambda r: r.score, reverse=True)
        results = results[:500]
        logger.info("Layering: found %d suspicious chains", len(results))
        return results
