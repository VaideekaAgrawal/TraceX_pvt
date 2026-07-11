"""
AI Explanation of Alert / per-account explanation panel -- ROADMAP Phase 5.

**Deliberately a Phase-5 self-contained port, NOT the Phase 8 AI substrate.**
`SYSTEM_DEVELOPMENT_PLAN.md` §4.1 calls the archive's existing per-account
LLM explanation panel *already built and genuinely strong*: facts injected
into the prompt (not generated), low temperature, cached, labeled
AI-generated. This module ports that behavior near-verbatim (`_call_openrouter`
from `archive/fund-flow-tracker/api/server.py:111-134`, the prompt template
from `server.py:767-795`, reworded for the data this codebase's schema
actually has available) so L1 triage gets this feature now, without waiting
on -- or duplicating -- Phase 8's LLM gateway/PII-redaction middleware/tool
catalog. There is NO provider abstraction, NO tool-calling, NO guardrail
middleware here: a direct `httpx` POST to OpenRouter. Phase 8 may replace or
wrap this; this module should not itself grow gateway-shaped features later
(if it starts needing multi-provider routing, tool calls, or free-text
input, that need belongs to Phase 8, not an extension of this file).

**Guardrail property preserved exactly** (CLAUDE.md: "the existing per-
account LLM explanation is defensible... because it can't be manipulated by
attacker-controlled input" -- and that property does NOT automatically
transfer to new AI features): every fact assembled below is server-computed
(risk scores, role classification, aggregated transaction stats, KYC/income
fields, detected pattern types). `Transaction.narration`/`purpose` are
deliberately EXCLUDED from the fact dict and therefore never reach the
prompt -- both are marked "PII, attacker-controllable" in
`db/models/reference.py::Transaction` and are exactly the fields
`db/pii.py`'s redaction allow-map exists to protect. This is the same
omission the archive made (implicitly, by simply never reading those
columns); this docstring makes it an explicit, tested guarantee instead of
an implicit gap (see `tests/orchestration/test_account_explanation.py`'s
narration/purpose regression test).
"""
from __future__ import annotations

import time
from typing import Any

import httpx
from sqlalchemy.orm import Session

from db.enums import ActorType, AiAgent
from db.models.orchestration import AiInteraction
from db.repositories.detection import AlertRepository
from db.repositories.investigation import CaseAccountRepository, CaseRepository
from db.repositories.orchestration import AiInteractionRepository
from db.repositories.reference import AccountRepository, CustomerRepository, TransactionRepository
from detection.scoring.ensemble import RoleClassifier
from foundation.config import Settings
from investigation.account_facts import transaction_stats
from investigation.case_graph import build_case_graph_store

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_NOT_CONFIGURED_MESSAGE = "AI explanations not configured. Set openrouter_api_key."


def _call_openrouter(prompt: str, *, settings: Settings, max_tokens: int = 300) -> str:
    """Single OpenRouter chat-completions call -- ported near-verbatim from
    `archive/fund-flow-tracker/api/server.py::_call_openrouter`
    (temperature=0.3, 20s timeout). Fails open: returns a visible error/
    "not configured" string on any failure (missing key, network error,
    non-2xx response, malformed body) rather than raising, so a triage
    screen degrades to a readable message instead of a 500."""
    if not settings.openrouter_api_key:
        return _NOT_CONFIGURED_MESSAGE
    try:
        response = httpx.post(
            _OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {settings.openrouter_api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost:3000",
                "X-Title": "TraceX AML",
            },
            json={
                "model": settings.llm_model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0.3,
            },
            timeout=20.0,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return str(content).strip()
    except Exception as exc:  # noqa: BLE001 -- fails open with a message, matches the archive
        return f"Could not generate explanation: {exc}"


def _assemble_facts(session: Session, case_id: str, account_id: str) -> dict[str, Any]:
    """Server-computed facts only -- see module docstring for the guardrail
    reasoning behind what is and isn't included here."""
    account = AccountRepository(session).get(account_id)
    case = CaseRepository(session).get(case_id)

    case_account_ids = [
        ca.account_id for ca in CaseAccountRepository(session).list_for_case(case_id)
    ]
    graph = build_case_graph_store(session, case_account_ids)
    role_info = RoleClassifier().classify_all(graph).get(account_id, {})

    txns = TransactionRepository(session).list_for_account_in_window(account_id)
    stats = transaction_stats(txns, account_id)

    customer = None
    if account is not None and account.customer_id is not None:
        customer = CustomerRepository(session).get(account.customer_id)

    detected_patterns = sorted(
        {
            str(alert.detection_type)
            for alert in AlertRepository(session).list_for_case(case_id)
            if account_id in alert.account_ids
        }
    )

    return {
        "account_id": account_id,
        "branch_city": account.branch_city if account is not None else None,
        "current_risk_score": (
            float(account.current_risk_score)
            if account is not None and account.current_risk_score is not None
            else None
        ),
        "case_risk_score": (
            float(case.risk_score) if case is not None and case.risk_score is not None else None
        ),
        "network_risk_score": (
            float(case.network_risk_score)
            if case is not None and case.network_risk_score is not None
            else None
        ),
        "role": role_info.get("role", "UNKNOWN"),
        "role_confidence": role_info.get("confidence", 0.0),
        "total_in": stats["total_in"],
        "total_out": stats["total_out"],
        "txn_count": stats["txn_count"],
        "counterparty_count": stats["counterparty_count"],
        "channel_breakdown": stats["channel_breakdown"],
        "occupation": customer.occupation if customer is not None else None,
        "declared_annual_income": (
            float(customer.declared_annual_income)
            if customer is not None and customer.declared_annual_income is not None
            else None
        ),
        "income_bracket": customer.income_bracket if customer is not None else None,
        "detected_patterns": detected_patterns,
    }


def _build_prompt(facts: dict[str, Any]) -> str:
    """Prompt template ported from `archive/fund-flow-tracker/api/
    server.py:767-795`, reworded for a single-account explainer built off
    this schema's actually-available fields (no `account_type`/`anomaly_
    score`/`fraud_probability`/top ML features -- those come from an
    in-memory detection run the archive kept around; this codebase's
    per-account signal is `Account.current_risk_score` + case-level risk +
    network risk + role classification instead)."""
    account_id = facts["account_id"]
    detected_patterns = facts["detected_patterns"]
    pattern_text = (
        ", ".join(detected_patterns)
        if detected_patterns
        else "No specific pattern matched -- flagged by composite risk scoring"
    )
    channel_text = (
        ", ".join(f"{channel}: {count}" for channel, count in facts["channel_breakdown"].items())
        or "N/A"
    )
    income = facts["declared_annual_income"] or 0.0
    income_ratio = (facts["total_in"] / income) if income > 0 else 0.0

    return f"""You are a senior financial crime analyst writing investigation briefings for \
compliance officers at a bank. Write a clear, professional 3-4 sentence explanation of why \
account {account_id} has been flagged as suspicious by our AML system.

Account Profile:
- Account ID: {account_id}
- Branch: {facts['branch_city'] or 'Unknown'}
- Occupation: {facts['occupation'] or 'Unknown'}
- Declared Annual Income: Rs.{income:,.0f}
- Total Inflow: Rs.{facts['total_in']:,.0f}
- Total Outflow: Rs.{facts['total_out']:,.0f}
- Transaction Count: {facts['txn_count']}
- Unique Counterparties: {facts['counterparty_count']}
- Channel Mix: {channel_text}
- Income-to-Inflow Ratio: {income_ratio:.1f}x declared income
- Account Risk Score: {facts['current_risk_score'] or 0.0:.1f}/100
- Case Risk Score: {facts['case_risk_score'] or 0.0:.1f}/100
- Network Risk Score: {facts['network_risk_score'] or 0.0:.1f}/100
- Network Role: {facts['role']} (confidence: {facts['role_confidence']:.0%})

AML Patterns Detected: {pattern_text}

Instructions:
- Write as a compliance officer would for a Suspicious Activity Report
- Use specific numbers from the data above
- Explain what the patterns mean in plain English (e.g. "layering" = moving funds through \
multiple accounts to obscure origin)
- End with a concrete recommended investigative action
- Do NOT use bullet points or headers -- write flowing prose only
- Do NOT mention model names like XGBoost or Isolation Forest
- Maximum 4 sentences"""


def _find_cached(
    repo: AiInteractionRepository, case_id: str, account_id: str
) -> AiInteraction | None:
    """Most-recent-wins cache lookup over `ai_interactions`, filtered in
    Python to this account (see `AiInteractionRepository.
    list_for_case_and_agent`'s docstring for why the account filter can't be
    pushed into SQL). No TTL modeled -- matches the archive's "cached until
    force=True" semantics; a future phase can add one by comparing
    `created_at` without changing this function's interface."""
    matching = [
        interaction
        for interaction in repo.list_for_case_and_agent(case_id, AiAgent.RECOMMENDATION)
        if interaction.facts is not None and interaction.facts.get("account_id") == account_id
    ]
    if not matching:
        return None
    return max(matching, key=lambda interaction: interaction.created_at)


def explain_account(
    session: Session,
    case_id: str,
    account_id: str,
    *,
    settings: Settings,
    actor_type: ActorType,
    actor_id: str,
    force: bool = False,
) -> dict[str, Any]:
    """Return `{"account_id", "explanation", "cached", "model",
    "generated_at"}` for `account_id` within `case_id`. Validates
    `account_id` is in the case's scope (defense-in-depth -- the real
    boundary check is the route dependency, `api.routes.cases.
    require_case_scoped_account`; this repeats it because this function is
    also directly unit-testable/callable without going through HTTP).

    Unless `force=True`, checks `ai_interactions` for a prior `RECOMMENDATION`
    interaction for this exact (case, account) and returns it (`cached=True`)
    without calling the LLM again. Otherwise assembles fresh facts, calls
    `_call_openrouter`, persists a new `ai_interactions` row (does NOT commit
    -- caller owns the transaction boundary, matching every other
    investigation-layer function), and returns `cached=False`."""
    case_account_ids = {
        ca.account_id for ca in CaseAccountRepository(session).list_for_case(case_id)
    }
    if account_id not in case_account_ids:
        raise ValueError(f"account {account_id!r} is not in case {case_id!r}'s scope")

    interaction_repo = AiInteractionRepository(session)
    if not force:
        cached = _find_cached(interaction_repo, case_id, account_id)
        if cached is not None:
            return {
                "account_id": account_id,
                "explanation": cached.response_text,
                "cached": True,
                "model": cached.model,
                "generated_at": cached.created_at,
            }

    facts = _assemble_facts(session, case_id, account_id)
    prompt = _build_prompt(facts)

    start = time.monotonic()
    explanation = _call_openrouter(prompt, settings=settings)
    latency_ms = int((time.monotonic() - start) * 1000)

    interaction = interaction_repo.create(
        agent=AiAgent.RECOMMENDATION,
        case_id=case_id,
        user_id=actor_id,
        request_text=prompt,
        facts=facts,
        response_text=explanation,
        model=settings.llm_model,
        model_provider=settings.llm_provider,
        redacted=False,
        latency_ms=latency_ms,
        actor_type=actor_type,
        actor_id=actor_id,
    )

    return {
        "account_id": account_id,
        "explanation": explanation,
        "cached": False,
        "model": interaction.model,
        "generated_at": interaction.created_at,
    }
