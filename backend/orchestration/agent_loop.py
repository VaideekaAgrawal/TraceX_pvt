"""The agentic tool-calling loop — ROADMAP Phase 9 (shared substrate).

Phase 8 built the *pieces* an agent needs (the tool catalog, the grounding
contract, the PII gate) but no agent that runs them: `account_explanation` and
`pattern_explanation` are single-shot calls over server-assembled facts. Phase 9
is the first consumer that lets the model *choose* which tools to call, so this
is where the loop lives. It is deliberately agnostic to what the model is being
asked to produce — the Recommendation Engine and (Phase 10) the Copilot both
drive it, passing their own system prompt and their own final-answer schema.

## The loop, and why it is shaped this way — TWO phases

    Phase 1 (gather): tools = catalog.schemas() only, tool_choice="auto"
        loop: model calls fact tools -> dispatch, fold into FactBundle, feed the
              flattened fact_key:value view back; stop when it makes no tool call
    Phase 2 (answer): tools = [submit_tool], tool_choice forces submit_tool
        one call; its arguments ARE the structured answer, validated by the caller

The two phases exist because offering the submit tool *during* gathering makes
the model call it early with empty arguments — Sonnet does not enforce a tool's
argument schema any more than it honours `response_format` (docs/METRICS.md §13),
so a premature submit returns `{}` and the whole answer is lost with no error.
Withholding submit until an explicit, forced final turn is what makes the
submission reliably well-formed. Found live on this phase's first real run.

Three properties are load-bearing and none of them is a prompt instruction:

1. **Every fact the model sees has passed the PII egress gate.** Results are
   folded in via `ToolCatalog.dispatch`, which gates each payload at the point of
   egress (Phase 8 moved the gate there precisely so a tool-calling loop could not
   bypass it). This module never touches raw tool internals.

2. **The final answer is a forced, schema-shaped tool call.** Phase 2 forces the
   submit tool specifically, so the model cannot trail off into unvalidated prose;
   its arguments are the structured answer the caller then validates.

3. **The FactBundle the caller gets back is exactly what grounds the answer.**
   The same bundle the model saw (as flattened fact_key:value pairs) is what the
   caller's validator checks and what gets persisted to `ai_interactions.facts` —
   the equality Phase 8's grounding module is built around.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Protocol

import openai
from openai.types.chat import ChatCompletionMessageFunctionToolCall
from sqlalchemy.orm import Session  # noqa: F401  (kept for symmetry / future use)

from foundation.config import Settings
from orchestration.gateway import ExplanationUnavailableError
from orchestration.grounding import FactBundle, flatten_tool_result
from orchestration.tools.catalog import ToolError

logger = logging.getLogger(__name__)

# Matches the gateway's single-shot call. Low temperature: the model restates and
# selects among server-computed facts, it is not being creative.
_TEMPERATURE = 0.3
# A loop makes several calls; a touch more headroom than the single-shot 20s.
_TIMEOUT_SECONDS = 30.0
_MAX_RETRIES = 2
# Enough for a real investigation to gather evidence across a few accounts and
# still submit, without letting a confused model spin forever (each iteration is
# a billed round-trip). Measured target: real cases submit in 4-8 iterations.
_DEFAULT_MAX_ITERATIONS = 12
_DEFAULT_MAX_TOKENS = 1500
# The forced final answer needs far more room than a gather turn: a real
# multi-recommendation submission cites many facts with verbose call-prefixed
# keys, and 1500 tokens truncated it mid-JSON — which comes back as an empty
# `{}` (finish_reason=length), losing the whole answer with no error. Verified
# live (docs/METRICS.md). Gather turns keep the smaller budget: their output is
# just tool-call arguments. Cost is only ever tokens actually generated.
_SUBMIT_MAX_TOKENS = 4000


class ToolDispatcher(Protocol):
    """The catalog contract the loop actually needs — nothing more. Both Phase 9's
    case-bound `ToolCatalog` and the Copilot's cross-case `CopilotCatalog` satisfy
    it structurally, so the loop is reused across both without either a shared base
    class or a `# type: ignore` at the call site."""

    def schemas(self) -> list[dict[str, Any]]: ...

    def dispatch(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]: ...


class AgentLoopError(Exception):
    """The loop could not produce a structured submission (the model never
    called the submit tool even when forced, or its arguments were unparseable).
    Distinct from a *rejected* answer, which is a normal downstream outcome."""


@dataclass
class AgentResult:
    """What one full loop produced. `submission` is the raw parsed arguments of
    the submit tool — the caller's own schema, which the caller validates."""

    submission: dict[str, Any]
    bundle: FactBundle
    iterations: int
    latency_ms: int


def _make_client(settings: Settings) -> openai.OpenAI:
    """A client against `settings.llm_base_url`. Constructed here rather than
    reusing `gateway.call_llm`'s inline client because this is a multi-turn
    tool-calling call, not the gateway's single-shot completion — but the
    connection params (timeout, retries, OpenRouter attribution headers) are kept
    identical on purpose so both paths behave the same against the provider."""
    return openai.OpenAI(
        api_key=settings.openrouter_api_key,
        base_url=settings.llm_base_url,
        timeout=_TIMEOUT_SECONDS,
        max_retries=_MAX_RETRIES,
        default_headers={"HTTP-Referer": "http://localhost:3000", "X-Title": "TraceX AML"},
    )


def _parse_arguments(raw: str | None) -> dict[str, Any]:
    """A tool call's `function.arguments` JSON string -> dict. An empty/missing
    argument string means a no-argument tool call (e.g. `get_case_summary`)."""
    if not raw or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AgentLoopError(f"tool arguments were not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise AgentLoopError("tool arguments were not a JSON object")
    return parsed


def run_agent_loop(
    *,
    settings: Settings,
    catalog: ToolDispatcher,
    system_prompt: str,
    user_prompt: str,
    submit_tool: dict[str, Any],
    submit_tool_name: str,
    max_iterations: int = _DEFAULT_MAX_ITERATIONS,
    max_tokens: int = _DEFAULT_MAX_TOKENS,
) -> AgentResult:
    """Drive the model through fact-gathering tool calls to a forced structured
    submission. Returns the parsed submission plus the FactBundle it was grounded
    on. Raises `ExplanationUnavailableError` on a provider failure (same contract
    as the gateway) and `AgentLoopError` if no submission could be obtained."""
    if not settings.openrouter_api_key:
        raise ExplanationUnavailableError(
            "AI recommendations not configured. Set openrouter_api_key."
        )

    client = _make_client(settings)
    bundle = FactBundle()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    start = time.monotonic()

    # ── Phase 1: gather facts ────────────────────────────────────────────
    # ONLY the fact tools are offered, with tool_choice="auto" so the model
    # stops when it has what it needs (a turn with no tool call). The submit
    # tool is deliberately withheld here: offering it during gathering under a
    # forced/required choice makes the model fire it early with empty arguments
    # (Sonnet does not enforce the tool arg schema — the same class of issue as
    # its silent response_format drop, docs/METRICS.md §13). Separating "gather"
    # from "answer" is what makes the final submission reliably well-formed.
    gather_iterations = 0
    for _ in range(max_iterations):
        message = _create(
            client, settings, messages, tools=catalog.schemas(),
            tool_choice="auto", max_tokens=max_tokens,
        )
        tool_calls = _function_tool_calls(message)
        if not tool_calls:
            break  # the model is done gathering
        gather_iterations += 1
        _record_assistant_turn(messages, message, tool_calls)
        for tc in tool_calls:
            _dispatch_into(bundle, messages, catalog, tc)

    # ── Phase 2: forced structured answer ────────────────────────────────
    # Now the model MUST answer via the submit tool and nothing else. With only
    # this tool available and an explicit instruction, the arguments come back
    # complete rather than the empty {} an early, unforced submit produced.
    messages.append(
        {
            "role": "user",
            "content": (
                f"You have gathered enough facts. Now call {submit_tool_name} with your "
                f"complete final answer, citing fact_keys exactly as shown in the tool results."
            ),
        }
    )
    # Declare the FULL tool set here, not just the submit tool — the phase-1
    # history contains assistant tool_calls referencing the fact tools, and a
    # request whose `tools` list omits tools the conversation already referenced
    # makes the provider return an empty-argument tool call (verified live: the
    # identical forced submit yields complete arguments with the full list and
    # `{}` with a submit-only list). `tool_choice` still forces submit, so the
    # model must answer through it regardless of what else is declared.
    message = _create(
        client, settings, messages, tools=[*catalog.schemas(), submit_tool],
        tool_choice={"type": "function", "function": {"name": submit_tool_name}},
        max_tokens=_SUBMIT_MAX_TOKENS,
    )
    submit_calls = [
        tc for tc in _function_tool_calls(message) if tc.function.name == submit_tool_name
    ]
    if not submit_calls:
        raise AgentLoopError("model did not call the submit tool when forced to")

    submission = _parse_arguments(submit_calls[0].function.arguments)
    # An empty `{}` is never a valid submission — both answer schemas require at
    # least one item. It is the signature of a truncated (finish_reason=length)
    # tool call whose incomplete JSON normalised to empty. Fail LOUD here: a
    # silently-empty submission surfaces downstream as "0 accepted, 0 rejected",
    # which reads like a clean pass rather than the lost answer it actually is.
    if not submission:
        raise AgentLoopError(
            "submit tool returned empty arguments (likely truncated) — "
            "raise the answer token budget"
        )
    latency_ms = int((time.monotonic() - start) * 1000)
    return AgentResult(
        submission=submission, bundle=bundle,
        iterations=gather_iterations + 1, latency_ms=latency_ms,
    )


def _create(
    client: openai.OpenAI,
    settings: Settings,
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]],
    tool_choice: Any,
    max_tokens: int,
) -> Any:
    """One chat-completions call, with the provider-error contract the gateway
    uses. Returns the response message."""
    try:
        response = client.chat.completions.create(
            model=settings.llm_model,
            messages=messages,  # type: ignore[arg-type]
            tools=tools,  # type: ignore[arg-type]
            tool_choice=tool_choice,
            temperature=_TEMPERATURE,
            max_tokens=max_tokens,
        )
    except openai.APIError as exc:
        logger.warning("agent loop LLM call failed: %s", exc)
        raise ExplanationUnavailableError(f"Could not generate recommendation: {exc}") from exc
    if not response.choices:
        raise ExplanationUnavailableError("Could not generate recommendation: no choices returned")
    return response.choices[0].message


def _function_tool_calls(message: Any) -> list[ChatCompletionMessageFunctionToolCall]:
    """Only function tool calls — we register nothing else, and narrowing to the
    concrete type keeps the rest of the loop type-safe."""
    return [
        tc
        for tc in (message.tool_calls or [])
        if isinstance(tc, ChatCompletionMessageFunctionToolCall)
    ]


def _record_assistant_turn(
    messages: list[dict[str, Any]],
    message: Any,
    tool_calls: list[ChatCompletionMessageFunctionToolCall],
) -> None:
    """Append the assistant turn WITH its tool calls, before any tool results —
    the provider requires each tool result to follow the message that asked for it."""
    messages.append(
        {
            "role": "assistant",
            "content": message.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in tool_calls
            ],
        }
    )


def _dispatch_into(
    bundle: FactBundle,
    messages: list[dict[str, Any]],
    catalog: ToolDispatcher,
    tc: ChatCompletionMessageFunctionToolCall,
) -> None:
    """Dispatch one fact tool (PII-gated at the catalog), fold it into the bundle,
    and feed the FLATTENED, call-prefixed fact_key:value view back to the model —
    the exact keys the validator resolves, not the raw nested JSON (otherwise the
    model cites `node_count` for a fact stored as
    `get_ego_graph_summary(...).node_count` and every correct claim is rejected;
    found live, see flatten_tool_result). A ToolError is reported back as a tool
    result so the model can correct course, not raised."""
    name = tc.function.name
    arguments = _parse_arguments(tc.function.arguments)
    try:
        result = catalog.dispatch(name, arguments)
        bundle.add_tool_result(name, result, arguments)
        content = json.dumps(flatten_tool_result(name, result, arguments), default=str)
    except ToolError as exc:
        content = json.dumps({"error": str(exc)})
    messages.append({"role": "tool", "tool_call_id": tc.id, "content": content})
