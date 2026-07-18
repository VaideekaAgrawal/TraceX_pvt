"""Case-level auto-narrative — ROADMAP Phase 11.

The executive writeup that goes into an STR/SAR: what the case is, what the
detection found, how the money moved, the network around it, and why it warrants
(or doesn't warrant) a report. It extends the Phase 8/9 substrate to the whole
case rather than one account — same agent loop, same tool catalog, same grounding
contract — so **every figure in the narrative is cited to a tool-computed fact,
and an ungrounded sentence never reaches the document.** A regulator can re-run
the validator against the persisted facts and confirm the writeup invented
nothing.

Multi-account by construction: the case tool catalog is bound to the case, and
the model is told to synthesise across all its linked accounts. The result is a
DRAFT the investigator edits before it becomes a report (`investigation.reporting`
owns the Report lifecycle); this module only produces the grounded prose.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from db.enums import ActorType
from foundation.config import Settings
from orchestration import grounding
from orchestration.agent_loop import run_agent_loop
from orchestration.grounding import GroundingError
from orchestration.tools.catalog import build_tool_catalog

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a bank AML analyst writing the case narrative for a regulatory filing \
(a Suspicious Transaction Report). Write a clear, factual account a compliance \
officer and a regulator will read.

Cover, in order, as the facts support:
1. Background — the case, its accounts, the customer profile(s).
2. What was detected — the typology/typologies and the alerts that fired.
3. The money movement — key inflows/outflows, amounts, counterparties.
4. The network — connected accounts, cycles, mule structure, prior-SAR links.
5. Assessment — why this is (or is not) suspicious, and the recommended action.

Hard rules — enforced by code, not honour:
- You may not state a number you were not handed by a tool. Call the fact tools, \
then cite the exact fact_key and value for every number in every sentence. Each \
tool result is returned as "fact_key": value pairs — cite fact_keys EXACTLY as \
shown (they include the tool and its arguments). Do not compute new figures.
- Refer to customers by customer_id; you are never given names.
- Synthesise across ALL of the case's linked accounts, not just one.

Gather what you need with the tools, then submit the narrative as grounded \
claims (one sentence per claim, each with its citations).
"""


@dataclass
class NarrativeResult:
    """The grounded narrative plus the audit material behind it."""

    narrative: str
    grounded: bool
    facts: dict[str, Any]
    tools_called: list[dict[str, Any]]
    rejected_reasons: list[str] = field(default_factory=list)
    iterations: int = 0
    latency_ms: int = 0


def generate_case_narrative(
    session: Session,
    case_id: str,
    *,
    settings: Settings,
    actor_type: ActorType,
    actor_id: str | None,
) -> NarrativeResult:
    """Generate a grounded, multi-account case narrative. Does NOT persist or
    commit — the reporting layer owns the Report row. Raises
    `ExplanationUnavailableError`/`AgentLoopError` on an LLM failure."""
    catalog = build_tool_catalog(session, case_id, actor_type=actor_type, actor_id=actor_id)
    result = run_agent_loop(
        settings=settings,
        catalog=catalog,
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=f"Write the case narrative for case {case_id}.",
        submit_tool=grounding.submit_tool(),
        submit_tool_name=grounding.SUBMIT_TOOL_NAME,
        # A full multi-account case narrative with a citation per sentence is much
        # longer than a recommendation; the default 4000-token submit budget
        # truncated it to an empty {} (found live). Give it real room.
        submit_max_tokens=8000,
    )

    try:
        claims = grounding.parse_response(result.submission)
    except GroundingError as exc:
        return NarrativeResult(
            narrative="", grounded=False, facts=result.bundle.facts,
            tools_called=result.bundle.tools_called,
            rejected_reasons=[f"unparseable narrative: {exc}"],
            iterations=result.iterations, latency_ms=result.latency_ms,
        )

    gresult = grounding.validate(claims, result.bundle)
    # A partially-grounded narrative still yields the accepted sentences (the
    # investigator edits before filing), but the ungrounded ones are dropped and
    # reported, never shown.
    return NarrativeResult(
        narrative=gresult.narrative(),
        grounded=gresult.ok,
        facts=result.bundle.facts,
        tools_called=result.bundle.tools_called,
        rejected_reasons=[str(r) for r in gresult.rejected],
        iterations=result.iterations,
        latency_ms=result.latency_ms,
    )
