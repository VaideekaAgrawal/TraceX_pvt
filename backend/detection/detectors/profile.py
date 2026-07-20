"""
Profile Mismatch Detector — behavioural baseline comparison.

Ported unchanged from `archive/fund-flow-tracker/services/detection/
profile.py`: income-vs-volume mismatch, peer-group z-score deviation, and
sudden per-account amount-spike ("behavioural shift") checks.

(The archive imports `services.detection.features.safe_ratio` but never
actually calls it in this file — dropped here as a genuinely dead import,
not a behavior change; ruff's F401 would otherwise fail CI on a port of
dead code.)
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


class ProfileMismatchDetector:
    """Detect accounts whose behaviour doesn't match their declared profile."""

    def __init__(
        self,
        params: dict[str, Any] | None = None,
        config: DetectionConfig | None = None,
    ):
        """`params` overrides individual thresholds without touching the
        shared default config -- omit it to get today's exact configured
        behavior. Used by the Rule Engine's `volume_vs_declared_income_ratio`,
        `peer_zscore_deviation`, and `behavioural_shift` primitives, which
        each map to one of this detector's three internal checks."""
        base = config or DEFAULT_DETECTION_CONFIG
        p = params or {}
        self.cfg = SimpleNamespace(
            profile_mismatch_z_threshold=p.get("z_threshold", base.profile_mismatch_z_threshold),
            income_mismatch_ratio_threshold=p.get("ratio_threshold", 10),
            peer_min_group_size=p.get("min_peer_group_size", 5),
            behavioural_shift_z_threshold=p.get("shift_z_threshold", 3),
            behavioural_shift_min_txn_count=p.get("min_txn_count", 15),
            behavioural_shift_rolling_window=p.get("rolling_window", 20),
        )

    def detect(
        self,
        graph_store: GraphStore,
        transactions_df: pd.DataFrame,
        accounts_df: pd.DataFrame,
    ) -> list[DetectionResult]:
        results = []
        results.extend(self._detect_income_mismatch(transactions_df, accounts_df))
        results.extend(self._detect_peer_deviation(transactions_df, accounts_df))
        results.extend(self._detect_behavioural_shift(transactions_df, accounts_df))

        results.sort(key=lambda r: r.score, reverse=True)
        logger.info("Profile mismatch: found %d alerts", len(results))
        return results

    def _detect_income_mismatch(
        self, txns: pd.DataFrame, accounts: pd.DataFrame
    ) -> list[DetectionResult]:
        """Volume > configured x declared annual income — vectorised."""
        if "declared_annual_income" not in accounts.columns:
            return []
        accs = accounts[accounts["declared_annual_income"] > 0].copy()
        if accs.empty:
            return []

        src_vol = txns.groupby("source_account")["amount"].sum().rename("src_vol")
        dst_vol = txns.groupby("dest_account")["amount"].sum().rename("dst_vol")
        vol = src_vol.add(dst_vol, fill_value=0).rename("volume")

        accs = accs.set_index("account_id") if "account_id" in accs.columns else accs
        accs = accs.join(vol, how="left")
        accs["volume"] = accs["volume"].fillna(0)
        accs["ratio"] = accs["volume"] / accs["declared_annual_income"].clip(lower=1)
        flagged = accs[accs["ratio"] > self.cfg.income_mismatch_ratio_threshold]

        results = []
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
                    f"Volume/income ratio: {ratio:.1f}x ({row.get('occupation', 'unknown')})",
                    f"Declared: {declared:,.0f}, Actual: {volume:,.0f}",
                ],
            ))
        return results

    def _detect_peer_deviation(
        self, txns: pd.DataFrame, accounts: pd.DataFrame
    ) -> list[DetectionResult]:
        """Account volume deviates beyond a z-score threshold from its peer
        group — vectorised."""
        if "occupation" not in accounts.columns or "income_bracket" not in accounts.columns:
            return []

        src_vol = txns.groupby("source_account")["amount"].sum()
        dst_vol = txns.groupby("dest_account")["amount"].sum()
        vol = src_vol.add(dst_vol, fill_value=0)

        accs = accounts.copy()
        accs = accs.set_index("account_id") if "account_id" in accs.columns else accs
        accs.index.name = "account_id"
        accs["volume"] = accs.index.map(vol).fillna(0)

        peer_stats = accs.groupby(["occupation", "income_bracket"])["volume"].agg(
            mean="mean", std="std", count="count"
        ).reset_index()
        peer_stats = peer_stats[peer_stats["count"] >= self.cfg.peer_min_group_size]

        accs = accs.reset_index().merge(
            peer_stats, on=["occupation", "income_bracket"], how="inner"
        )
        accs["z_score"] = (accs["volume"] - accs["mean"]) / accs["std"].clip(lower=1)
        flagged = accs[accs["z_score"].abs() > self.cfg.profile_mismatch_z_threshold]

        results = []
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
                    f"Z-score: {z:.1f} sigma from "
                    f"{row.get('occupation', '')}/{row.get('income_bracket', '')} peer group",
                    f"Peer average: {row['mean']:,.0f}, This account: {vol_val:,.0f}",
                ],
            ))
        return results

    def _detect_behavioural_shift(
        self, txns: pd.DataFrame, accounts: pd.DataFrame | None = None
    ) -> list[DetectionResult]:
        """Detect sudden amount spikes per account — vectorised via groupby + rolling.

        **A profile-mismatch alert requires a profile.** This sub-detector is
        transaction-only, so on a KYC-barren dataset it would flag any account
        with enough activity and a spike — which is how the real IBM benchmark
        produced ~36k `profile_mismatch` alerts (86% of all alerts) on accounts
        that carry no occupation/income at all. A "profile mismatch" on an entity
        we have no profile for is meaningless noise. So gate to accounts that
        actually have a declared profile (`declared_annual_income > 0`), matching
        the gate `_detect_income_mismatch` already applies. Accounts *are* passed
        now; the old `accounts=None` path (no gate) is kept only for direct unit
        callers and treats "no accounts frame" as "cannot verify a profile → skip"."""
        src = txns[["source_account", "timestamp", "amount"]].rename(
            columns={"source_account": "account_id"}
        )
        dst = txns[["dest_account", "timestamp", "amount"]].rename(
            columns={"dest_account": "account_id"}
        )
        acc_txns = pd.concat([src, dst], ignore_index=True)
        acc_txns = acc_txns.sort_values(["account_id", "timestamp"]).reset_index(drop=True)

        # Keep only accounts with a declared profile to (potentially) mismatch.
        if accounts is None or "declared_annual_income" not in accounts.columns:
            return []
        profiled = set(
            accounts.loc[accounts["declared_annual_income"] > 0, "account_id"].astype(str)
        )
        if not profiled:
            return []
        acc_txns = acc_txns[acc_txns["account_id"].astype(str).isin(profiled)].copy()

        counts = acc_txns.groupby("account_id").size()
        valid = counts[counts >= self.cfg.behavioural_shift_min_txn_count].index
        acc_txns = acc_txns[acc_txns["account_id"].isin(valid)].copy()

        window = self.cfg.behavioural_shift_rolling_window
        acc_txns["rolling_mean"] = (
            acc_txns.groupby("account_id")["amount"]
            .transform(lambda x: x.rolling(window=window, min_periods=5).mean())
        )
        acc_txns["rolling_std"] = (
            acc_txns.groupby("account_id")["amount"]
            .transform(lambda x: x.rolling(window=window, min_periods=5).std().clip(lower=1))
        )
        amount_delta = acc_txns["amount"] - acc_txns["rolling_mean"]
        acc_txns["z_score"] = amount_delta / acc_txns["rolling_std"]

        spikes = acc_txns[acc_txns["z_score"] > self.cfg.behavioural_shift_z_threshold]
        first_spikes = (
            spikes.sort_values("z_score", ascending=False)
            .groupby("account_id")
            .first()
            .reset_index()
        )

        results = []
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
