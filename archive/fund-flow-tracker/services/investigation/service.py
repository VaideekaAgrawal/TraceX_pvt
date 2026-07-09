"""
Investigation Service — orchestrates case management + evidence generation.

Responsibilities:
- Create/manage investigation cases
- Generate FIU-IND compliant evidence packs
- Track resolution for feedback loop (model retraining)
"""
import logging
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from infrastructure.event_bus import bus, Topics
from infrastructure.health import health
from services.investigation.case_manager import CaseManager
from services.investigation.evidence import EvidenceGenerator
from services.common.models import Alert, Case, EvidencePack, DetectionSummary
from services.rl.bandit import LinUCBAgent

logger = logging.getLogger(__name__)

_SERVICE = "investigation"

# RL investigation-queue prioritization lives here, not in the API layer —
# only the top N by risk score get re-ranked, keeping /api/rl/queue fast.
_RL_CANDIDATE_CAP = 200

# Pre-defined synthetic feedback sequences for the live judge demo — replaces
# real investigator history with a scripted one so weight evolution can be
# shown in seconds via /api/rl/simulate.
_RL_SCENARIOS: Dict[str, List[Tuple[Dict[str, float], bool]]] = {
    "layering_dominant": [
        ({"has_layering": 1, "risk_score_norm": 0.85, "fraud_prob": 0.7}, True),
        ({"has_round_trip": 1, "risk_score_norm": 0.6, "fraud_prob": 0.3}, False),
        ({"has_layering": 1, "has_round_trip": 1, "risk_score_norm": 0.9}, True),
        ({"has_structuring": 1, "risk_score_norm": 0.5}, False),
        ({"has_layering": 1, "is_mule_role": 1, "risk_score_norm": 0.8}, True),
    ] * 20,
    "balanced": [
        ({"has_layering": 1, "risk_score_norm": 0.8}, True),
        ({"has_structuring": 1, "risk_score_norm": 0.55}, False),
        ({"has_round_trip": 1, "risk_score_norm": 0.7, "fraud_prob": 0.65}, True),
        ({"has_dormancy": 1, "risk_score_norm": 0.45}, False),
        ({"has_profile_mismatch": 1, "is_source_role": 1, "risk_score_norm": 0.75}, True),
    ] * 20,
}


class InvestigationService:
    """Manages investigations, cases, evidence generation, and RL-based
    investigation-queue prioritization."""

    def __init__(self):
        self.case_manager = CaseManager()
        self.evidence_gen = EvidenceGenerator()
        self.rl_agent = LinUCBAgent(alpha=1.0, state_path="data/rl_state.json")
        health.register_service(_SERVICE)

    # ── Alert management ─────────────────────────────────────────────

    def create_alerts_from_detections(self, detection_results: Dict) -> Dict[str, List]:
        """Auto-create/refresh alerts from detection pipeline output. Returns
        the diff dict {alerts, new_ids, reactivated_ids, stale_ids} — see
        CaseManager.auto_create_alerts_from_detections."""
        diff = self.case_manager.auto_create_alerts_from_detections(detection_results)
        alerts = diff["alerts"]
        health.increment("alerts_created", len(diff["new_ids"]))
        health.heartbeat(_SERVICE, "healthy")

        for alert in alerts:
            bus.publish(Topics.ALERT_CREATED, alert.to_dict(), source_service=_SERVICE)

        logger.info("Created %d alerts from detections", len(alerts))
        return diff

    def list_alerts(self, status: Optional[str] = None) -> List[Alert]:
        return self.case_manager.list_alerts(status)

    def get_alert(self, alert_id: str) -> Optional[Alert]:
        return self.case_manager.get_alert(alert_id)

    # ── Case management ──────────────────────────────────────────────

    def create_case(self, account_ids: List[str], typology: str,
                    priority: str = "P3", alert_ids: Optional[List[str]] = None,
                    notes: str = "") -> Case:
        case = self.case_manager.create_case(
            account_ids, typology, priority, alert_ids, notes
        )
        health.increment("cases_opened")
        bus.publish(Topics.CASE_UPDATED, case.to_dict(), source_service=_SERVICE)
        return case

    def update_case(self, case_id: str, status: str, notes: str = "") -> Optional[Case]:
        case = self.case_manager.update_case_status(case_id, status, notes)
        if case:
            bus.publish(Topics.CASE_UPDATED, case.to_dict(), source_service=_SERVICE)
        return case

    def resolve_case(self, case_id: str, resolution: str,
                     is_true_positive: bool) -> Optional[Case]:
        case = self.case_manager.resolve_case(case_id, resolution, is_true_positive)
        if case:
            bus.publish(Topics.CASE_UPDATED, case.to_dict(), source_service=_SERVICE)
        return case

    def get_case(self, case_id: str) -> Optional[Case]:
        return self.case_manager.get_case(case_id)

    def list_cases(self, status: Optional[str] = None) -> List[Case]:
        return self.case_manager.list_cases(status)

    def get_case_stats(self) -> Dict[str, int]:
        return self.case_manager.get_stats()

    # ── Evidence generation ──────────────────────────────────────────

    def generate_evidence(self, case_id: str, account_ids: List[str],
                          detection_summary: DetectionSummary,
                          transactions_df: pd.DataFrame,
                          accounts_df: pd.DataFrame,
                          case_notes: str = "") -> EvidencePack:
        """Generate FIU-IND compliant evidence pack."""
        pack = self.evidence_gen.generate(
            case_id, account_ids, detection_summary,
            transactions_df, accounts_df, case_notes,
        )

        # Link evidence to case
        case = self.case_manager.get_case(case_id)
        if case:
            case.evidence_hash = pack.json_hash

        return pack

    # ── RL-based investigation-queue prioritization ──────────────────

    @staticmethod
    def _rl_txn_maps(txns_df: Optional[pd.DataFrame]) -> Dict[str, Dict]:
        """Vectorised per-account aggregates (amounts, counterparties, channels) via groupby."""
        if txns_df is None or txns_df.empty:
            return {"total_out": {}, "total_in": {}, "out_partners": {}, "in_partners": {},
                    "out_channels": {}, "in_channels": {}}

        out_grp = txns_df.groupby("source_account")
        in_grp = txns_df.groupby("dest_account")
        has_channel = "channel" in txns_df.columns

        return {
            "total_out": out_grp["amount"].sum().to_dict(),
            "total_in": in_grp["amount"].sum().to_dict(),
            "out_partners": out_grp["dest_account"].apply(set).to_dict(),
            "in_partners": in_grp["source_account"].apply(set).to_dict(),
            "out_channels": out_grp["channel"].apply(set).to_dict() if has_channel else {},
            "in_channels": in_grp["channel"].apply(set).to_dict() if has_channel else {},
        }

    @staticmethod
    def _rl_account_features(acc_id: str, maps: Dict[str, Dict], declared_map: Dict[str, float],
                             detection_summary: DetectionSummary) -> Dict:
        """Build the flat feature dict LinUCBAgent.build_context() expects for one account."""
        anom_score = detection_summary.anomaly_scores.get(acc_id, 0.0)
        fraud_prob = detection_summary.fraud_probabilities.get(acc_id, 0.0)

        total_out = maps["total_out"].get(acc_id, 0.0)
        total_in = maps["total_in"].get(acc_id, 0.0)
        counterparties = len(maps["out_partners"].get(acc_id, set()) | maps["in_partners"].get(acc_id, set()))
        channels = maps["out_channels"].get(acc_id, set()) | maps["in_channels"].get(acc_id, set())

        return {
            "account_id": acc_id,
            "risk_score": detection_summary.risk_scores.get(acc_id, 0.0),
            "role": detection_summary.roles.get(acc_id, {}).get("role", "NORMAL"),
            "patterns": list(detection_summary.detection_flags.get(acc_id, {}).keys()),
            "anomaly_score": anom_score,
            "fraud_probability": fraud_prob,
            "total_in_flow": total_in,
            "total_out_flow": total_out,
            "total_amount": total_in + total_out,
            "counterparties": counterparties,
            "declared_annual_income": declared_map.get(acc_id, 0.0),
            "channel_diversity": len(channels) or 1,
        }

    def get_prioritized_queue(self, accounts_df: Optional[pd.DataFrame],
                             txns_df: Optional[pd.DataFrame],
                             detection_summary: DetectionSummary) -> Dict[str, Any]:
        """RL-ranked investigation queue — accounts sorted by UCB score
        (exploration + exploitation) among the top-risk candidates."""
        maps = self._rl_txn_maps(txns_df)
        declared_map = (
            accounts_df.set_index("account_id")["declared_annual_income"].to_dict()
            if accounts_df is not None and "declared_annual_income" in accounts_df.columns else {}
        )

        candidates = []
        for acc_id, score in sorted(detection_summary.risk_scores.items(), key=lambda x: x[1], reverse=True):
            if score < 26:
                break  # risk dict isn't sorted by insertion, but this list is now sorted desc
            candidates.append(self._rl_account_features(acc_id, maps, declared_map, detection_summary))
            if len(candidates) >= _RL_CANDIDATE_CAP:
                break

        ranked = self.rl_agent.rank_accounts(candidates)
        return {"queue": ranked, "agent_stats": self.rl_agent.get_stats()}

    def submit_feedback(self, account_id: str, is_true_positive: bool,
                        accounts_df: Optional[pd.DataFrame], txns_df: Optional[pd.DataFrame],
                        detection_summary: DetectionSummary) -> Optional[Dict[str, Any]]:
        """Investigator submits a TP/FP verdict — the RL agent updates online
        (O(d^2)). Returns None if the account isn't currently scored."""
        if account_id not in detection_summary.risk_scores:
            return None

        maps = self._rl_txn_maps(txns_df)
        declared_map = (
            accounts_df.set_index("account_id")["declared_annual_income"].to_dict()
            if accounts_df is not None and "declared_annual_income" in accounts_df.columns else {}
        )
        acc_dict = self._rl_account_features(account_id, maps, declared_map, detection_summary)
        ctx = self.rl_agent.build_context(acc_dict)
        result = self.rl_agent.receive_feedback(account_id, ctx, is_true_positive)

        return {
            "reward_applied": result["reward"],
            "agent_stats": self.rl_agent.get_stats(),
            "top_learned_features": result["learned_weights_snapshot"],
        }

    def get_rl_weights(self) -> Dict[str, Any]:
        """Current learned feature weights — full interpretability for compliance review."""
        return {
            "weights": self.rl_agent.get_learned_weights(),
            "stats": self.rl_agent.get_stats(),
            "interpretation": "Positive weight = feature increases investigation priority. "
                              "Negative weight = feature reduces priority (learned false-positive signal).",
        }

    def simulate_rl_feedback(self, scenario: str, steps: int) -> Dict[str, Any]:
        """Demo helper: replay N synthetic feedback events to show the agent
        learning live, without needing real investigator history."""
        sequence = _RL_SCENARIOS.get(scenario, _RL_SCENARIOS["balanced"])[:steps]
        feature_map = {name: j for j, name in enumerate(self.rl_agent.FEATURE_NAMES)}
        snapshots = []

        for i, (features, is_tp) in enumerate(sequence):
            ctx = np.zeros(self.rl_agent.d)
            for k, v in features.items():
                if k in feature_map:
                    ctx[feature_map[k]] = v
            ctx[-1] = 1.0  # bias
            self.rl_agent.update(ctx, 1.0 if is_tp else -0.3)

            if i % 5 == 0 or i == len(sequence) - 1:
                snapshots.append({
                    "step": i + 1,
                    "weights": self.rl_agent._get_top_weights(5),
                    "precision": self.rl_agent.get_stats()["learned_precision"],
                })

        return {
            "steps_replayed": len(sequence),
            "final_stats": self.rl_agent.get_stats(),
            "weight_evolution": snapshots,
            "message": f"Simulated {len(sequence)} investigator decisions using the "
                       f"'{scenario}' scenario.",
        }
