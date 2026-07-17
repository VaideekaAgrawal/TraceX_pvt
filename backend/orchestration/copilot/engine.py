"""The Investigation Copilot engine — ROADMAP Phase 10.

`ask()` is the whole interaction: resolve the user's case scope, run the Phase 9
agent loop over the Copilot's investigator-scoped catalog, validate the answer
with the Phase 8 grounding contract, re-hydrate `customer_id -> name` for display,
and persist an audited `ai_interactions` row.

The ordering is the security story, and it is deliberate:

    tools return customer_id (never a name)          <- PII gate holds here
    model reasons + cites over customer_id
    grounding validates claims against the bundle    <- on the tokenised text
    re-hydrate customer_id -> name for the reply      <- display boundary only
    persist the TOKENISED narrative + facts           <- PII-free at rest

So the name never crosses to the model (provable), the grounding guarantee is
checked on exactly what the model saw, and the persisted record stays auditable
and free of names. An answer that cannot be grounded is not shown — `answered=
False` with a reason, never an ungrounded reply (the Phase 5 landmine stays
fixed: a failed/ungrounded interaction is never persisted as a clean success).

Does NOT commit — the caller owns the transaction boundary (a `write_case_note`
tool call only becomes durable when the route commits).
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy.orm import Session

from db.enums import ActorType, AiAgent
from db.models.platform import User
from db.repositories.orchestration import AiInteractionRepository
from foundation.auth import actor_type_for_role
from foundation.config import Settings
from orchestration import grounding
from orchestration.agent_loop import run_agent_loop
from orchestration.grounding import GroundingError

from . import rehydration, scoping
from .catalog import CopilotCatalog

logger = logging.getLogger(__name__)

# The investigator's own question is trusted free text (an authenticated user,
# not the attacker-controllable narration/notes decision 10 keeps out of prompts).
# Capped anyway to bound prompt-injection surface; the answer is grounding-gated
# regardless of what the question says.
MAX_QUESTION_CHARS = 1000

_SYSTEM_PROMPT = """\
You are the Investigation Copilot for a bank AML investigator. You help them across \
their own cases: finding and summarising cases, reporting what changed, answering \
grounded questions about a case's accounts and money flow, and recording notes they \
dictate.

Hard rules — enforced by code, not honour:
- You can only see the user's own cases. Every case tool takes a case_id and will \
error if it is not one of their cases (use list_my_cases to find them).
- Refer to customers by customer_id. You are never given customer names; do not \
guess or invent one.
- You may not state a number you were not handed by a tool. Call tools, then cite \
the exact fact_key and value for every number. Each tool result is returned as \
"fact_key": value pairs — cite fact_keys EXACTLY as shown. Do not compute new figures.
- Only use write_case_note to save something the investigator explicitly asked you \
to note. You cannot escalate, close, or reassign cases — those decisions stay with \
the investigator.

Gather what you need with tools, then submit your answer as grounded claims.
"""


@dataclass
class CopilotResult:
    answered: bool
    answer: str
    interaction_id: int | None = None
    tools_used: list[str] | None = None
    rejected_reason: str | None = None
    iterations: int = 0
    latency_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def ask(
    session: Session,
    user: User,
    question: str,
    *,
    settings: Settings,
) -> CopilotResult:
    """Answer an investigator's Copilot question over their own cases. Raises
    `ExplanationUnavailableError` (LLM unconfigured/unreachable) or `AgentLoopError`
    (no valid structured answer) — never persists a failed call as a success."""
    trimmed = (question or "").strip()[:MAX_QUESTION_CHARS]
    if not trimmed:
        return CopilotResult(answered=False, answer="", rejected_reason="empty question")

    accessible = scoping.accessible_case_ids(session, user)
    if not accessible:
        # Nothing to work on — don't spend a model call to say so.
        return CopilotResult(
            answered=False, answer="",
            rejected_reason="you have no cases assigned to you",
        )

    actor_type: ActorType = actor_type_for_role(user.role)
    catalog = CopilotCatalog(session, user, accessible)

    result = run_agent_loop(
        settings=settings,
        catalog=catalog,  # CopilotCatalog satisfies the ToolDispatcher protocol
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=trimmed,
        submit_tool=grounding.submit_tool(),
        submit_tool_name=grounding.SUBMIT_TOOL_NAME,
    )

    try:
        claims = grounding.parse_response(result.submission)
    except GroundingError as exc:
        return CopilotResult(
            answered=False, answer="", rejected_reason=f"unparseable answer: {exc}",
            iterations=result.iterations, latency_ms=result.latency_ms,
        )

    gresult = grounding.validate(claims, result.bundle)
    if not gresult.ok:
        return CopilotResult(
            answered=False, answer="",
            rejected_reason="; ".join(str(r) for r in gresult.rejected),
            iterations=result.iterations, latency_ms=result.latency_ms,
        )

    # The grounded narrative still speaks in customer_id (what the model saw and
    # what we persist). Re-hydrate names ONLY for the reply to the investigator.
    token_narrative = gresult.narrative()
    name_map = rehydration.build_name_map(
        session, rehydration.collect_customer_ids(result.bundle.facts)
    )
    display_narrative = rehydration.rehydrate(token_narrative, name_map)

    interaction = AiInteractionRepository(session).create(
        agent=AiAgent.COPILOT,
        case_id=None,  # cross-case interaction
        user_id=user.user_id,
        request_text=trimmed,
        facts=result.bundle.facts,
        rule_anchors=None,
        tools_called=result.bundle.tools_called,
        response_text=token_narrative,  # tokenised (customer_id), PII-free at rest
        model=settings.llm_model,
        model_provider=settings.llm_provider,
        redacted=False,
        latency_ms=result.latency_ms,
        actor_type=actor_type,
        actor_id=user.user_id,
    )

    return CopilotResult(
        answered=True,
        answer=display_narrative,
        interaction_id=interaction.id,
        tools_used=result.bundle.tool_names,
        iterations=result.iterations,
        latency_ms=result.latency_ms,
    )
