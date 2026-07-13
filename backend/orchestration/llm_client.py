"""
Cache-lookup and generate-and-persist tail shared by `orchestration.
account_explanation`/`orchestration.pattern_explanation` -- ROADMAP Phase 6
extraction, narrowed further in Phase 8.

**Transport now lives in `foundation.llm_gateway`.** This module used to
also own the direct OpenRouter `httpx` call (`call_openrouter`); as of
ROADMAP Phase 8, that call is `foundation.llm_gateway.generate_completion`
(provider-abstracted, retry/timeout-aware). `call_openrouter`/
`ExplanationUnavailableError`/`_NOT_CONFIGURED_MESSAGE` are re-exported here
under their original names purely so `account_explanation.py`/
`pattern_explanation.py` (and every test that imports them from here) keep
working unchanged -- see each re-export below for exactly what it aliases.

`find_cached_interaction`/`generate_and_persist_explanation` are unchanged
in behavior from Phase 6/7 (this module's actual remaining scope): the
shared `ai_interactions` cache-lookup and the timed-call-plus-persist tail
`explain_account`/`explain_pattern` both need. `generate_and_persist_
explanation` takes the actual LLM call as a `call_fn` parameter rather than
calling the gateway itself, so each caller still passes its OWN module-local
`_call_openrouter` reference -- this is what keeps each module's existing
`monkeypatch.setattr(account_explanation, "_call_openrouter", ...)`-style
test seam working unchanged: `call_fn` is resolved in the CALLER's frame
(picking up whatever that name currently refers to there, including a
monkeypatched value) before this function ever sees it.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from db.enums import ActorType, AiAgent
from db.models.orchestration import AiInteraction
from db.repositories.orchestration import AiInteractionRepository
from foundation.config import Settings
from foundation.llm_gateway import _NOT_CONFIGURED_MESSAGE  # noqa: F401
from foundation.llm_gateway import GatewayError as ExplanationUnavailableError  # noqa: F401
from foundation.llm_gateway import generate_completion as call_openrouter  # noqa: F401

# `call_openrouter`/`ExplanationUnavailableError`/`_NOT_CONFIGURED_MESSAGE`
# are re-exported at module level (not just imported for internal use) --
# `account_explanation.py`/`pattern_explanation.py` import
# `call_openrouter as _call_openrouter` from here, and both modules'
# existing tests reference `ExplanationUnavailableError`/
# `_NOT_CONFIGURED_MESSAGE` off the `account_explanation`/`pattern_
# explanation` module objects (which re-export them again from here) --
# see those modules' own docstrings. `foundation.llm_gateway.
# generate_completion`'s signature (`prompt, *, settings, max_tokens=300,
# provider=None`) is a strict superset of the old `call_openrouter(prompt,
# *, settings, max_tokens=300)` signature, so this alias is a literal
# drop-in replacement -- every existing `call_fn(prompt, settings=settings)`
# call site needs zero changes.


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
    tools_called: list[dict[str, Any]] | None = None,
    redacted: bool = False,
) -> AiInteraction:
    """Timed LLM call + `AiInteraction` persistence -- the shared tail of
    `account_explanation.explain_account`/`pattern_explanation.
    explain_pattern`'s near-identical flows (code-review finding, Phase 6).

    Calls `call_fn(prompt, settings=settings)` rather than the gateway
    directly -- see module docstring for why (preserves each caller's own
    monkeypatch-at-`_call_openrouter` test seam). Raises
    `ExplanationUnavailableError` on failure, propagated from `call_fn` and
    NOT caught here -- the caller decides how to surface it (matching
    `call_openrouter`'s own "the caller decides" contract). Does NOT commit
    -- caller owns the transaction boundary, matching every other
    investigation/orchestration-layer function.

    `tools_called`/`redacted` (ROADMAP Phase 8, both new, both defaulted so
    the two existing callers are byte-for-byte unaffected if they don't
    pass them): threaded straight through to `AiInteractionRepository.
    create(...)` -- `tools_called` records which fixed-catalog tools (see
    `orchestration.tools`) a future agent called to assemble `facts`
    (`None`/empty for the current two callers, which assemble facts via
    direct repository reads, not the tool layer); `redacted` records
    whether `prompt` passed through `foundation.pii_redaction.redact_facts`
    before reaching the LLM (replaces this call's previous hardcoded
    `redacted=False`)."""
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
        tools_called=tools_called,
        redacted=redacted,
        latency_ms=latency_ms,
        actor_type=actor_type,
        actor_id=actor_id,
    )
