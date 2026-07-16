"""`/cases/{case_id}/recommendations` — the Recommendation Engine HTTP surface
(ROADMAP Phase 9).

Both routes are case-scoped via `require_case_access` (the same boundary the L1/L2
surfaces use) and both persist an `ai_interactions` row, so both are POSTs and both
`db.commit()` themselves — matching `api.routes.cases`' transaction-boundary
convention (the `orchestration` functions they call only flush).

`generate` runs the agentic reasoning loop, so it is a real (billed) LLM call, not
a cheap read — POST makes that side effect honest. `challenge` appends an
investigator's cross-question to the same audited interaction thread.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from db.models.investigation import Case
from db.models.platform import User
from db.session import get_db
from foundation.auth import (
    actor_type_for_role,
    get_app_settings,
    get_current_user,
    require_case_access,
)
from foundation.config import Settings
from orchestration.agent_loop import AgentLoopError
from orchestration.gateway import ExplanationUnavailableError
from orchestration.recommendation import engine
from orchestration.recommendation.engine import MAX_CHALLENGE_CHARS

router = APIRouter(prefix="/cases", tags=["recommendations"])


# ── Response models ──────────────────────────────────────────────────────


class RegulatoryAnchorModel(BaseModel):
    fatf: str
    india: str


class RecommendationModel(BaseModel):
    action_id: str
    title: str
    description: str
    narrative: str
    confidence: float
    rank: int
    typologies: list[str]
    regulatory_anchor: RegulatoryAnchorModel
    rule_anchor: list[dict[str, Any]]
    cited_fact_keys: list[str]


class RejectedModel(BaseModel):
    action_id: str
    reason: str


class RecommendationsResponse(BaseModel):
    case_id: str
    recommendations: list[RecommendationModel]
    rejected: list[RejectedModel]
    interaction_id: int | None
    iterations: int
    latency_ms: int


class ChallengeRequest(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_CHALLENGE_CHARS)


class ChallengeResponse(BaseModel):
    case_id: str
    answered: bool
    narrative: str
    interaction_id: int | None
    rejected_reason: str | None
    iterations: int
    latency_ms: int


# ── Routes ───────────────────────────────────────────────────────────────


@router.post("/{case_id}/recommendations", response_model=RecommendationsResponse)
def generate_recommendations(
    case: Case = Depends(require_case_access),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_app_settings),
    db: Session = Depends(get_db),
) -> RecommendationsResponse:
    """Generate ranked, grounded next-step recommendations for the case. Returns
    an empty list (200) when no alerts have fired — there is nothing to ground a
    recommendation on. 503 if the LLM is unconfigured/unreachable; 502 if the
    model could not produce a valid structured answer."""
    try:
        result = engine.generate_recommendations(
            db,
            case.case_id,
            settings=settings,
            actor_type=actor_type_for_role(user.role),
            actor_id=user.user_id,
        )
    except ExplanationUnavailableError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except AgentLoopError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    db.commit()
    return RecommendationsResponse(**result.to_dict())


@router.post("/{case_id}/recommendations/challenge", response_model=ChallengeResponse)
def challenge_recommendation(
    body: ChallengeRequest,
    case: Case = Depends(require_case_access),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_app_settings),
    db: Session = Depends(get_db),
) -> ChallengeResponse:
    """Cross-question the engine: an investigator challenges a recommendation and
    the engine defends (or concedes) with grounded, cited facts, appended to the
    same audited interaction thread. An answer that cannot be grounded is not
    shown — `answered=false` with a reason, never an ungrounded rebuttal."""
    try:
        result = engine.answer_challenge(
            db,
            case.case_id,
            body.question,
            settings=settings,
            actor_type=actor_type_for_role(user.role),
            actor_id=user.user_id,
        )
    except ExplanationUnavailableError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except AgentLoopError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    db.commit()
    return ChallengeResponse(**result.to_dict())
