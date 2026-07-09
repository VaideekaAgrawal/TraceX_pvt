"""
LinUCB Contextual Bandit — Adaptive Investigation Queue (demo).

State: account feature vector (d-dimensional)
Action: recommend this account for next investigation
Reward: +1.0 (TP confirmed) | -0.3 (FP) | 0.0 (not investigated)

Maintains a d x d precision matrix A and reward vector b.
Ranking picks the highest UCB score; feedback updates A/b online in O(d^2).
"""
import numpy as np
import json
import os
from typing import Dict, List, Tuple
from datetime import datetime, timezone


class LinUCBAgent:
    """
    Linear Upper Confidence Bound contextual bandit for investigation prioritisation.
    Reference: Li et al., "A Contextual-Bandit Approach to Personalized News Article
    Recommendation", WWW 2010. Adapted for AML investigation triage.
    """

    FEATURE_NAMES = [
        "risk_score_norm",
        "anomaly_score_norm",
        "fraud_prob",
        "pattern_count",
        "has_layering",
        "has_round_trip",
        "has_structuring",
        "has_dormancy",
        "has_profile_mismatch",
        "is_source_role",
        "is_mule_role",
        "log_total_amount",
        "counterparty_count_norm",
        "income_ratio_norm",
        "channel_diversity",
        "bias",
    ]

    def __init__(self, alpha: float = 1.0, state_path: str = "data/rl_state.json"):
        self.d = len(self.FEATURE_NAMES)
        self.alpha = alpha
        self.state_path = state_path

        self.A = np.identity(self.d)
        self.b = np.zeros(self.d)

        self.total_feedback = 0
        self.tp_count = 0
        self.fp_count = 0

        self._load_state()

    # -- Core LinUCB --------------------------------------------------------

    def score(self, context: np.ndarray) -> Tuple[float, float, float]:
        """Returns (expected_reward, uncertainty, ucb_score) for a context vector."""
        x = context.reshape(-1, 1)
        A_inv = np.linalg.inv(self.A)
        theta = A_inv @ self.b

        expected = (theta.T @ x).item()
        uncertainty = float(np.sqrt(max((x.T @ A_inv @ x).item(), 0.0)))
        ucb = expected + self.alpha * uncertainty
        return expected, uncertainty, ucb

    def update(self, context: np.ndarray, reward: float):
        """Online update after investigator feedback. O(d^2) — microseconds."""
        x = context.reshape(-1, 1)
        self.A += x @ x.T
        self.b += reward * x.reshape(-1)
        self.total_feedback += 1
        if reward > 0:
            self.tp_count += 1
        elif reward < 0:
            self.fp_count += 1
        self._save_state()

    def rank_accounts(self, accounts: List[Dict]) -> List[Dict]:
        """Re-rank account dicts by UCB score (context built from each dict's fields)."""
        scored = []
        for acc in accounts:
            ctx = self.build_context(acc)
            expected, uncertainty, ucb = self.score(ctx)
            scored.append({
                **acc,
                "rl_expected_reward": round(expected, 4),
                "rl_uncertainty": round(uncertainty, 4),
                "rl_ucb_score": round(ucb, 4),
                "rl_is_exploration": uncertainty > 0.3,
            })
        return sorted(scored, key=lambda r: r["rl_ucb_score"], reverse=True)

    def receive_feedback(self, account_id: str, context: np.ndarray,
                          is_true_positive: bool) -> Dict:
        """Called when investigator closes a case with a TP/FP verdict."""
        reward = 1.0 if is_true_positive else -0.3
        self.update(context, reward)
        return {
            "account_id": account_id,
            "is_true_positive": is_true_positive,
            "reward": reward,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "learned_weights_snapshot": self._get_top_weights(),
        }

    # -- Feature Building ----------------------------------------------------

    def build_context(self, acc: Dict) -> np.ndarray:
        """Convert an account feature dict into a normalised context vector."""
        patterns = acc.get("patterns") or []
        total_amount = acc.get("total_amount", 0) or 0
        declared = acc.get("declared_annual_income", 0) or 1
        actual_volume = (acc.get("total_in_flow", 0) or 0) + (acc.get("total_out_flow", 0) or 0)

        return np.array([
            (acc.get("risk_score", 0) or 0) / 100.0,
            (acc.get("anomaly_score", 0) or 0) / 100.0,
            acc.get("fraud_probability", 0) or 0,
            min(len(patterns) / 5.0, 1.0),
            1.0 if "layering" in patterns else 0.0,
            1.0 if "round_trip" in patterns else 0.0,
            1.0 if "structuring" in patterns else 0.0,
            1.0 if "dormancy" in patterns else 0.0,
            1.0 if "profile_mismatch" in patterns else 0.0,
            1.0 if acc.get("role") == "SOURCE" else 0.0,
            1.0 if acc.get("role") == "MULE" else 0.0,
            min(np.log1p(total_amount) / 20.0, 1.0),
            min((acc.get("counterparties", 0) or 0) / 50.0, 1.0),
            min(actual_volume / max(declared, 1) / 10.0, 1.0),
            min((acc.get("channel_diversity", 1) or 1) / 5.0, 1.0),
            1.0,  # bias
        ], dtype=float)

    # -- Interpretability ------------------------------------------------------

    def get_learned_weights(self) -> Dict[str, float]:
        """Current learned weight per feature — fully interpretable."""
        A_inv = np.linalg.inv(self.A)
        theta = A_inv @ self.b
        return {name: round(float(w), 4) for name, w in zip(self.FEATURE_NAMES, theta)}

    def _get_top_weights(self, n: int = 5) -> List[Dict]:
        weights = self.get_learned_weights()
        return sorted(
            ({"feature": k, "weight": v} for k, v in weights.items()),
            key=lambda w: abs(w["weight"]), reverse=True
        )[:n]

    def get_stats(self) -> Dict:
        precision = self.tp_count / max(self.tp_count + self.fp_count, 1)
        return {
            "total_feedback": self.total_feedback,
            "tp_count": self.tp_count,
            "fp_count": self.fp_count,
            "learned_precision": round(precision, 3),
            "top_learned_features": self._get_top_weights(),
            "exploration_coefficient": self.alpha,
            "learning_status": (
                "Bootstrapping (< 10 decisions)" if self.total_feedback < 10 else
                "Learning (10-100 decisions)" if self.total_feedback < 100 else
                "Calibrated (100+ decisions)"
            ),
        }

    def reset(self):
        """Blank-slate reset (demo helper, e.g. before a live judge run)."""
        self.A = np.identity(self.d)
        self.b = np.zeros(self.d)
        self.total_feedback = 0
        self.tp_count = 0
        self.fp_count = 0
        self._save_state()

    # -- Persistence -------------------------------------------------------------

    def _save_state(self):
        state = {
            "A": self.A.tolist(),
            "b": self.b.tolist(),
            "total_feedback": self.total_feedback,
            "tp_count": self.tp_count,
            "fp_count": self.fp_count,
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
        with open(self.state_path, "w") as f:
            json.dump(state, f)

    def _load_state(self):
        if not os.path.exists(self.state_path):
            return
        try:
            with open(self.state_path) as f:
                state = json.load(f)
            A = np.array(state["A"])
            b = np.array(state["b"])
            if A.shape == (self.d, self.d) and b.shape == (self.d,):
                self.A = A
                self.b = b
                self.total_feedback = state.get("total_feedback", 0)
                self.tp_count = state.get("tp_count", 0)
                self.fp_count = state.get("fp_count", 0)
        except Exception:
            pass  # start fresh if state is corrupt or schema changed
