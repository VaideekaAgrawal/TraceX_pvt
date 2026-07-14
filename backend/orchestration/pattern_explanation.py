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
modules cache on disjoint keys (`facts["account_id"]` vs. `facts
["alert_id"]`).

**Cache key is `alert_id`, NOT `pattern_signature`** (code-review finding,
Phase 6, fixed from an earlier version of this module that cached on
`compute_pattern_signature(detection_type, account_ids)` alone): `alerts.
alert_id` is deterministic per `(account_ids, detection_type, detection
date)` (`investigation.alerts.generate_alerts_from_detection` ->
`make_deterministic_alert_id`), so the SAME `detection_type`+`account_ids`
pair re-detected on a LATER date legitimately produces a second, different
`Alert` row -- with its own `score`/`risk_score`/`severity`/`confidence`,
which `_build_prompt` embeds directly into the LLM prompt text. Caching by
pattern-shape alone meant a request for that newer alert could silently
serve the older alert's stale explanation, with the wrong numbers baked
into the prose and an internally-inconsistent `rule_anchors.alert_id`.
Keying on `alert_id` (the natural unique identity of the entity being
explained, same granularity as `account_explanation`'s per-account keying)
eliminates that whole bug class rather than papering over the symptom.
`compute_pattern_signature` is still computed and stored in `facts` --
useful as a structural "same underlying pattern shape" fingerprint for a
future feature (e.g. Phase 7's Similar Cases), just no longer the cache key.

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

Shares the cache-lookup and generate-and-persist flow with
`orchestration.account_explanation.explain_account` via `orchestration.
gateway.find_cached_interaction`/`generate_and_persist_explanation`
(code-review finding, Phase 6: this module used to duplicate that whole
flow near-verbatim).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy.orm import Session

from db.enums import ActorType, AiAgent
from db.models.base import utcnow
from db.repositories.detection import AlertRepository
from db.repositories.investigation import CaseAccountRepository
from db.repositories.orchestration import AiInteractionRepository
from foundation.config import Settings
from orchestration.gateway import (
    ExplanationUnavailableError,
    find_cached_interaction,
    generate_and_persist_explanation,
)
from orchestration.gateway import call_llm as _call_llm


def compute_pattern_signature(detection_type: str, account_ids: list[str]) -> str:
    """A structural "same underlying pattern shape" fingerprint: a sha256 of
    the JSON-serialized `{detection_type, account_ids}` (account_ids sorted,
    so the same set in a different order hashes identically), truncated to
    24 hex chars. **Not the cache key** (see module docstring for why) --
    stored in `facts["pattern_signature"]` as metadata a future feature
    (e.g. Phase 7's Similar Cases) could group on."""
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
    `RECOMMENDATION` interaction for this exact `alert_id` (`orchestration.
    gateway.find_cached_interaction`, keyed on `facts["alert_id"]` -- see
    module docstring for why this is `alert_id`, not a pattern-shape hash)
    and returns it (`cached=True`) without calling the LLM again. Otherwise
    assembles fresh (already-persisted) facts and calls `call_llm`
    via `orchestration.gateway.generate_and_persist_explanation`: on
    success, persists a new `ai_interactions` row -- populating
    `rule_anchors` for the first time (see module docstring) -- and returns
    `cached=False`; on `ExplanationUnavailableError`, returns `cached=False`
    with the error message surfaced but writes NO `ai_interactions` row
    (identical contract to `explain_account` -- see module docstring)."""
    facts = _assemble_facts(session, case_id, alert_id)

    interaction_repo = AiInteractionRepository(session)
    if not force:
        cached = find_cached_interaction(
            interaction_repo, case_id, AiAgent.RECOMMENDATION,
            key_field="alert_id", key_value=alert_id,
        )
        if cached is not None:
            return {
                "alert_id": alert_id,
                "explanation": cached.response_text,
                "cached": True,
                "model": cached.model,
                "generated_at": cached.created_at,
                "rule_anchors": cached.rule_anchors,
                "pattern_signature": facts["pattern_signature"],
            }

    prompt = _build_prompt(facts)
    rule_anchors = {
        "detection_type": facts["detection_type"],
        "rule_ids": facts["rule_ids"],
        "alert_id": facts["alert_id"],
    }

    try:
        interaction = generate_and_persist_explanation(
            session,
            call_fn=_call_llm,
            prompt=prompt,
            settings=settings,
            case_id=case_id,
            facts=facts,
            actor_type=actor_type,
            actor_id=actor_id,
            rule_anchors=rule_anchors,
        )
    except ExplanationUnavailableError as exc:
        return {
            "alert_id": alert_id,
            "explanation": str(exc),
            "cached": False,
            "model": settings.llm_model,
            "generated_at": utcnow(),
            "rule_anchors": None,
            "pattern_signature": facts["pattern_signature"],
        }

    return {
        "alert_id": alert_id,
        "explanation": interaction.response_text,
        "cached": False,
        "model": interaction.model,
        "generated_at": interaction.created_at,
        "rule_anchors": interaction.rule_anchors,
        "pattern_signature": facts["pattern_signature"],
    }
