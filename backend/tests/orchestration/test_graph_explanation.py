"""
`orchestration.graph_explanation` -- Investigation Graph AI explanation
(`fix/l1-l2-usability-and-bugs`). Mirrors `tests/orchestration/test_account_
explanation.py`'s structure and guardrail-regression pattern: cache hit on
repeat (case, account), `force` bypass, failure never cached, and facts/
prompt never contain `Transaction.narration`/`purpose`.

Seeds a genuine 3-node transaction cycle (A1 -> A2 -> A3 -> A1) so cycle
detection is exercised for real, not just asserted absent.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from db.enums import (
    ActorType,
    AiAgent,
    CaseLevel,
    CaseStatus,
    Channel,
    EntityType,
    Priority,
    RiskLevel,
)
from db.repositories.investigation import CaseAccountRepository, CaseRepository
from db.repositories.orchestration import AiInteractionRepository
from db.repositories.reference import AccountRepository, CustomerRepository, TransactionRepository
from foundation.config import Settings
from orchestration import graph_explanation

# A recognizable marker only ever written into narration/purpose -- if it
# leaks into the assembled facts or the built prompt, the same guardrail
# `account_explanation.py` documents/tests is broken here too.
_SECRET_NARRATION = "SECRET_NARRATION_MARKER_do_not_leak_to_llm"
_SECRET_PURPOSE = "SECRET_PURPOSE_MARKER_do_not_leak_to_llm"


def _seed(session: Session) -> None:
    for account_id, risk in (("A1", 40.0), ("A2", 70.0), ("A3", 55.0)):
        AccountRepository(session).create(
            account_id=account_id, customer_id=f"CUST_{account_id}",
            current_risk_score=risk, actor_type=ActorType.SYSTEM, actor_id=None,
        )
        CustomerRepository(session).create(
            customer_id=f"CUST_{account_id}", name=f"Customer {account_id}",
            entity_type=EntityType.INDIVIDUAL, risk_rating=RiskLevel.MEDIUM,
            actor_type=ActorType.SYSTEM, actor_id=None,
        )
    CaseRepository(session).create(
        case_id="CASE1", primary_account_id="A1", status=CaseStatus.IN_PROGRESS,
        level=CaseLevel.L2, priority=Priority.P1, actor_type=ActorType.SYSTEM, actor_id=None,
    )
    for account_id in ("A1", "A2", "A3"):
        CaseAccountRepository(session).add_account(
            case_id="CASE1", account_id=account_id, actor_type=ActorType.SYSTEM, actor_id=None
        )

    ts = datetime(2026, 1, 1, tzinfo=UTC)
    # A1 -> A2 -> A3 -> A1: a genuine closed cycle.
    TransactionRepository(session).create(
        txn_id="T1", timestamp=ts, source_account="A1", dest_account="A2",
        amount=10_000.0, channel=Channel.NEFT, is_laundering=1, ingested_at=ts,
        narration=_SECRET_NARRATION, purpose=_SECRET_PURPOSE,
        actor_type=ActorType.SYSTEM, actor_id=None,
    )
    TransactionRepository(session).create(
        txn_id="T2", timestamp=ts.replace(hour=1), source_account="A2", dest_account="A3",
        amount=9_500.0, channel=Channel.UPI, is_laundering=1, ingested_at=ts,
        actor_type=ActorType.SYSTEM, actor_id=None,
    )
    TransactionRepository(session).create(
        txn_id="T3", timestamp=ts.replace(hour=2), source_account="A3", dest_account="A1",
        amount=9_000.0, channel=Channel.UPI, is_laundering=1, ingested_at=ts,
        actor_type=ActorType.SYSTEM, actor_id=None,
    )
    session.commit()


def _settings() -> Settings:
    return Settings(env="dev", jwt_secret="test-secret", openrouter_api_key="test-key")


def test_explain_graph_first_call_writes_interaction_and_is_not_cached(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(session)
    calls: list[str] = []

    def _fake_call(prompt: str, *, settings: Settings, max_tokens: int = 300) -> str:
        calls.append(prompt)
        return "Fake graph explanation."

    monkeypatch.setattr(graph_explanation, "_call_llm", _fake_call)

    result = graph_explanation.explain_graph(
        session, "CASE1", "A1",
        settings=_settings(), actor_type=ActorType.INVESTIGATOR, actor_id="U1",
    )
    session.commit()

    assert result["cached"] is False
    assert result["explanation"] == "Fake graph explanation."
    assert result["account_id"] == "A1"
    assert len(calls) == 1

    interactions = AiInteractionRepository(session).list_for_case_and_agent(
        "CASE1", AiAgent.RECOMMENDATION
    )
    assert len(interactions) == 1
    assert interactions[0].facts is not None
    assert interactions[0].facts["graph_account_id"] == "A1"
    # A real cycle was seeded (A1 -> A2 -> A3 -> A1) -- the facts must say so.
    assert interactions[0].facts["has_cycle"] is True
    assert interactions[0].facts["cycle_count"] >= 1


def test_explain_graph_second_call_is_cached_with_no_additional_llm_call(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(session)
    calls: list[str] = []

    def _fake_call(prompt: str, *, settings: Settings, max_tokens: int = 300) -> str:
        calls.append(prompt)
        return "Fake graph explanation."

    monkeypatch.setattr(graph_explanation, "_call_llm", _fake_call)

    first = graph_explanation.explain_graph(
        session, "CASE1", "A1",
        settings=_settings(), actor_type=ActorType.INVESTIGATOR, actor_id="U1",
    )
    session.commit()
    assert len(calls) == 1

    second = graph_explanation.explain_graph(
        session, "CASE1", "A1",
        settings=_settings(), actor_type=ActorType.INVESTIGATOR, actor_id="U1",
    )
    session.commit()

    assert second["cached"] is True
    assert second["explanation"] == first["explanation"]
    assert len(calls) == 1  # no additional stub call


def test_explain_graph_does_not_collide_with_account_explanation_cache(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`key_field="graph_account_id"` must be disjoint from `account_
    explanation`'s `key_field="account_id"` in the same `AiAgent.
    RECOMMENDATION` cache namespace -- calling one must not serve the
    other's cached response back."""
    from orchestration import account_explanation

    _seed(session)

    def _fake_account_call(prompt: str, *, settings: Settings, max_tokens: int = 300) -> str:
        return "Fake ACCOUNT explanation."

    def _fake_graph_call(prompt: str, *, settings: Settings, max_tokens: int = 300) -> str:
        return "Fake GRAPH explanation."

    monkeypatch.setattr(account_explanation, "_call_llm", _fake_account_call)
    monkeypatch.setattr(graph_explanation, "_call_llm", _fake_graph_call)

    account_result = account_explanation.explain_account(
        session, "CASE1", "A1",
        settings=_settings(), actor_type=ActorType.INVESTIGATOR, actor_id="U1",
    )
    session.commit()
    graph_result = graph_explanation.explain_graph(
        session, "CASE1", "A1",
        settings=_settings(), actor_type=ActorType.INVESTIGATOR, actor_id="U1",
    )
    session.commit()

    assert account_result["explanation"] == "Fake ACCOUNT explanation."
    assert graph_result["explanation"] == "Fake GRAPH explanation."

    interactions = AiInteractionRepository(session).list_for_case_and_agent(
        "CASE1", AiAgent.RECOMMENDATION
    )
    assert len(interactions) == 2


def test_explain_graph_force_bypasses_cache(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(session)
    calls: list[str] = []

    def _fake_call(prompt: str, *, settings: Settings, max_tokens: int = 300) -> str:
        calls.append(prompt)
        return f"Explanation #{len(calls)}."

    monkeypatch.setattr(graph_explanation, "_call_llm", _fake_call)

    first = graph_explanation.explain_graph(
        session, "CASE1", "A1",
        settings=_settings(), actor_type=ActorType.INVESTIGATOR, actor_id="U1",
    )
    session.commit()

    second = graph_explanation.explain_graph(
        session, "CASE1", "A1",
        settings=_settings(), actor_type=ActorType.INVESTIGATOR, actor_id="U1", force=True,
    )
    session.commit()

    assert len(calls) == 2
    assert second["cached"] is False
    assert second["explanation"] != first["explanation"]


def test_explain_graph_facts_and_prompt_never_contain_narration_or_purpose(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(session)
    captured_prompts: list[str] = []

    def _fake_call(prompt: str, *, settings: Settings, max_tokens: int = 300) -> str:
        captured_prompts.append(prompt)
        return "Fake graph explanation."

    monkeypatch.setattr(graph_explanation, "_call_llm", _fake_call)

    graph_explanation.explain_graph(
        session, "CASE1", "A1",
        settings=_settings(), actor_type=ActorType.INVESTIGATOR, actor_id="U1",
    )
    session.commit()

    assert len(captured_prompts) == 1
    prompt = captured_prompts[0]
    assert _SECRET_NARRATION not in prompt
    assert _SECRET_PURPOSE not in prompt

    interaction = AiInteractionRepository(session).list_for_case_and_agent(
        "CASE1", AiAgent.RECOMMENDATION
    )[0]
    assert interaction.facts is not None
    facts_str = str(interaction.facts)
    assert _SECRET_NARRATION not in facts_str
    assert _SECRET_PURPOSE not in facts_str
    assert "narration" not in interaction.facts
    assert "purpose" not in interaction.facts


def test_explain_graph_rejects_account_outside_case_scope(session: Session) -> None:
    _seed(session)
    AccountRepository(session).create(
        account_id="A_OUTSIDE", actor_type=ActorType.SYSTEM, actor_id=None
    )
    session.commit()
    with pytest.raises(ValueError, match="not in case"):
        graph_explanation.explain_graph(
            session, "CASE1", "A_OUTSIDE",
            settings=_settings(), actor_type=ActorType.INVESTIGATOR, actor_id="U1",
        )


def test_explain_graph_failure_is_not_cached(session: Session) -> None:
    # Regression test (same class of bug `explain_account`/`explain_pattern`
    # were fixed for): a failed/"not configured" call must never be written
    # to `ai_interactions` and served back as `cached: True` later.
    _seed(session)
    settings = Settings(env="dev", jwt_secret="test-secret", openrouter_api_key="")

    first = graph_explanation.explain_graph(
        session, "CASE1", "A1",
        settings=settings, actor_type=ActorType.INVESTIGATOR, actor_id="U1",
    )
    session.commit()
    assert first["cached"] is False

    second = graph_explanation.explain_graph(
        session, "CASE1", "A1",
        settings=settings, actor_type=ActorType.INVESTIGATOR, actor_id="U1",
    )
    session.commit()
    assert second["cached"] is False  # still not cached, not a bad cache hit

    interactions = AiInteractionRepository(session).list_for_case_and_agent(
        "CASE1", AiAgent.RECOMMENDATION
    )
    assert interactions == []  # no failure ever persisted
