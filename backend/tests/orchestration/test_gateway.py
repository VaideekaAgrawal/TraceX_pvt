"""
Gateway tests (ROADMAP Phase 8, committed decision 6).

These drive `orchestration.gateway.call_llm` against a **real local HTTP
server** speaking the OpenAI chat-completions wire format, rather than
monkeypatching the `openai` client. That's deliberate: the whole point of
decision 6 is that any OpenAI-compatible `base_url` works, and a mocked client
would prove nothing about the request we actually put on the wire. This exercises
the SDK for real — serialization, headers, status handling, retries — with no
network dependency and no API key.

The error-mapping tests are the load-bearing ones. Every failure path must raise
`ExplanationUnavailableError`, because the callers' "never persist a failed call
as a cached success" contract (the Phase 5 landmine) depends on this function
raising rather than returning error text that would get written to
`ai_interactions` and served back as `cached: True` forever.
"""
from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest

from foundation.config import Settings
from orchestration import gateway


class _StubState:
    """What the stub should do, and what it saw. Rebound per test."""

    status: int = 200
    body: dict[str, Any] = {}
    seen_path: str | None = None
    seen_headers: dict[str, str] = {}
    seen_payload: dict[str, Any] = {}
    request_count: int = 0


def _make_handler(state: type[_StubState]) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 -- BaseHTTPRequestHandler's API
            state.request_count += 1
            state.seen_path = self.path
            state.seen_headers = {k.lower(): v for k, v in self.headers.items()}
            length = int(self.headers.get("Content-Length", "0"))
            state.seen_payload = json.loads(self.rfile.read(length) or b"{}")

            payload = json.dumps(state.body).encode()
            self.send_response(state.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args: Any) -> None:  # silence stderr noise
            return

    return Handler


@pytest.fixture
def stub() -> Iterator[type[_StubState]]:
    state = type("State", (_StubState,), {})
    server = HTTPServer(("127.0.0.1", 0), _make_handler(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]  # bound to 127.0.0.1 above; port 0 -> OS-assigned
    state.base_url = f"http://127.0.0.1:{port}/v1"  # type: ignore[attr-defined]
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()


def _settings(stub: type[_StubState], **overrides: Any) -> Settings:
    kwargs: dict[str, Any] = {
        "env": "dev",
        "jwt_secret": "test-secret",
        "openrouter_api_key": "test-key",
        "llm_base_url": stub.base_url,  # type: ignore[attr-defined]
        "llm_model": "test/model",
    }
    kwargs.update(overrides)
    return Settings(**kwargs)


def _completion(content: str | None) -> dict[str, Any]:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 0,
        "model": "test/model",
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": content},
             "finish_reason": "stop"}
        ],
    }


def test_call_llm_returns_stripped_content(stub: type[_StubState]) -> None:
    stub.body = _completion("  An explanation.  \n")
    assert gateway.call_llm("why?", settings=_settings(stub)) == "An explanation."


def test_call_llm_sends_expected_request(stub: type[_StubState]) -> None:
    stub.body = _completion("ok")
    gateway.call_llm("why is A1 risky?", settings=_settings(stub), max_tokens=123)

    # Hits the OpenAI-compatible chat-completions path off our base_url.
    assert stub.seen_path == "/v1/chat/completions"
    assert stub.seen_headers["authorization"] == "Bearer test-key"
    assert stub.seen_payload["model"] == "test/model"
    assert stub.seen_payload["max_tokens"] == 123
    # Low temperature is a guardrail property, not a preference: these outputs
    # restate server-computed facts and must not get creative with them.
    assert stub.seen_payload["temperature"] == gateway._TEMPERATURE
    assert stub.seen_payload["messages"] == [{"role": "user", "content": "why is A1 risky?"}]


def test_call_llm_default_max_tokens_leaves_room_for_a_full_explanation(
    stub: type[_StubState],
) -> None:
    # Regression test (ROADMAP Phase 8). The inherited default was 300, which
    # was a latent truncation bug invisible to every pre-Phase-8 test because
    # they all mocked the call and never saw a real completion length. Measured
    # live: the real `account_explanation` prompt draws ~201 visible tokens from
    # Sonnet 4.5 and ~370 from Opus 4.8 — so 300 silently cut Opus off
    # mid-sentence. Anything at or below ~400 will start truncating real
    # explanations again; this asserts the headroom, not the exact number.
    stub.body = _completion("ok")
    gateway.call_llm("why?", settings=_settings(stub))
    assert stub.seen_payload["max_tokens"] == gateway._DEFAULT_MAX_TOKENS
    assert gateway._DEFAULT_MAX_TOKENS >= 500


def test_call_llm_without_api_key_raises_and_never_calls_out(stub: type[_StubState]) -> None:
    settings = _settings(stub, openrouter_api_key="")
    with pytest.raises(gateway.ExplanationUnavailableError, match=gateway._NOT_CONFIGURED_MESSAGE):
        gateway.call_llm("why?", settings=settings)
    assert stub.request_count == 0


def test_call_llm_maps_server_error_to_explanation_unavailable(stub: type[_StubState]) -> None:
    stub.status = 500
    stub.body = {"error": {"message": "upstream exploded"}}
    with pytest.raises(gateway.ExplanationUnavailableError):
        gateway.call_llm("why?", settings=_settings(stub))


def test_call_llm_maps_rate_limit_to_explanation_unavailable(stub: type[_StubState]) -> None:
    stub.status = 429
    stub.body = {"error": {"message": "slow down"}}
    with pytest.raises(gateway.ExplanationUnavailableError):
        gateway.call_llm("why?", settings=_settings(stub))


def test_call_llm_retries_retryable_status_before_giving_up(stub: type[_StubState]) -> None:
    # SDK-native retry (`max_retries`), which the raw-httpx version this
    # replaced did not have at all. 1 initial attempt + _MAX_RETRIES retries.
    stub.status = 500
    stub.body = {"error": {"message": "upstream exploded"}}
    with pytest.raises(gateway.ExplanationUnavailableError):
        gateway.call_llm("why?", settings=_settings(stub))
    assert stub.request_count == gateway._MAX_RETRIES + 1


def test_call_llm_empty_content_raises_rather_than_caching_an_empty_answer(
    stub: type[_StubState],
) -> None:
    # A well-formed 200 with no usable text is still a failure. If this returned
    # "" instead of raising, the caller would persist an empty string as a
    # perfectly good explanation and serve it back as `cached: True` forever.
    stub.body = _completion("   ")
    with pytest.raises(gateway.ExplanationUnavailableError, match="empty response"):
        gateway.call_llm("why?", settings=_settings(stub))


def test_call_llm_null_content_raises(stub: type[_StubState]) -> None:
    stub.body = _completion(None)
    with pytest.raises(gateway.ExplanationUnavailableError, match="empty response"):
        gateway.call_llm("why?", settings=_settings(stub))


def test_call_llm_no_choices_raises(stub: type[_StubState]) -> None:
    stub.body = {"id": "x", "object": "chat.completion", "created": 0,
                 "model": "test/model", "choices": []}
    with pytest.raises(gateway.ExplanationUnavailableError, match="no choices"):
        gateway.call_llm("why?", settings=_settings(stub))
