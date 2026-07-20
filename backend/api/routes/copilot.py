"""`/copilot/*` — the Investigation Copilot HTTP surface (ROADMAP Phase 10).

Unlike `/cases/{id}/*`, the Copilot is cross-case, so this is NOT case-scoped;
it only requires an authenticated user, and the engine scopes every action to
*that user's own cases* internally (`copilot.scoping`). It persists an
`ai_interactions` row (and possibly a note via `write_case_note`), so it POSTs
and commits itself — matching the transaction-boundary convention of the other
routes (the orchestration layer only flushes).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from db.models.platform import User
from db.session import get_db
from foundation.auth import get_app_settings, get_current_user
from foundation.config import Settings
from orchestration.agent_loop import AgentLoopError
from orchestration.copilot import engine
from orchestration.copilot.engine import MAX_QUESTION_CHARS
from orchestration.gateway import ExplanationUnavailableError

router = APIRouter(prefix="/copilot", tags=["copilot"])


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)


class AskResponse(BaseModel):
    answered: bool
    answer: str
    interaction_id: int | None
    tools_used: list[str] | None
    rejected_reason: str | None
    iterations: int
    latency_ms: int


@router.post("/ask", response_model=AskResponse)
def ask(
    body: AskRequest,
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_app_settings),
    db: Session = Depends(get_db),
) -> AskResponse:
    """Ask the Copilot a question over your own cases. The answer is grounded
    (cited to tool facts) and re-hydrated with customer names for display; an
    answer that cannot be grounded returns `answered=false` with a reason. 503 if
    the LLM is unconfigured/unreachable; 502 if it could not produce a valid
    structured answer."""
    try:
        result = engine.ask(db, user, body.question, settings=settings)
    except ExplanationUnavailableError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except AgentLoopError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    db.commit()
    return AskResponse(**result.to_dict())
