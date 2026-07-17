"""Agent loop mechanics — ROADMAP Phase 9.

The loop is driven by a *fake* OpenAI client (monkeypatched `_make_client`) so
these exercise the real dispatch/bundle/forced-submit logic without a network
call. Tool calls are real `ChatCompletionMessageFunctionToolCall` instances
because the loop narrows on that type."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from openai.types.chat import ChatCompletionMessageFunctionToolCall
from openai.types.chat.chat_completion_message_function_tool_call import Function
from sqlalchemy.orm import Session

from db.enums import ActorType
from foundation.config import Settings
from orchestration import agent_loop
from orchestration.tools.catalog import build_tool_catalog

CASE_ID = "CASE-REC-1"
SUBMIT_NAME = "submit_test"
_SUBMIT_TOOL = {
    "type": "function",
    "function": {
        "name": SUBMIT_NAME,
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
            "additionalProperties": False,
        },
    },
}


def _tool_call(call_id: str, name: str, arguments: str) -> ChatCompletionMessageFunctionToolCall:
    return ChatCompletionMessageFunctionToolCall(
        id=call_id, type="function", function=Function(name=name, arguments=arguments)
    )


def _response(tool_calls: list[ChatCompletionMessageFunctionToolCall]) -> SimpleNamespace:
    message = SimpleNamespace(content=None, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class _FakeClient:
    """Returns pre-scripted responses in order; records the calls made."""

    def __init__(self, responses: list[SimpleNamespace]) -> None:
        self._responses = responses
        self.calls: list[dict[str, Any]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return self._responses[len(self.calls) - 1]


def _settings() -> Settings:
    # A key so the loop proceeds; no network call happens (client is faked).
    return Settings(openrouter_api_key="test-key")


def _install(monkeypatch: pytest.MonkeyPatch, responses: list[SimpleNamespace]) -> _FakeClient:
    client = _FakeClient(responses)
    monkeypatch.setattr(agent_loop, "_make_client", lambda settings: client)
    return client


def test_loop_dispatches_a_tool_then_returns_the_submission(
    case_with_layering_alert: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _install(
        monkeypatch,
        [
            # Phase 1: call a fact tool, then a no-tool-call turn ends gathering.
            _response([_tool_call("c1", "get_case_summary", "{}")]),
            _response([]),
            # Phase 2: forced submit.
            _response([_tool_call("c2", SUBMIT_NAME, '{"ok": true}')]),
        ],
    )
    catalog = build_tool_catalog(
        case_with_layering_alert, CASE_ID, actor_type=ActorType.INVESTIGATOR, actor_id="U1"
    )

    result = agent_loop.run_agent_loop(
        settings=_settings(), catalog=catalog,
        system_prompt="sys", user_prompt="go",
        submit_tool=_SUBMIT_TOOL, submit_tool_name=SUBMIT_NAME,
    )

    assert result.submission == {"ok": True}
    # The fact tool's output was folded into the bundle and recorded.
    assert len(result.bundle) > 0
    assert result.bundle.tool_names == ["get_case_summary"]
    # The final (forced-submit) call carried the tool result back as a tool message.
    assert any(m["role"] == "tool" for m in client.calls[-1]["messages"])
    # Phase 2 forces the submit tool, while still declaring the full tool set (so
    # the history's fact-tool references stay valid).
    final = client.calls[-1]
    assert final["tool_choice"]["function"]["name"] == SUBMIT_NAME
    assert SUBMIT_NAME in [t["function"]["name"] for t in final["tools"]]


def test_tool_error_is_fed_back_not_raised(
    case_with_layering_alert: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An out-of-scope account makes dispatch raise ToolError; the loop must feed
    # that back to the model (so it can correct) and still complete on submit.
    _install(
        monkeypatch,
        [
            _response([_tool_call("c1", "get_account_facts", '{"account_id": "NOT-IN-CASE"}')]),
            _response([]),
            _response([_tool_call("c2", SUBMIT_NAME, '{"ok": true}')]),
        ],
    )
    catalog = build_tool_catalog(
        case_with_layering_alert, CASE_ID, actor_type=ActorType.INVESTIGATOR, actor_id="U1"
    )
    result = agent_loop.run_agent_loop(
        settings=_settings(), catalog=catalog,
        system_prompt="sys", user_prompt="go",
        submit_tool=_SUBMIT_TOOL, submit_tool_name=SUBMIT_NAME,
    )
    assert result.submission == {"ok": True}
    # The failed tool contributed no facts to the bundle.
    assert len(result.bundle) == 0


def test_missing_api_key_raises_before_any_call(
    case_with_layering_alert: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from orchestration.gateway import ExplanationUnavailableError

    catalog = build_tool_catalog(
        case_with_layering_alert, CASE_ID, actor_type=ActorType.INVESTIGATOR, actor_id="U1"
    )
    with pytest.raises(ExplanationUnavailableError):
        agent_loop.run_agent_loop(
            settings=Settings(openrouter_api_key=""), catalog=catalog,
            system_prompt="sys", user_prompt="go",
            submit_tool=_SUBMIT_TOOL, submit_tool_name=SUBMIT_NAME,
        )
