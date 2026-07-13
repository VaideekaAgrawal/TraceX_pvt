"""
`foundation.llm_gateway` -- provider dispatch, retry/backoff, failure
classification (ROADMAP Phase 8). Monkeypatches `_sleep` to a no-op so the
retry tests run fast (real `time.sleep` would otherwise add real seconds
per exhausted-retry test).
"""
from __future__ import annotations

from typing import Any

import httpx
import pytest

from foundation import llm_gateway
from foundation.config import Settings
from foundation.llm_gateway import (
    GatewayError,
    OpenRouterProvider,
    ProviderError,
    generate_completion,
)


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "env": "dev",
        "jwt_secret": "test-secret",
        "openrouter_api_key": "test-key",
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


class _FakeProvider:
    """A minimal `LLMProvider` that fails a configured number of times
    (retryable or not) before succeeding, recording every call."""

    def __init__(self, *, fail_times: int, retryable: bool, result: str = "ok") -> None:
        self.fail_times = fail_times
        self.retryable = retryable
        self.result = result
        self.calls = 0

    def complete(
        self, prompt: str, *, model: str, max_tokens: int, temperature: float, timeout: float
    ) -> str:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise ProviderError("boom", retryable=self.retryable)
        return self.result


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm_gateway, "_sleep", lambda _seconds: None)


def test_provider_for_dispatches_openrouter() -> None:
    settings = _settings(llm_provider="openrouter")
    provider = llm_gateway._provider_for(settings)
    assert isinstance(provider, OpenRouterProvider)


def test_provider_for_unknown_provider_raises_gateway_error() -> None:
    settings = _settings(llm_provider="not-a-real-provider")
    with pytest.raises(GatewayError, match="unknown llm_provider"):
        llm_gateway._provider_for(settings)


def test_generate_completion_uses_injected_provider_without_dispatch() -> None:
    provider = _FakeProvider(fail_times=0, retryable=False)
    result = generate_completion("hello", settings=_settings(), provider=provider)
    assert result == "ok"
    assert provider.calls == 1


def test_retryable_error_is_retried_up_to_max_attempts_then_succeeds() -> None:
    provider = _FakeProvider(fail_times=2, retryable=True)
    result = generate_completion("hello", settings=_settings(), provider=provider)
    assert result == "ok"
    assert provider.calls == 3  # 2 failures + 1 success, within _MAX_ATTEMPTS=3


def test_retryable_error_exhausted_raises_gateway_error() -> None:
    provider = _FakeProvider(fail_times=10, retryable=True)
    with pytest.raises(GatewayError):
        generate_completion("hello", settings=_settings(), provider=provider)
    assert provider.calls == llm_gateway._MAX_ATTEMPTS


def test_non_retryable_error_raises_immediately_without_retry() -> None:
    provider = _FakeProvider(fail_times=10, retryable=False)
    with pytest.raises(GatewayError):
        generate_completion("hello", settings=_settings(), provider=provider)
    assert provider.calls == 1  # no retry attempted


def test_provider_error_is_logged_on_each_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression test (code-review finding): logging was dropped during the
    # extraction from the old orchestration/llm_client.py::call_openrouter
    # (which logged every failure via logger.warning) into
    # foundation/llm_gateway.py -- LLM outages produced zero server-side
    # log signal. Confirm both the retrying-attempt and the final-failure
    # cases each emit a warning. Monkeypatches `llm_gateway.logger.warning`
    # directly rather than relying on `caplog`'s propagation-through-the-
    # logger-hierarchy behavior, which proved order-dependent across the
    # full test suite (passed in isolation, failed when run after other
    # test modules that touch global logging state) -- this is
    # deterministic regardless of what else in the suite has run.
    warnings_logged: list[str] = []
    monkeypatch.setattr(
        llm_gateway.logger, "warning", lambda msg, *args, **kwargs: warnings_logged.append(msg)
    )

    provider = _FakeProvider(fail_times=10, retryable=True)
    with pytest.raises(GatewayError):
        generate_completion("hello", settings=_settings(), provider=provider)
    assert len(warnings_logged) == llm_gateway._MAX_ATTEMPTS


def test_openrouter_provider_missing_api_key_raises_non_retryable() -> None:
    provider = OpenRouterProvider(api_key="")
    with pytest.raises(ProviderError) as exc_info:
        provider.complete(
            "hello", model="m", max_tokens=10, temperature=0.3, timeout=1.0
        )
    assert exc_info.value.retryable is False
    assert "not configured" in str(exc_info.value)


def test_openrouter_provider_missing_key_surfaces_via_gateway() -> None:
    with pytest.raises(GatewayError, match="not configured"):
        generate_completion("hello", settings=_settings(openrouter_api_key=""))


class _FakeResponse:
    def __init__(self, status_code: int, body: dict[str, Any]) -> None:
        self.status_code = status_code
        self._body = body

    def json(self) -> dict[str, Any]:
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("bad status", request=None, response=self)  # type: ignore[arg-type]


@pytest.mark.parametrize("status_code", [429, 500, 502, 503, 504])
def test_openrouter_provider_classifies_retryable_status_codes(
    monkeypatch: pytest.MonkeyPatch, status_code: int
) -> None:
    monkeypatch.setattr(
        llm_gateway.httpx, "post", lambda *a, **k: _FakeResponse(status_code, {})
    )
    provider = OpenRouterProvider(api_key="test-key")
    with pytest.raises(ProviderError) as exc_info:
        provider.complete("hello", model="m", max_tokens=10, temperature=0.3, timeout=1.0)
    assert exc_info.value.retryable is True


def test_openrouter_provider_classifies_other_4xx_as_non_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm_gateway.httpx, "post", lambda *a, **k: _FakeResponse(401, {}))
    provider = OpenRouterProvider(api_key="test-key")
    with pytest.raises(ProviderError) as exc_info:
        provider.complete("hello", model="m", max_tokens=10, temperature=0.3, timeout=1.0)
    assert exc_info.value.retryable is False


def test_openrouter_provider_null_choice_element_is_non_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Regression test (code-review finding, PLAUSIBLE): a response body
    # like {"choices": [null]} is valid JSON with the key/index present,
    # but the null element raises TypeError on the next ["message"]
    # subscript -- not KeyError/IndexError. Previously uncaught, this
    # propagated past the retry loop and past callers' `except
    # ExplanationUnavailableError` as an unhandled crash.
    monkeypatch.setattr(
        llm_gateway.httpx, "post", lambda *a, **k: _FakeResponse(200, {"choices": [None]})
    )
    provider = OpenRouterProvider(api_key="test-key")
    with pytest.raises(ProviderError) as exc_info:
        provider.complete("hello", model="m", max_tokens=10, temperature=0.3, timeout=1.0)
    assert exc_info.value.retryable is False


def test_openrouter_provider_malformed_body_is_non_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        llm_gateway.httpx, "post", lambda *a, **k: _FakeResponse(200, {"choices": []})
    )
    provider = OpenRouterProvider(api_key="test-key")
    with pytest.raises(ProviderError) as exc_info:
        provider.complete("hello", model="m", max_tokens=10, temperature=0.3, timeout=1.0)
    assert exc_info.value.retryable is False


def test_openrouter_provider_success_strips_content(monkeypatch: pytest.MonkeyPatch) -> None:
    body = {"choices": [{"message": {"content": "  hello world  "}}]}
    monkeypatch.setattr(llm_gateway.httpx, "post", lambda *a, **k: _FakeResponse(200, body))
    provider = OpenRouterProvider(api_key="test-key")
    result = provider.complete("hello", model="m", max_tokens=10, temperature=0.3, timeout=1.0)
    assert result == "hello world"


def test_openrouter_provider_timeout_is_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise_timeout(*a: object, **k: object) -> None:
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(llm_gateway.httpx, "post", _raise_timeout)
    provider = OpenRouterProvider(api_key="test-key")
    with pytest.raises(ProviderError) as exc_info:
        provider.complete("hello", model="m", max_tokens=10, temperature=0.3, timeout=1.0)
    assert exc_info.value.retryable is True
