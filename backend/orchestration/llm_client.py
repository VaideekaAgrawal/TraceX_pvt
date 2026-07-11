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
"""
from __future__ import annotations

import logging

import httpx

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
