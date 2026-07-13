"""
The LLM gateway — the single place this codebase talks to a model.

ROADMAP Phase 8, committed decision 6. Replaces `orchestration/llm_client.py`'s
raw-`httpx` POST to OpenRouter's chat-completions URL. The call now goes through
the `openai` SDK pointed at `settings.llm_base_url`, because the OpenAI
chat-completions schema *is* the portable provider interface — OpenRouter,
vLLM, TGI and Ollama all speak it — so a bank-mandated on-prem swap is a
`base_url` change rather than a rewrite. There is deliberately **no** further
provider-abstraction layer on top: a lowest-common-denominator wrapper would
buy nothing the SDK does not already give and would forfeit tool-calling and
structured outputs, which the rest of Phase 8 depends on.

What this module is NOT (yet): the tool catalog, the grounding contract, and
the PII egress gate are separate Phase 8 modules (`orchestration/tools/`,
`orchestration/grounding.py`, `orchestration/redaction.py`). This one only
knows how to make the call. As under the old `llm_client`, every caller remains
independently responsible for its own guardrail property — facts assembled
server-side, never attacker-controllable free text (decision 10). This module
cannot enforce that; it does not know what is safe to put in a prompt.

Also holds `find_cached_interaction`/`generate_and_persist_explanation`, the
shared cache-lookup and generate-and-persist tail that
`account_explanation.explain_account` and `pattern_explanation.explain_pattern`
both need (extracted in Phase 6; carried over unchanged). Response-level
caching over `ai_interactions` is the entire caching story — provider-native
*prompt* caching is deliberately not designed for, since it is vendor-specific
and would forfeit exactly the portability decision 6 exists to buy (decision 7).

`generate_and_persist_explanation` takes the LLM call as a `call_fn` parameter
rather than calling `call_llm` itself, so each caller passes its own
module-local `_call_llm` reference. That is what keeps each module's
`monkeypatch.setattr(account_explanation, "_call_llm", ...)` test seam working:
`call_fn` is resolved in the *caller's* frame — picking up a monkeypatched
value if one is set — before this function ever sees it.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

import openai
from sqlalchemy.orm import Session

from db.enums import ActorType, AiAgent
from db.models.orchestration import AiInteraction
from db.repositories.orchestration import AiInteractionRepository
from foundation.config import Settings

logger = logging.getLogger(__name__)

_NOT_CONFIGURED_MESSAGE = "AI explanations not configured. Set openrouter_api_key."

# Matches the raw-httpx call this replaces, so the Phase 5/6 explanation
# behavior is unchanged by the port. Low temperature because these outputs are
# meant to restate server-computed facts, not to be creative about them.
_TEMPERATURE = 0.3
_TIMEOUT_SECONDS = 20.0
# SDK-native retry, replacing the old code's "no retry at all". The SDK retries
# connection errors, 408/409/429 and 5xx with exponential backoff; anything
# still failing after this surfaces as a typed exception below. Note the
# effective wall-clock ceiling is _TIMEOUT_SECONDS x (1 + _MAX_RETRIES).
_MAX_RETRIES = 2


class ExplanationUnavailableError(Exception):
    """Raised by `call_llm` when no explanation could be generated (missing API
    key, network failure, rate limit, non-2xx response, malformed body).

    Every caller catches this and returns a visible message WITHOUT persisting
    a cached/successful-looking record for it. This is the Phase 5 landmine and
    it is load-bearing: the original design "failed open" by returning the error
    text as if it were the explanation, which then got written to
    `ai_interactions` and served back as `cached: True` forever after —
    indistinguishable from a real explanation. A transient outage could become
    the permanently cached answer. Keep the raise; do not soften this to a
    return value."""


def call_llm(prompt: str, *, settings: Settings, max_tokens: int = 300) -> str:
    """Single chat-completions call through the `openai` SDK against
    `settings.llm_base_url`.

    Raises `ExplanationUnavailableError` on any failure rather than returning
    an error string — the caller is the layer that decides how a failure is
    surfaced and (crucially) not cached; this function only knows how to make
    the call."""
    if not settings.openrouter_api_key:
        raise ExplanationUnavailableError(_NOT_CONFIGURED_MESSAGE)

    client = openai.OpenAI(
        api_key=settings.openrouter_api_key,
        base_url=settings.llm_base_url,
        timeout=_TIMEOUT_SECONDS,
        max_retries=_MAX_RETRIES,
        # OpenRouter attributes traffic with these; harmless against any other
        # OpenAI-compatible base_url, which ignores unknown headers.
        default_headers={"HTTP-Referer": "http://localhost:3000", "X-Title": "TraceX AML"},
    )

    try:
        response = client.chat.completions.create(
            model=settings.llm_model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=_TEMPERATURE,
        )
    except openai.APIStatusError as exc:  # includes RateLimitError (429)
        logger.warning("LLM call failed with status %s: %s", exc.status_code, exc)
        raise ExplanationUnavailableError(f"Could not generate explanation: {exc}") from exc
    except openai.APIError as exc:  # APIConnectionError, APITimeoutError, ...
        logger.warning("LLM call failed: %s", exc)
        raise ExplanationUnavailableError(f"Could not generate explanation: {exc}") from exc

    # A well-formed 2xx with no usable content is still a failure, and must
    # take the same not-cached path as a network error rather than persisting
    # an empty string as a valid explanation.
    if not response.choices:
        raise ExplanationUnavailableError("Could not generate explanation: no choices returned")
    content = response.choices[0].message.content
    if content is None or not content.strip():
        raise ExplanationUnavailableError("Could not generate explanation: empty response")
    return content.strip()


def find_cached_interaction(
    repo: AiInteractionRepository, case_id: str, agent: AiAgent, *, key_field: str, key_value: str
) -> AiInteraction | None:
    """Most-recent-wins cache lookup over `ai_interactions`, filtered in Python
    to `interaction.facts[key_field] == key_value` (see
    `AiInteractionRepository.list_for_case_and_agent`'s docstring for why this
    filtering step can't be pushed into SQL). Shared by
    `account_explanation.explain_account` (`key_field="account_id"`) and
    `pattern_explanation.explain_pattern` (`key_field="alert_id"`) — both cache
    in the same `ai_interactions`/`AiAgent.RECOMMENDATION` namespace but on
    disjoint keys, so sharing this lookup carries no collision risk."""
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
    """Timed LLM call + `AiInteraction` persistence — the shared tail of
    `account_explanation.explain_account`/`pattern_explanation.explain_pattern`.

    Calls `call_fn(prompt, settings=settings)` rather than `call_llm` directly;
    see the module docstring for why (it preserves each caller's monkeypatch
    seam). Raises `ExplanationUnavailableError` on failure, propagated from
    `call_fn` and NOT caught here — the caller decides how to surface it, which
    is what keeps a failed call from being persisted as a cached success. Does
    NOT commit: the caller owns the transaction boundary, matching every other
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
