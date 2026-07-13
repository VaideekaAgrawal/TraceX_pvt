"""
LLM gateway (ROADMAP Phase 8) -- the provider-abstracted, retry/timeout-
aware transport `orchestration.llm_client.call_openrouter` used to do
directly. This is the entire "self-host swap later" surface: every AI
feature (existing account/pattern explanations, Phase 9's Recommendation
Engine, Phase 10's Copilot) calls `generate_completion(...)`, never a
provider SDK directly, so swapping OpenRouter for a self-hosted model later
is a one-place change (`_provider_for`/a new `LLMProvider` implementation),
not a grep-and-replace across every caller.

**No second prompt-level cache is added here.** The existing `orchestration.
llm_client.find_cached_interaction`/`AiInteraction`-row semantic cache
(fact-key-based, e.g. keyed on `account_id`/`alert_id`) already satisfies
the ROADMAP's "caching" checklist item for this phase; a second raw-prompt
cache sitting next to it would risk the two silently diverging (different
TTL/eviction/invalidation semantics for what's supposed to be "the" cached
answer). This gateway handles retry/timeout only.

Failure classification (`ProviderError.retryable`) matters because a
transient network blip and "the API key is wrong" need different handling
upstream -- retrying the latter just burns 3 attempts' worth of latency for
a guaranteed-identical failure.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Protocol

import httpx

from foundation.config import Settings

logger = logging.getLogger(__name__)

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_NOT_CONFIGURED_MESSAGE = "AI explanations not configured. Set openrouter_api_key."

_TIMEOUT_SECONDS = 20.0  # unchanged from the pre-Phase-8 direct call
_MAX_ATTEMPTS = 3
_BASE_DELAY_SECONDS = 0.5
_MAX_DELAY_SECONDS = 4.0

#: HTTP status codes worth retrying -- rate-limited or a transient upstream
#: failure, as opposed to a client-side 4xx (bad request/auth) that will
#: fail identically on every retry.
_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

#: Module-level so tests can monkeypatch this to a no-op and run the retry
#: tests without actually sleeping.
_sleep: Callable[[float], None] = time.sleep


class LLMProvider(Protocol):
    def complete(
        self, prompt: str, *, model: str, max_tokens: int, temperature: float, timeout: float
    ) -> str: ...


class ProviderError(Exception):
    """Raised by an `LLMProvider.complete()` implementation on any failure.
    `retryable` tells the gateway's retry loop whether attempting again is
    worth it."""

    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


class GatewayError(Exception):
    """Public failure surfaced to callers of `generate_completion` -- either
    every retry attempt was exhausted, or the first `ProviderError` was
    non-retryable. Callers catch this exactly where they used to catch
    `orchestration.llm_client.ExplanationUnavailableError` (re-exported
    there as an alias of this class, see that module)."""


class OpenRouterProvider:
    """Ports the pre-Phase-8 direct `httpx.post` call (`orchestration.
    llm_client.call_openrouter`, itself ported from `archive/fund-flow-
    tracker/api/server.py:111-134`) near-verbatim -- same URL, headers,
    request-body shape, 20s timeout -- but classifies failures instead of
    catching a blanket `Exception`, so the gateway's retry loop can tell a
    transient network blip from a permanent misconfiguration."""

    def __init__(self, *, api_key: str) -> None:
        self._api_key = api_key

    def complete(
        self, prompt: str, *, model: str, max_tokens: int, temperature: float, timeout: float
    ) -> str:
        if not self._api_key:
            raise ProviderError(_NOT_CONFIGURED_MESSAGE, retryable=False)

        try:
            response = httpx.post(
                _OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "http://localhost:3000",
                    "X-Title": "TraceX AML",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                },
                timeout=timeout,
            )
        except httpx.TimeoutException as exc:
            raise ProviderError(f"OpenRouter call timed out: {exc}", retryable=True) from exc
        except httpx.HTTPError as exc:
            # Connection-level failure (DNS, refused connection, etc.) --
            # worth retrying, distinct from a non-2xx response the server
            # actually returned.
            raise ProviderError(f"OpenRouter call failed: {exc}", retryable=True) from exc

        if response.status_code in _RETRYABLE_STATUS_CODES:
            raise ProviderError(
                f"OpenRouter returned retryable status {response.status_code}", retryable=True
            )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ProviderError(f"OpenRouter call failed: {exc}", retryable=False) from exc

        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            # `TypeError` covers a plausible-but-malformed shape like
            # `{"choices": [null]}` -- valid JSON, present key/index, but a
            # `None` element raises `TypeError` on the next `["message"]`
            # subscript, not `KeyError`/`IndexError` (code-review finding).
            raise ProviderError(
                f"OpenRouter response malformed: {exc}", retryable=False
            ) from exc
        return str(content).strip()


def _provider_for(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "openrouter":
        return OpenRouterProvider(api_key=settings.openrouter_api_key)
    raise GatewayError(f"unknown llm_provider {settings.llm_provider!r}")


def generate_completion(
    prompt: str,
    *,
    settings: Settings,
    max_tokens: int = 300,
    provider: LLMProvider | None = None,
) -> str:
    """Literal drop-in replacement for the old `orchestration.llm_client.
    call_openrouter(prompt, *, settings, max_tokens=300)` signature -- every
    existing caller's `_call_openrouter(prompt, settings=settings)` call
    keeps working unchanged against this function.

    `temperature=0.3` is passed to the provider here (not hardcoded inside
    `OpenRouterProvider`) -- preserves the exact behavior every existing
    caller (`account_explanation`, `pattern_explanation`) already relies on
    without those callers needing to know or care that temperature is now a
    provider-level parameter.

    `provider`, when given, bypasses `_provider_for(settings)` entirely --
    the seam `scripts/verify_ai_substrate.py` uses to run deterministically
    against a `FakeProvider` when no real API key is configured, and what
    `test_llm_gateway.py` uses to exercise retry/error-classification
    behavior without a real network call.

    Hand-rolled retry (no new dependency, per this repo's own stated
    posture of not adding a dependency before something needs it): up to
    `_MAX_ATTEMPTS`, catching `ProviderError`. A non-retryable error raises
    `GatewayError` immediately; a retryable one sleeps
    `min(_MAX_DELAY_SECONDS, _BASE_DELAY_SECONDS * 2**attempt)` and retries,
    unless it was the last attempt, in which case it also raises
    `GatewayError`."""
    resolved_provider = provider if provider is not None else _provider_for(settings)

    last_exc: ProviderError | None = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            return resolved_provider.complete(
                prompt,
                model=settings.llm_model,
                max_tokens=max_tokens,
                temperature=0.3,
                timeout=_TIMEOUT_SECONDS,
            )
        except ProviderError as exc:
            last_exc = exc
            is_last_attempt = attempt == _MAX_ATTEMPTS - 1
            if not exc.retryable or is_last_attempt:
                logger.warning(
                    "LLM gateway call failed permanently (attempt %d/%d, retryable=%s): %s",
                    attempt + 1, _MAX_ATTEMPTS, exc.retryable, exc,
                )
                raise GatewayError(str(exc)) from exc
            logger.warning(
                "LLM gateway call failed, retrying (attempt %d/%d): %s",
                attempt + 1, _MAX_ATTEMPTS, exc,
            )
            _sleep(min(_MAX_DELAY_SECONDS, _BASE_DELAY_SECONDS * 2**attempt))

    # Unreachable (the loop above always either returns or raises), but
    # satisfies mypy's "function may not return a value" check without a
    # `# type: ignore`.
    assert last_exc is not None
    raise GatewayError(str(last_exc)) from last_exc
