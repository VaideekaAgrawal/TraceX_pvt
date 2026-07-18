"""`/model-metrics` — model & detection governance surface (ROADMAP Phase 12).

Makes the platform's maturity claims inspectable: which model version is live and
what it scored, how each rule's confidence has moved under real verdicts (the
Phase 12 feedback loop — `detection.rules.feedback`), what the RL bandit has
learned, and the durable precision implied by resolved-case outcomes. Read-only
and gated to `ADMIN_COMPLIANCE` — model governance is a compliance function
(`SYSTEM_DEVELOPMENT_PLAN.md` §5), not an investigator view.

Everything here is read from persisted state, so the numbers survive a restart —
notably the precision figure comes from the `detection_feedback` rows, not the
bandit's process-lifetime tp/fp counters (which reset each boot).
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.enums import CaseResolution, UserRole
from db.models.platform import User
from db.repositories.detection import (
    DetectionFeedbackRepository,
    ModelRunRepository,
    RlArmStateRepository,
    RuleDefinitionRepository,
)
from db.session import get_db
from detection.rl.bandit import GLOBAL_ARM_ID, LinUCBAgent
from foundation.auth import require_role

router = APIRouter(tags=["governance"])


class ModelInfo(BaseModel):
    # `model_name`/`model_type` mirror the DB column names; opt out of Pydantic
    # v2's protected `model_` namespace so they aren't renamed/warned.
    model_config = {"protected_namespaces": ()}

    model_name: str
    model_type: str
    version: str
    trained_at: str | None
    dataset_hash: str | None
    metrics: dict | None
    has_artifact: bool
    active: bool


class RuleInfo(BaseModel):
    rule_id: str
    name: str
    tier: int
    confidence: float
    enabled: bool


class FeatureWeight(BaseModel):
    feature: str
    weight: float


class RlInfo(BaseModel):
    arm_id: str
    updated_at: str | None
    top_features: list[FeatureWeight]


class FeedbackSummary(BaseModel):
    total: int
    true_positive: int
    false_positive: int
    enhanced_monitoring: int
    #: TP / (TP + FP) over resolved cases; None until at least one TP/FP exists.
    precision: float | None


class ModelMetricsResponse(BaseModel):
    models: list[ModelInfo]
    rules: list[RuleInfo]
    rl: RlInfo
    feedback: FeedbackSummary


def _top_features(agent: LinUCBAgent, n: int = 8) -> list[FeatureWeight]:
    weights = agent.get_learned_weights()
    ranked = sorted(weights.items(), key=lambda kv: abs(kv[1]), reverse=True)
    return [FeatureWeight(feature=k, weight=v) for k, v in ranked[:n]]


@router.get("/model-metrics", response_model=ModelMetricsResponse)
def get_model_metrics(
    _: User = Depends(require_role(UserRole.ADMIN_COMPLIANCE)),
    db: Session = Depends(get_db),
) -> ModelMetricsResponse:
    """Governance snapshot: active model runs, per-rule learned confidence
    (noisiest first), the RL bandit's top learned features, and durable
    verdict-based precision."""
    models = [
        ModelInfo(
            model_name=m.model_name,
            model_type=str(m.model_type),
            version=m.version,
            trained_at=m.trained_at.isoformat() if m.trained_at else None,
            dataset_hash=m.dataset_hash,
            metrics=m.metrics,
            has_artifact=bool(m.artifact_path and os.path.exists(m.artifact_path)),
            active=m.active,
        )
        for m in ModelRunRepository(db).list_active()
    ]

    # Enabled rules, lowest confidence first — the rules the feedback loop has
    # flagged as noisiest surface at the top, where a reviewer wants them.
    rules = sorted(
        (
            RuleInfo(
                rule_id=r.rule_id, name=r.name, tier=r.tier,
                confidence=r.confidence, enabled=r.enabled,
            )
            for r in RuleDefinitionRepository(db).list_enabled()
        ),
        key=lambda r: r.confidence,
    )

    agent = LinUCBAgent(db)
    arm_state = RlArmStateRepository(db).get(GLOBAL_ARM_ID)
    rl = RlInfo(
        arm_id=GLOBAL_ARM_ID,
        updated_at=arm_state.updated_at.isoformat() if arm_state and arm_state.updated_at else None,
        top_features=_top_features(agent),
    )

    counts = DetectionFeedbackRepository(db).counts_by_verdict()
    tp = counts.get(str(CaseResolution.TRUE_POSITIVE_SAR), 0)
    fp = counts.get(str(CaseResolution.FALSE_POSITIVE), 0)
    mon = counts.get(str(CaseResolution.ENHANCED_MONITORING), 0)
    feedback = FeedbackSummary(
        total=sum(counts.values()),
        true_positive=tp,
        false_positive=fp,
        enhanced_monitoring=mon,
        precision=round(tp / (tp + fp), 3) if (tp + fp) else None,
    )

    return ModelMetricsResponse(models=models, rules=rules, rl=rl, feedback=feedback)
