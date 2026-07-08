"""
Profile Mismatch Detector — behavioural baseline comparison.

Detection method:
- Build per-account behavioural baseline (transaction frequency, avg amount,
  channel distribution, geographic spread) over configurable window
- Compare live behaviour against baseline using Mahalanobis distance / z-score
- Deviations beyond 3σ trigger flag
- Also: income-vs-volume ratio check and peer group comparison
"""
import logging
from types import SimpleNamespace
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from infrastructure.config import config
from services.common.models import DetectionResult
from services.detection.features import safe_ratio

logger = logging.getLogger(__name__)


class ProfileMismatchDetector:
    """Detect accounts whose behaviour doesn't match their declared profile."""

    def __init__(self, params: Optional[Dict] = None):
        """`params` overrides individual thresholds without touching the
        global config singleton — omit it (the default) to get today's
        exact configured behavior. Used by the Rule Engine's
        `volume_vs_declared_income_ratio`, `peer_zscore_deviation`, and
        `behavioural_shift` primitives, which each map to one of this
        detector's three internal checks."""
        base = config.detection
        p = params or {}
        self.cfg = SimpleNamespace(
            profile_mismatch_z_threshold=p.get("z_threshold", base.profile_mismatch_z_threshold),
            income_mismatch_ratio_threshold=p.get("ratio_threshold", 10),
            peer_min_group_size=p.get("min_peer_group_size", 5),
            behavioural_shift_z_threshold=p.get("shift_z_threshold", 3),
            behavioural_shift_min_txn_count=p.get("min_txn_count", 15),
            behavioural_shift_rolling_window=p.get("rolling_window", 20),
        )

    def detect(self, graph_engine, transactions_df: pd.DataFrame,
               accounts_df: pd.DataFrame) -> List[DetectionResult]:
        results = []
        results.extend(self._detect_income_mismatch(transactions_df, accounts_df))
        results.extend(self._detect_peer_deviation(transactions_df, accounts_df))
        results.extend(self._detect_behavioural_shift(transactions_df))

        results.sort(key=lambda r: r.score, reverse=True)
        logger.info("Profile mismatch: found %d alerts", len(results))
        return results

    def _detect_income_mismatch(self, txns: pd.DataFrame,
                                 accounts: pd.DataFrame) -> List[DetectionResult]:
        """Volume > 10× declared annual income — vectorised."""
        results = []
        if "declared_annual_income" not in accounts.columns:
            return []
        accs = accounts[accounts["declared_annual_income"] > 0].copy()
        if accs.empty:
            return []

        # Compute per-account total volume vectorised
        src_vol = txns.groupby("source_account")["amount"].sum().rename("src_vol")
        dst_vol = txns.groupby("dest_account")["amount"].sum().rename("dst_vol")
        vol = src_vol.add(dst_vol, fill_value=0).rename("volume")

        accs = accs.set_index("account_id") if "account_id" in accs.columns else accs
        accs = accs.join(vol, how="left")
        accs["volume"] = accs["volume"].fillna(0)
        accs["ratio"] = accs["volume"] / accs["declared_annual_income"].clip(lower=1)
        flagged = accs[accs["ratio"] > self.cfg.income_mismatch_ratio_threshold]

        for acc_id, row in flagged.iterrows():
            ratio = float(row["ratio"])
            volume = float(row["volume"])
            declared = float(row["declared_annual_income"])
            score = min(1.0, min(ratio / 100, 0.5) + 0.3 + min(volume / 10_000_000, 0.2))
            severity = "CRITICAL" if ratio > 50 else "HIGH" if ratio > 20 else "MEDIUM"
            results.append(DetectionResult(
                detection_type="profile_mismatch",
                account_ids=[acc_id],
                score=round(score, 3),
                severity=severity,
                details={
                    "sub_type": "income_mismatch",
                    "declared_annual_income": round(declared, 2),
                    "actual_volume": round(volume, 2),
                    "volume_to_income_ratio": round(ratio, 2),
                    "occupation": row.get("occupation", "unknown"),
                    "income_bracket": row.get("income_bracket", "unknown"),
                },
                indicators=[
                    f"Volume/income ratio: {ratio:.1f}× ({row.get('occupation', 'unknown')})",
                    f"Declared: {declared:,.0f}, Actual: {volume:,.0f}",
                ],
            ))
        return results

    def _detect_peer_deviation(self, txns: pd.DataFrame,
                                accounts: pd.DataFrame) -> List[DetectionResult]:
        """Account volume deviates > 3σ from peer group — vectorised."""
        results = []
        if "occupation" not in accounts.columns or "income_bracket" not in accounts.columns:
            return []

        # Compute per-account volume vectorised
        src_vol = txns.groupby("source_account")["amount"].sum()
        dst_vol = txns.groupby("dest_account")["amount"].sum()
        vol = src_vol.add(dst_vol, fill_value=0)

        accs = accounts.copy()
        accs = accs.set_index("account_id") if "account_id" in accs.columns else accs
        accs.index.name = "account_id"  # guarantee stable name before reset_index
        accs["volume"] = accs.index.map(vol).fillna(0)

        # Compute peer group stats via groupby
        peer_stats = accs.groupby(["occupation", "income_bracket"])["volume"].agg(
            mean="mean", std="std", count="count"
        ).reset_index()
        peer_stats = peer_stats[peer_stats["count"] >= self.cfg.peer_min_group_size]

        accs = accs.reset_index().merge(peer_stats, on=["occupation", "income_bracket"], how="inner")
        accs["z_score"] = (accs["volume"] - accs["mean"]) / accs["std"].clip(lower=1)
        flagged = accs[accs["z_score"].abs() > self.cfg.profile_mismatch_z_threshold]

        for _, row in flagged.iterrows():
            acc_id = row.get("account_id", row.get("index"))
            z = float(row["z_score"])
            vol_val = float(row["volume"])
            score = min(1.0, abs(z) / 10 * 0.6 + 0.2)
            severity = "CRITICAL" if abs(z) > 5 else "HIGH" if abs(z) > 3 else "MEDIUM"
            results.append(DetectionResult(
                detection_type="profile_mismatch",
                account_ids=[acc_id],
                score=round(score, 3),
                severity=severity,
                details={
                    "sub_type": "peer_deviation",
                    "z_score": round(z, 2),
                    "actual_volume": round(vol_val, 2),
                    "peer_mean": round(float(row["mean"]), 2),
                    "peer_std": round(float(row["std"]), 2),
                    "peer_count": int(row["count"]),
                    "occupation": row.get("occupation", ""),
                    "income_bracket": row.get("income_bracket", ""),
                },
                indicators=[
                    f"Z-score: {z:.1f}σ from {row.get('occupation','')}/{row.get('income_bracket','')} peer group",
                    f"Peer average: {row['mean']:,.0f}, This account: {vol_val:,.0f}",
                ],
            ))
        return results

    def _detect_behavioural_shift(self, txns: pd.DataFrame) -> List[DetectionResult]:
        """Detect sudden amount spikes per account — vectorised via groupby + rolling."""
        results = []
        # Build long-format (account, timestamp, amount)
        src = txns[["source_account", "timestamp", "amount"]].rename(
            columns={"source_account": "account_id"}
        )
        dst = txns[["dest_account", "timestamp", "amount"]].rename(
            columns={"dest_account": "account_id"}
        )
        acc_txns = pd.concat([src, dst], ignore_index=True)
        acc_txns = acc_txns.sort_values(["account_id", "timestamp"]).reset_index(drop=True)

        # Only keep accounts with enough transactions for a meaningful rolling baseline
        counts = acc_txns.groupby("account_id").size()
        valid = counts[counts >= self.cfg.behavioural_shift_min_txn_count].index
        acc_txns = acc_txns[acc_txns["account_id"].isin(valid)].copy()

        # Vectorised rolling z-score per account
        window = self.cfg.behavioural_shift_rolling_window
        acc_txns["rolling_mean"] = (
            acc_txns.groupby("account_id")["amount"]
            .transform(lambda x: x.rolling(window=window, min_periods=5).mean())
        )
        acc_txns["rolling_std"] = (
            acc_txns.groupby("account_id")["amount"]
            .transform(lambda x: x.rolling(window=window, min_periods=5).std().clip(lower=1))
        )
        acc_txns["z_score"] = (acc_txns["amount"] - acc_txns["rolling_mean"]) / acc_txns["rolling_std"]

        # Pick most anomalous spike per account (highest z_score, not earliest)
        spikes = acc_txns[acc_txns["z_score"] > self.cfg.behavioural_shift_z_threshold]
        first_spikes = (
            spikes.sort_values("z_score", ascending=False)
                  .groupby("account_id")
                  .first()
                  .reset_index()
        )

        for _, row in first_spikes.iterrows():
            acc_id = row["account_id"]
            z = float(row["z_score"])
            score = min(1.0, abs(z) / 10 * 0.5 + 0.2)
            results.append(DetectionResult(
                detection_type="profile_mismatch",
                account_ids=[acc_id],
                score=round(score, 3),
                severity="HIGH" if z > 5 else "MEDIUM",
                details={
                    "sub_type": "behavioural_shift",
                    "first_spike_timestamp": str(row["timestamp"]),
                    "spike_amount": round(float(row["amount"]), 2),
                    "rolling_mean": round(float(row["rolling_mean"]), 2),
                    "z_score": round(z, 2),
                },
                indicators=[
                    f"Amount spike: {row['amount']:,.0f} vs avg {row['rolling_mean']:,.0f}",
                    f"Z-score: {z:.1f}",
                ],
            ))
        return results
