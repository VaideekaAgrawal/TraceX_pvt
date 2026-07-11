"""
Pattern Explanation (ROADMAP Phase 6; `SYSTEM_DEVELOPMENT_PLAN.md` §4.2:
"evidence-backed explanation of a detected typology ... Extension of the
existing AI-explanation pattern to graph-structural findings rather than
just account-level anomalies").

**Guardrail property preserved exactly**, same as
`orchestration.account_explanation`: every fact injected into the prompt
below is server-computed and ALREADY PERSISTED -- sourced only from the
`Alert` row's own columns (`detection_type`, `account_ids`, `score`,
`risk_score`, `severity`, `priority`, `confidence`, `rule_ids`) via
`AlertRepository.get(alert_id)`, validated to belong to `case_id` and to
overlap the case's linked accounts. This module NEVER re-runs detection
live to produce facts -- the alert a pattern explanation describes is
whatever the detection pipeline already decided and persisted, not a
fresh recomputation that could disagree with the alert an investigator is
actually looking at.

Shares the `ai_interactions`/`AiAgent.RECOMMENDATION` namespace with
`orchestration.account_explanation` -- no collision risk, since the two
modules cache on disjoint keys (`facts["account_id"]` vs.
`facts["pattern_signature"]`) and `_find_cached_by_signature` only ever
matches rows carrying `pattern_signature`, which `account_explanation`
never writes.

On success, this is the first real writer of `AiInteraction.rule_anchors`
(always `None` on the `account_explanation` path) -- a structured pointer
back to exactly what triggered the alert (detection type + rule ids), NOT
the FATF/RBI regulatory-anchor mapping `SYSTEM_DEVELOPMENT_PLAN.md`'s
Investigation Path Recommendation describes (that's Phase 9's action
catalog, out of scope here).

**Failure/caching contract is identical to `explain_account`'s** (the exact
Phase-5 code-review-fixed bug that must not regress): a failed/
not-configured call returns `cached=False` with the error message
surfaced, and writes NO `AiInteraction` row -- a transient outage must
never get permanently "cached" as the answer.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from sqlalchemy.orm import Session

from db.enums import ActorType, AiAgent
from db.models.base import utcnow
from db.models.orchestration import AiInteraction
from db.repositories.detection import AlertRepository
from db.repositories.investigation import CaseAccountRepository
from db.repositories.orchestration import AiInteractionRepository
from foundation.config import Settings
from orchestration.llm_client import ExplanationUnavailableError
from orchestration.llm_client import call_openrouter as _call_openrouter


def compute_pattern_signature(detection_type: str, account_ids: list[str]) -> str:
    """Deterministic cache key for one detected pattern: a sha256 of the
    JSON-serialized `{detection_type, account_ids}` (account_ids sorted, so
    the same set in a different order hashes identically), truncated to 24
    hex chars -- collision risk is irrelevant at this scale (a handful of
    patterns per case), 24 chars just keeps it readable in logs/DB rows."""
    payload = json.dumps(
        {"detection_type": detection_type, "account_ids": sorted(account_ids)}, sort_keys=True
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _assemble_facts(session: Session, case_id: str, alert_id: str) -> dict[str, Any]:
    """Server-computed, ALREADY-PERSISTED facts only -- see module
    docstring. Raises `ValueError` if `alert_id` doesn't exist, doesn't
    belong to `case_id`, or shares no account with `case_id`'s linked
    accounts (defense-in-depth -- the real boundary check is the route
    dependency, `api.routes.l2`'s `require_case_access`; this repeats it
    because this function is also directly unit-testable/callable without
    going through HTTP, matching `orchestration.account_explanation.
    explain_account`'s precedent)."""
    alert = AlertRepository(session).get(alert_id)
    if alert is None:
        raise ValueError(f"alert {alert_id!r} does not exist")
    if alert.case_id != case_id:
        raise ValueError(f"alert {alert_id!r} does not belong to case {case_id!r}")

    case_account_ids = set(CaseAccountRepository(session).list_account_ids_for_case(case_id))
    if not case_account_ids.intersection(alert.account_ids):
        raise ValueError(f"alert {alert_id!r} shares no account with case {case_id!r}'s scope")

    return {
        "alert_id": alert.alert_id,
        "case_id": case_id,
        "detection_type": str(alert.detection_type),
        "primary_account_id": alert.primary_account_id,
        "account_ids": sorted(alert.account_ids),
        "score": alert.score,
        "risk_score": alert.risk_score,
        "severity": str(alert.severity),
        "priority": str(alert.priority),
        "confidence": alert.confidence,
        "rule_ids": alert.rule_ids or [],
        "pattern_signature": compute_pattern_signature(
            str(alert.detection_type), alert.account_ids
        ),
    }


def _build_prompt(facts: dict[str, Any]) -> str:
    """Prompt template for a typology/pattern explanation -- structurally
    matches `orchestration.account_explanation._build_prompt`'s prose
    style/instructions, retargeted from one account's anomaly to one
    detected multi-account pattern."""
    accounts_text = ", ".join(facts["account_ids"]) if facts["account_ids"] else "N/A"
    rule_text = (
        ", ".join(facts["rule_ids"])
        if facts["rule_ids"]
        else "composite ML scoring (no rule-engine match)"
    )
    confidence = facts["confidence"] or "N/A"

    return f"""You are a senior financial crime analyst writing investigation briefings for \
compliance officers at a bank. Write a clear, professional 3-4 sentence evidence-backed \
explanation of the "{facts['detection_type']}" pattern detected across accounts {accounts_text}.

Detection Summary:
- Alert ID: {facts['alert_id']}
- Detection Type: {facts['detection_type']}
- Accounts Involved: {accounts_text}
- Primary Account: {facts['primary_account_id']}
- Composite Score: {facts['score']:.2f}
- Risk Score: {facts['risk_score']:.1f}/100
- Severity: {facts['severity']}
- Priority: {facts['priority']}
- Confidence: {confidence}
- Triggering Rules: {rule_text}

Instructions:
- Write as a compliance officer would for a Suspicious Activity Report
- Explain what "{facts['detection_type']}" means in plain English and why this combination of \
accounts and signals constitutes it
- Use specific numbers from the data above
- End with a concrete recommended investigative action
- Do NOT use bullet points or headers -- write flowing prose only
- Do NOT mention model names like XGBoost or Isolation Forest
- Maximum 4 sentences"""


def _find_cached_by_signature(
    repo: AiInteractionRepository, case_id: str, signature: str
) -> AiInteraction | None:
    """Most-recent-wins cache lookup over `ai_interactions`, filtered in
    Python to this `pattern_signature` -- same shape as `orchestration.
    account_explanation._find_cached`, filtering on the pattern-signature
    key instead of `account_id`."""
    matching = [
        interaction
        for interaction in repo.list_for_case_and_agent(case_id, AiAgent.RECOMMENDATION)
        if interaction.facts is not None and interaction.facts.get("pattern_signature") == signature
    ]
    if not matching:
        return None
    return max(matching, key=lambda interaction: interaction.created_at)


def explain_pattern(
    session: Session,
    case_id: str,
    alert_id: str,
    *,
    settings: Settings,
    actor_type: ActorType,
    actor_id: str,
    force: bool = False,
) -> dict[str, Any]:
    """Return `{"alert_id", "explanation", "cached", "model",
    "generated_at", "rule_anchors", "pattern_signature"}` for the pattern
    `alert_id` describes within `case_id`.

    Unless `force=True`, checks `ai_interactions` for a prior
    `RECOMMENDATION` interaction carrying this exact pattern signature and
    returns it (`cached=True`) without calling the LLM again. Otherwise
    assembles fresh (already-persisted) facts and calls `call_openrouter`:
    on success, persists a new `ai_interactions` row -- populating
    `rule_anchors` for the first time (see module docstring) -- and returns
    `cached=False`; on `ExplanationUnavailableError`, returns `cached=False`
    with the error message surfaced but writes NO `ai_interactions` row
    (identical contract to `explain_account` -- see module docstring)."""
    facts = _assemble_facts(session, case_id, alert_id)
    signature = facts["pattern_signature"]

    interaction_repo = AiInteractionRepository(session)
    if not force:
        cached = _find_cached_by_signature(interaction_repo, case_id, signature)
        if cached is not None:
            return {
                "alert_id": alert_id,
                "explanation": cached.response_text,
                "cached": True,
                "model": cached.model,
                "generated_at": cached.created_at,
                "rule_anchors": cached.rule_anchors,
                "pattern_signature": signature,
            }

    prompt = _build_prompt(facts)

    start = time.monotonic()
    try:
        explanation = _call_openrouter(prompt, settings=settings)
    except ExplanationUnavailableError as exc:
        return {
            "alert_id": alert_id,
            "explanation": str(exc),
            "cached": False,
            "model": settings.llm_model,
            "generated_at": utcnow(),
            "rule_anchors": None,
            "pattern_signature": signature,
        }
    latency_ms = int((time.monotonic() - start) * 1000)

    rule_anchors = {
        "detection_type": facts["detection_type"],
        "rule_ids": facts["rule_ids"],
        "alert_id": facts["alert_id"],
    }

    interaction = interaction_repo.create(
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

    return {
        "alert_id": alert_id,
        "explanation": explanation,
        "cached": False,
        "model": interaction.model,
        "generated_at": interaction.created_at,
        "rule_anchors": interaction.rule_anchors,
        "pattern_signature": signature,
    }
