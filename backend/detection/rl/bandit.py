"""
LinUCB Contextual Bandit — Adaptive Investigation Queue.

State: 16-dim account context vector (`build_context`, see below).
Action: recommend this account for next investigation.
Reward: +1.0 (TP confirmed) | -0.3 (FP) | 0.0 (not investigated).

Maintains a d x d precision matrix A and reward vector b. Ranking picks the
highest UCB score; feedback updates A/b online in O(d^2). Ported from
`archive/fund-flow-tracker/services/rl/bandit.py`.

Two persistence changes from the archive (ROADMAP Phase 3, the landmine
this port exists to fix): (1) `A`/`b` are no longer written to a local JSON
file (`data/rl_state.json` -- silently wiped on any non-durable-filesystem
restart) but to `rl_arm_state` via `RlArmStateRepository.upsert`, called at
the same point the archive called `_save_state()` (end of every `update()`)
-- loaded via the repository at construction instead of reading a file. (2)
Single fixed `arm_id="global"` (`docs/RL_USP.md` line 110: "LinUCB
parameters -- one set per arm context (we treat as single arm, context
varies)"; true multi-armed-per-pattern-type is a documented "6 months
later" roadmap item, not this phase).

Judgment call: `total_feedback`/`tp_count`/`fp_count` (interpretability-only
counters, not part of the actual learned model — `RlArmState`'s own
docstring: "the bandit's A/b matrices are all that's needed to resume
learning") have no columns on `rl_arm_state` to persist into; they reset to
0 on each fresh `LinUCBAgent` instance rather than being silently dropped or
requiring a schema change out of this phase's scope. `get_stats()` is
therefore process-lifetime-scoped, not all-time — a real, deliberate
trade-off documented here for anyone extending stats later.

Do not conflate the 16-dim context vector this module builds with the
28-dim ML feature vector (`backend/detection/features.py::FeatureExtractor`)
that feeds `AnomalyDetector`/`FraudClassifier`. This one is a downstream
summary built from ensemble *outputs*.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import numpy as np
from sqlalchemy.orm import Session

from db.enums import ActorType
from db.repositories.detection import RlArmStateRepository

GLOBAL_ARM_ID = "global"


class LinUCBAgent:
    """
    Linear Upper Confidence Bound contextual bandit for investigation
    prioritisation. Reference: Li et al., "A Contextual-Bandit Approach to
    Personalized News Article Recommendation", WWW 2010. Adapted for AML
    investigation triage.
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

    def __init__(
        self,
        session: Session,
        *,
        arm_id: str = GLOBAL_ARM_ID,
        alpha: float = 1.0,
        actor_type: ActorType = ActorType.SYSTEM,
        actor_id: str | None = None,
    ):
        self.session = session
        self.repo = RlArmStateRepository(session)
        self.arm_id = arm_id
        self.d = len(self.FEATURE_NAMES)
        self.alpha = alpha
        self.actor_type = actor_type
        self.actor_id = actor_id

        self.A = np.identity(self.d)
        self.b = np.zeros(self.d)

        # Process-lifetime interpretability counters -- see module docstring.
        self.total_feedback = 0
        self.tp_count = 0
        self.fp_count = 0

        self._load_state()

    # -- Core LinUCB --------------------------------------------------------

    def score(self, context: np.ndarray) -> tuple[float, float, float]:
        """Returns (expected_reward, uncertainty, ucb_score) for a context vector."""
        x = context.reshape(-1, 1)
        A_inv = np.linalg.inv(self.A)
        theta = A_inv @ self.b

        expected = (theta.T @ x).item()
        uncertainty = float(np.sqrt(max((x.T @ A_inv @ x).item(), 0.0)))
        ucb = expected + self.alpha * uncertainty
        return expected, uncertainty, ucb

    def update(self, context: np.ndarray, reward: float) -> None:
        """Online update after investigator feedback. O(d^2) -- microseconds."""
        x = context.reshape(-1, 1)
        self.A += x @ x.T
        self.b += reward * x.reshape(-1)
        self.total_feedback += 1
        if reward > 0:
            self.tp_count += 1
        elif reward < 0:
            self.fp_count += 1
        self._save_state()

    def rank_accounts(self, accounts: list[dict[str, Any]]) -> list[dict[str, Any]]:
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

    def receive_feedback(
        self, account_id: str, context: np.ndarray, is_true_positive: bool
    ) -> dict[str, Any]:
        """Called when investigator closes a case with a TP/FP verdict."""
        reward = 1.0 if is_true_positive else -0.3
        self.update(context, reward)
        return {
            "account_id": account_id,
            "is_true_positive": is_true_positive,
            "reward": reward,
            "timestamp": datetime.now(UTC).isoformat(),
            "learned_weights_snapshot": self._get_top_weights(),
        }

    # -- Feature Building (the 16-dim RL context vector) --------------------

    def build_context(self, acc: dict[str, Any]) -> np.ndarray:
        """Convert an account feature dict (built from ensemble *outputs* --
        risk_score, anomaly_score, fraud_probability, pattern flags, role,
        plus a few raw signals) into a normalised 16-dim context vector."""
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

    def get_learned_weights(self) -> dict[str, float]:
        """Current learned weight per feature -- fully interpretable."""
        A_inv = np.linalg.inv(self.A)
        theta = A_inv @ self.b
        return {name: round(float(w), 4) for name, w in zip(self.FEATURE_NAMES, theta, strict=True)}

    def _get_top_weights(self, n: int = 5) -> list[dict[str, Any]]:
        weights = self.get_learned_weights()
        entries: list[dict[str, Any]] = [
            {"feature": k, "weight": v} for k, v in weights.items()
        ]
        return sorted(entries, key=lambda w: abs(float(w["weight"])), reverse=True)[:n]

    def get_stats(self) -> dict[str, Any]:
        """Process-lifetime stats -- see module docstring's judgment-call
        note on why total_feedback/tp_count/fp_count aren't durable."""
        precision = self.tp_count / max(self.tp_count + self.fp_count, 1)
        return {
            "total_feedback": self.total_feedback,
            "tp_count": self.tp_count,
            "fp_count": self.fp_count,
            "learned_precision": round(precision, 3),
            "top_learned_features": self._get_top_weights(),
            "exploration_coefficient": self.alpha,
            "learning_status": (
                "Bootstrapping (< 10 decisions)" if self.total_feedback < 10
                else "Learning (10-100 decisions)" if self.total_feedback < 100
                else "Calibrated (100+ decisions)"
            ),
        }

    def reset(self) -> None:
        """Blank-slate reset (demo helper, e.g. before a live judge run)."""
        self.A = np.identity(self.d)
        self.b = np.zeros(self.d)
        self.total_feedback = 0
        self.tp_count = 0
        self.fp_count = 0
        self._save_state()

    # -- Persistence (DB-backed, replaces the archive's local JSON file) --------

    def _save_state(self) -> None:
        self.repo.upsert(
            arm_id=self.arm_id,
            a_matrix=self.A.tolist(),
            b_vector=self.b.tolist(),
            actor_type=self.actor_type,
            actor_id=self.actor_id,
        )
        self.session.commit()

    def _load_state(self) -> None:
        state = self.repo.get(self.arm_id)
        if state is None:
            return
        A = np.array(state.a_matrix)
        b = np.array(state.b_vector)
        if A.shape == (self.d, self.d) and b.shape == (self.d,):
            self.A = A
            self.b = b
        # else: shape mismatch (e.g. FEATURE_NAMES changed) -- start fresh
        # rather than crash, matching the archive's "corrupt/schema-changed
        # state -> fresh start" fallback.
