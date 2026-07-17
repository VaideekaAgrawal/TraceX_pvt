"""The Recommendation Engine orchestration — ROADMAP Phase 9, slices 3-5.

Ties the phase together:

    rule_grounding.ground_case   -> what fired, and which actions are eligible
    agent_loop.run_agent_loop    -> the model gathers facts and picks gated actions
    grounding.validate           -> every rationale claim must be grounded
    ranking.score_action         -> deterministic, evidence-weighted ordering
    AiInteractionRepository       -> persisted with facts + rule_anchors + tools

The guardrail is a **code path, not a prompt**. Three independent checks each
reject before a recommendation reaches the investigator:

  1. `action_id` must be in the *eligible* catalog (gated by what actually fired).
     The submit schema also constrains it by enum — belt (schema) and braces (this).
  2. Every claim in the rationale must pass Phase 8's grounding validator against
     the fact bundle the tools produced. An ungrounded number sinks the whole
     recommendation, not just the sentence.
  3. The whole prompt-bound fact bundle is asserted PII-free before persistence
     (the tool layer already gated each result at egress; this is the belt-and-
     braces second assertion the gateway also does).

Recommendations persist as `ai_interactions` rows (`agent=RECOMMENDATION`) — no
new table. `facts`/`rule_anchors`/`tools_called` are the auditable receipt: a
regulator can re-run the validator against `facts` and read the rule thresholds
in `rule_anchors` without trusting the model at all.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from db.enums import ActorType, AiAgent
from db.models.orchestration import AiInteraction
from db.repositories.orchestration import AiInteractionRepository
from foundation.config import Settings
from orchestration import grounding
from orchestration.agent_loop import AgentResult, run_agent_loop
from orchestration.grounding import GroundingError
from orchestration.redaction import assert_no_pii_egress
from orchestration.tools.catalog import build_tool_catalog

from . import action_catalog, ranking, rule_grounding
from .rule_grounding import CaseGrounding

logger = logging.getLogger(__name__)

# Investigator free-text challenges are capped rather than trusted wholesale.
# Per decision 10, attacker-controllable free text stays out of prompts; a
# cross-question is authored by an *authenticated investigator*, a different (and
# far weaker) threat than narration/notes injected by the party under
# investigation — but a length cap costs nothing and bounds prompt-injection
# surface. The output is still gated by the grounding validator regardless.
#
# Public so the HTTP layer enforces the SAME limit (`api.routes.recommendations`
# uses it as the request field's max_length) — otherwise the route would accept a
# longer question that this then silently truncates, losing the investigator's
# words with no signal. One source of truth, enforced at the edge AND here.
MAX_CHALLENGE_CHARS = 1000


@dataclass
class Recommendation:
    """One accepted, ranked recommendation as returned to the API/investigator."""

    action_id: str
    title: str
    description: str
    narrative: str
    confidence: float
    rank: int
    typologies: list[str]
    regulatory_anchor: dict[str, str]
    rule_anchor: list[dict[str, Any]]
    cited_fact_keys: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RecommendationResult:
    case_id: str
    recommendations: list[Recommendation] = field(default_factory=list)
    rejected: list[dict[str, str]] = field(default_factory=list)
    interaction_id: int | None = None
    iterations: int = 0
    latency_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "recommendations": [r.to_dict() for r in self.recommendations],
            "rejected": self.rejected,
            "interaction_id": self.interaction_id,
            "iterations": self.iterations,
            "latency_ms": self.latency_ms,
        }


# ── prompts ────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are the Recommendation Engine of an anti-money-laundering (AML) investigation \
platform used by bank compliance analysts. Your job is to recommend the next \
investigative or disposition steps for one case, and to justify each with evidence.

Hard rules — these are enforced by code, not honour:
- You may ONLY recommend actions from the eligible action list below. Any other \
action_id is rejected outright.
- You may not state a number you were not handed by a tool. Call tools to gather \
facts, and cite the exact fact_key and value for every number in your rationale. \
Each tool result is returned to you as a set of "fact_key": value pairs — cite \
fact_keys EXACTLY as they appear there (they include the tool and its arguments, \
e.g. get_account_facts(account_id=ACC1).total_in). Do not compute new figures — \
if a percentage or ratio matters, a tool provides it.
- Prefer get_ego_graph_summary over get_ego_graph unless you need a specific edge.
- Keep each rationale to a few grounded sentences aimed at a compliance officer.

Workflow: call the fact tools you need, then call submit_recommendations with one \
entry per recommended action, ordered by how strongly the evidence supports it. \
The final ranking and confidence shown to the investigator are computed \
separately from the evidence; your job is to choose sound actions and ground them.

Eligible actions for this case:
{action_menu}
"""

_CHALLENGE_SYSTEM_PROMPT = """\
You are the Recommendation Engine of an AML investigation platform. An \
investigator is challenging a prior recommendation on this case. Answer their \
question directly and defend (or, if the evidence does not support it, concede) \
the recommendation — using only facts you gather from tools, citing the exact \
fact_key and value for every number. Each tool result is returned as "fact_key": \
value pairs; cite fact_keys EXACTLY as shown (they include the tool and its \
arguments). Do not invent figures. Submit your answer via submit_explanation as \
grounded claims, with at least one claim.
"""


def _action_menu(eligible: list[action_catalog.Action]) -> str:
    lines = []
    for a in eligible:
        anchor = a.regulatory_anchor
        lines.append(
            f"- {a.action_id}: {a.title}. {a.description} "
            f"[FATF: {anchor.fatf or 'n/a'}; India: {anchor.india or 'n/a'}]"
        )
    return "\n".join(lines)


def _rule_anchor_for(action: action_catalog.Action, ground: CaseGrounding) -> list[dict[str, Any]]:
    """The firings that substantiate this action, as JSON — attached to the
    recommendation so its regulatory justification is reconstructable."""
    if not action.typologies:
        return [f.to_dict() for f in ground.firings]
    return [f.to_dict() for f in ground.firings if f.typology in action.typologies]


# ── recommendation generation ───────────────────────────────────────────────


def _submit_tool(eligible_ids: list[str]) -> dict[str, Any]:
    """The forced final-answer schema for recommendations. `action_id` is
    enum-constrained to the eligible set (belt); the engine re-checks it (braces).
    `rationale` reuses Phase 8's grounded-claims schema verbatim, so the same
    validator that guards explanations guards recommendation rationales."""
    return {
        "type": "function",
        "function": {
            "name": "submit_recommendations",
            "description": (
                "Submit the recommended next steps for this case. Each entry names "
                "an eligible action and a grounded rationale."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "recommendations": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                "action_id": {
                                    "type": "string",
                                    "enum": list(eligible_ids),
                                    "description": "An action_id from the eligible list.",
                                },
                                "rationale": grounding.claims_schema(),
                            },
                            "required": ["action_id", "rationale"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["recommendations"],
                "additionalProperties": False,
            },
        },
    }


def generate_recommendations(
    session: Session,
    case_id: str,
    *,
    settings: Settings,
    actor_type: ActorType,
    actor_id: str,
) -> RecommendationResult:
    """Generate ranked, grounded recommendations for a case, and persist the
    interaction. Does NOT commit — the caller owns the transaction boundary,
    matching every other investigation/orchestration function.

    Raises `ExplanationUnavailableError` if the LLM is unconfigured/unreachable
    (never persists a failed call as a success — the Phase 5 landmine)."""
    ground = rule_grounding.ground_case(session, case_id)
    if not ground.firings:
        # Nothing fired — there is no evidence to ground a recommendation on, so
        # we do not call the model at all. An empty result, not an error.
        return RecommendationResult(case_id=case_id)

    eligible_actions = action_catalog.actions_for_typologies(ground.fired_typologies)
    eligible_ids = [a.action_id for a in eligible_actions]

    catalog = build_tool_catalog(session, case_id, actor_type=actor_type, actor_id=actor_id)
    system_prompt = _SYSTEM_PROMPT.format(action_menu=_action_menu(eligible_actions))
    user_prompt = (
        f"Recommend the next steps for case {case_id}. "
        f"Typologies detected: {', '.join(sorted(str(t) for t in ground.fired_typologies))}."
    )

    result: AgentResult = run_agent_loop(
        settings=settings,
        catalog=catalog,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        submit_tool=_submit_tool(eligible_ids),
        submit_tool_name="submit_recommendations",
    )

    accepted, rejected = _validate_recommendations(result, ground, set(eligible_ids))

    # Belt-and-braces PII assertion over the full prompt-bound bundle before it
    # is persisted (each tool result was already gated at dispatch).
    assert_no_pii_egress(result.bundle.facts, catalog.case_pii)

    response_payload = [r.to_dict() for r in accepted]
    interaction = AiInteractionRepository(session).create(
        agent=AiAgent.RECOMMENDATION,
        case_id=case_id,
        user_id=actor_id,
        request_text=user_prompt,
        facts=result.bundle.facts,
        rule_anchors=ground.to_rule_anchors(),
        tools_called=result.bundle.tools_called,
        response_text=json.dumps(response_payload),
        model=settings.llm_model,
        model_provider=settings.llm_provider,
        redacted=False,
        latency_ms=result.latency_ms,
        actor_type=actor_type,
        actor_id=actor_id,
    )

    return RecommendationResult(
        case_id=case_id,
        recommendations=accepted,
        rejected=rejected,
        interaction_id=interaction.id,
        iterations=result.iterations,
        latency_ms=result.latency_ms,
    )


def _validate_recommendations(
    result: AgentResult, ground: CaseGrounding, eligible_ids: set[str]
) -> tuple[list[Recommendation], list[dict[str, str]]]:
    """Validate each submitted recommendation, then rank the survivors. Returns
    (accepted-ranked, rejected-with-reasons)."""
    rejected: list[dict[str, str]] = []
    # (Action, GroundingResult) for each accepted recommendation, pre-ranking.
    survivors: list[tuple[action_catalog.Action, grounding.GroundingResult]] = []
    seen: set[str] = set()

    for raw in result.submission.get("recommendations", []):
        action_id = str(raw.get("action_id", ""))
        action = action_catalog.get_action(action_id)

        if action is None or action_id not in eligible_ids:
            rejected.append(
                {"action_id": action_id, "reason": "action not in the eligible catalog"}
            )
            continue
        if action_id in seen:
            continue  # a duplicate action_id — keep the first, drop the rest silently
        seen.add(action_id)

        try:
            claims = grounding.parse_response(raw.get("rationale") or {})
        except GroundingError as exc:
            rejected.append({"action_id": action_id, "reason": f"unparseable rationale: {exc}"})
            continue

        gresult = grounding.validate(claims, result.bundle)
        if not gresult.ok:
            reason = "; ".join(str(r) for r in gresult.rejected)
            rejected.append({"action_id": action_id, "reason": f"ungrounded rationale: {reason}"})
            continue

        survivors.append((action, gresult))

    # Deterministic evidence-weighted ranking over the survivors.
    scored = [(action, ranking.score_action(action, ground)) for action, _ in survivors]
    ranked = ranking.rank_actions(scored)
    narrative_by_id = {action.action_id: gr.narrative() for action, gr in survivors}
    citekeys_by_id = {
        action.action_id: sorted(
            {c.fact_key for claim in gr.accepted for c in claim.citations}
        )
        for action, gr in survivors
    }

    accepted = [
        Recommendation(
            action_id=action.action_id,
            title=action.title,
            description=action.description,
            narrative=narrative_by_id.get(action.action_id, ""),
            confidence=score,
            rank=rank,
            typologies=sorted(str(t) for t in action.typologies),
            regulatory_anchor={
                "fatf": action.regulatory_anchor.fatf,
                "india": action.regulatory_anchor.india,
            },
            rule_anchor=_rule_anchor_for(action, ground),
            cited_fact_keys=citekeys_by_id.get(action.action_id, []),
        )
        for action, score, rank in ranked
    ]
    return accepted, rejected


# ── cross-question dialogue ──────────────────────────────────────────────────


@dataclass
class ChallengeResult:
    case_id: str
    answered: bool
    narrative: str
    interaction_id: int | None = None
    rejected_reason: str | None = None
    iterations: int = 0
    latency_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def answer_challenge(
    session: Session,
    case_id: str,
    question: str,
    *,
    settings: Settings,
    actor_type: ActorType,
    actor_id: str,
) -> ChallengeResult:
    """Answer an investigator's free-text challenge to the case's recommendations,
    defending with grounded, cited facts, and append it to the same audited
    `ai_interactions` thread. Does NOT commit (caller owns the transaction).

    The answer is subject to the identical grounding contract: an answer whose
    claims are not grounded is *not* shown — `answered=False` with a reason,
    rather than an ungrounded rebuttal reaching the investigator."""
    trimmed = (question or "").strip()[:MAX_CHALLENGE_CHARS]
    if not trimmed:
        return ChallengeResult(
            case_id=case_id, answered=False, narrative="", rejected_reason="empty question"
        )

    catalog = build_tool_catalog(session, case_id, actor_type=actor_type, actor_id=actor_id)
    user_prompt = f"Case {case_id}. Investigator's question: {trimmed}"

    result = run_agent_loop(
        settings=settings,
        catalog=catalog,
        system_prompt=_CHALLENGE_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        submit_tool=grounding.submit_tool(),
        submit_tool_name=grounding.SUBMIT_TOOL_NAME,
    )

    assert_no_pii_egress(result.bundle.facts, catalog.case_pii)

    try:
        claims = grounding.parse_response(result.submission)
    except GroundingError as exc:
        return ChallengeResult(
            case_id=case_id, answered=False, narrative="",
            rejected_reason=f"unparseable answer: {exc}",
            iterations=result.iterations, latency_ms=result.latency_ms,
        )

    gresult = grounding.validate(claims, result.bundle)
    if not gresult.ok:
        return ChallengeResult(
            case_id=case_id, answered=False, narrative="",
            rejected_reason="; ".join(str(r) for r in gresult.rejected),
            iterations=result.iterations, latency_ms=result.latency_ms,
        )

    narrative = gresult.narrative()
    interaction: AiInteraction = AiInteractionRepository(session).create(
        agent=AiAgent.RECOMMENDATION,
        case_id=case_id,
        user_id=actor_id,
        request_text=trimmed,
        facts=result.bundle.facts,
        rule_anchors=None,
        tools_called=result.bundle.tools_called,
        response_text=narrative,
        model=settings.llm_model,
        model_provider=settings.llm_provider,
        redacted=False,
        latency_ms=result.latency_ms,
        actor_type=actor_type,
        actor_id=actor_id,
    )

    return ChallengeResult(
        case_id=case_id, answered=True, narrative=narrative,
        interaction_id=interaction.id, iterations=result.iterations,
        latency_ms=result.latency_ms,
    )
