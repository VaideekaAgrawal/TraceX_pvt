"""
Shared OpenRouter chat-completions call — extracted from
`orchestration.account_explanation` (ROADMAP Phase 6:
`orchestration.pattern_explanation` is the second real caller of this exact
HTTP-call logic, meeting this codebase's own "promote on second real caller"
convention already used for `HIGH_PAGERANK_THRESHOLD`/`CLOSING_REWARD`/
`list_account_ids_for_case`/`require_case_scoped_account`).

**This is NOT the Phase 8 AI substrate/LLM gateway.** Repeating
`account_explanation.py`'s own scope-boundary language verbatim: there is NO
provider abstraction, NO tool-calling, NO guardrail middleware here — a
direct `httpx` POST to OpenRouter. Phase 8 may replace or wrap this module;
it should not itself grow gateway-shaped features later (if it starts
needing multi-provider routing, tool calls, or free-text input, that need
belongs to Phase 8, not an extension of this file).

Every caller of `call_openrouter` is independently responsible for its own
guardrail property (facts assembled server-side only, never attacker-
controllable free text) — this module only knows how to make the call, not
what's safe to put in the prompt that reaches it.

Also holds `find_cached_interaction`/`generate_and_persist_explanation` --
the shared cache-lookup and generate-and-persist tail
`account_explanation.explain_account`/`pattern_explanation.explain_pattern`
both need (code-review finding, Phase 6: those two flows were near-verbatim
duplicates of each other; extracted here on the same "second real caller"
precedent as `call_openrouter` itself, one layer up). `generate_and_persist_
explanation` takes the actual LLM call as a `call_fn` parameter rather than
calling `call_openrouter` itself, so each caller still passes its OWN
module-local `_call_openrouter` reference — this is what keeps each
module's existing `monkeypatch.setattr(account_explanation,
"_call_openrouter", ...)`-style test seam working unchanged: `call_fn` is
resolved in the CALLER's frame (picking up whatever that name currently
refers to there, including a monkeypatched value) before this function ever
sees it.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

import httpx
from sqlalchemy.orm import Session

from db.enums import ActorType, AiAgent
from db.models.orchestration import AiInteraction
from db.repositories.orchestration import AiInteractionRepository
from foundation.config import Settings

logger = logging.getLogger(__name__)

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_NOT_CONFIGURED_MESSAGE = "AI explanations not configured. Set openrouter_api_key."


class ExplanationUnavailableError(Exception):
    """Raised by `call_openrouter` when no explanation could be generated
    (missing API key, network failure, non-2xx response, malformed body).
    Every caller catches this and returns a visible message WITHOUT
    persisting a cached/successful-looking record for it (code-review
    finding, Phase 5, `orchestration.account_explanation`: the previous
    "fails open by returning the error text" design got that error text
    written to `ai_interactions` and then served back as `cached: True`,
    indistinguishable from a real explanation, on every subsequent
    non-force call — a transient outage could get permanently "cached" as
    the answer). This same contract applies to every caller of this
    module, not just the account-explanation path."""


def call_openrouter(prompt: str, *, settings: Settings, max_tokens: int = 300) -> str:
    """Single OpenRouter chat-completions call (temperature=0.3, 20s
    timeout) — ported near-verbatim from `archive/fund-flow-tracker/api/
    server.py::_call_openrouter` via `orchestration.account_explanation`'s
    Phase-5 port. Raises `ExplanationUnavailableError` on any failure
    (missing key, network error, non-2xx response, malformed body) instead
    of returning an error string — the caller is the layer that decides how
    a failure is surfaced/not-cached; this function only knows how to make
    the call."""
    if not settings.openrouter_api_key:
        raise ExplanationUnavailableError(_NOT_CONFIGURED_MESSAGE)
    try:
        response = httpx.post(
            _OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {settings.openrouter_api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost:3000",
                "X-Title": "TraceX AML",
            },
            json={
                "model": settings.llm_model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0.3,
            },
            timeout=20.0,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return str(content).strip()
    except Exception as exc:  # noqa: BLE001 -- narrowed to ExplanationUnavailableError below
        logger.warning("OpenRouter call failed: %s", exc)
        raise ExplanationUnavailableError(f"Could not generate explanation: {exc}") from exc


def find_cached_interaction(
    repo: AiInteractionRepository, case_id: str, agent: AiAgent, *, key_field: str, key_value: str
) -> AiInteraction | None:
    """Most-recent-wins cache lookup over `ai_interactions`, filtered in
    Python to `interaction.facts[key_field] == key_value` (see
    `AiInteractionRepository.list_for_case_and_agent`'s docstring for why
    this filtering step can't be pushed into SQL). Shared by
    `account_explanation.explain_account` (`key_field="account_id"`) and
    `pattern_explanation.explain_pattern` (`key_field="alert_id"`) -- both
    cache in the same `ai_interactions`/`AiAgent.RECOMMENDATION` namespace
    but on disjoint keys, so no collision risk from sharing this lookup."""
    matching = [
        interaction
        for interaction in repo.list_for_case_and_agent(case_id, agent)
        if interaction.facts is not None and interaction.facts.get(key_field) == key_value
    ]
    if not matching:
        return None
    return max(matching, key=lambda interaction: interaction.created_at)


def generate_and_persist_explanation(
    session: Session,
    *,
    call_fn: Callable[..., str],
    prompt: str,
    settings: Settings,
    case_id: str,
    facts: dict[str, Any],
    actor_type: ActorType,
    actor_id: str,
    rule_anchors: dict[str, Any] | None = None,
) -> AiInteraction:
    """Timed LLM call + `AiInteraction` persistence -- the shared tail of
    `account_explanation.explain_account`/`pattern_explanation.
    explain_pattern`'s near-identical flows (code-review finding, Phase 6).

    Calls `call_fn(prompt, settings=settings)` rather than `call_openrouter`
    directly -- see module docstring for why (preserves each caller's own
    monkeypatch-at-`_call_openrouter` test seam). Raises
    `ExplanationUnavailableError` on failure, propagated from `call_fn` and
    NOT caught here -- the caller decides how to surface it (matching
    `call_openrouter`'s own "the caller decides" contract). Does NOT commit
    -- caller owns the transaction boundary, matching every other
    investigation/orchestration-layer function."""
    start = time.monotonic()
    explanation = call_fn(prompt, settings=settings)
    latency_ms = int((time.monotonic() - start) * 1000)

    return AiInteractionRepository(session).create(
        agent=AiAgent.RECOMMENDATION,
        case_id=case_id,
        user_id=actor_id,
        request_text=prompt,
        facts=facts,
        rule_anchors=rule_anchors,
        response_text=explanation,
        model=settings.llm_model,
        model_provider=settings.llm_provider,
        redacted=False,
        latency_ms=latency_ms,
        actor_type=actor_type,
        actor_id=actor_id,
    )
