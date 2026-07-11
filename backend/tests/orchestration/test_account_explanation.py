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
    DetectionType,
    EntityType,
    Priority,
    RiskLevel,
    UserRole,
)
from db.repositories.detection import AlertRepository
from db.repositories.investigation import CaseAccountRepository, CaseRepository
from db.repositories.orchestration import AiInteractionRepository
from db.repositories.platform import UserRepository
from db.repositories.reference import AccountRepository, CustomerRepository, TransactionRepository
from foundation.config import Settings
from orchestration import account_explanation

# A recognizable marker only ever written into narration/purpose -- if it
# leaks into the assembled facts or the built prompt, the guardrail this
# module's docstring promises ("Transaction.narration/purpose are
# deliberately EXCLUDED") is broken.
_SECRET_NARRATION = "SECRET_NARRATION_MARKER_do_not_leak_to_llm"
_SECRET_PURPOSE = "SECRET_PURPOSE_MARKER_do_not_leak_to_llm"


def _seed(session: Session) -> None:
    AccountRepository(session).create(
        account_id="A1",
        customer_id="CUST1",
        branch_city="Mumbai",
        current_risk_score=72.0,
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    AccountRepository(session).create(
        account_id="A2", actor_type=ActorType.SYSTEM, actor_id=None
    )
    CustomerRepository(session).create(
        customer_id="CUST1",
        name="Test Customer",
        entity_type=EntityType.INDIVIDUAL,
        risk_rating=RiskLevel.HIGH,
        occupation="Trader",
        declared_annual_income=500_000.0,
        income_bracket="5-10L",
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    UserRepository(session).create(
        user_id="U1",
        username="inv1",
        email="inv1@example.com",
        password_hash="x",
        role=UserRole.INVESTIGATOR,
        full_name="Investigator One",
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    CaseRepository(session).create(
        case_id="CASE1",
        primary_account_id="A1",
        status=CaseStatus.IN_PROGRESS,
        level=CaseLevel.L1,
        priority=Priority.P1,
        risk_score=80.0,
        network_risk_score=55.0,
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    CaseAccountRepository(session).add_account(
        case_id="CASE1", account_id="A1", actor_type=ActorType.SYSTEM, actor_id=None
    )
    ts = datetime(2026, 1, 1, tzinfo=UTC)
    TransactionRepository(session).create(
        txn_id="T1",
        timestamp=ts,
        source_account="A2",
        dest_account="A1",
        amount=10_000.0,
        channel=Channel.NEFT,
        is_laundering=0,
        ingested_at=ts,
        narration=_SECRET_NARRATION,
        purpose=_SECRET_PURPOSE,
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    AlertRepository(session).create(
        alert_id="AL1",
        detection_type=DetectionType.layering,
        primary_account_id="A1",
        account_ids=["A1"],
        score=0.8,
        risk_score=80.0,
        severity=RiskLevel.HIGH,
        priority=Priority.P1,
        status="open",
        source="pipeline",
        case_id="CASE1",
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    session.commit()


def _settings() -> Settings:
    return Settings(env="dev", jwt_secret="test-secret", openrouter_api_key="test-key")


def test_explain_account_first_call_writes_interaction_and_is_not_cached(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(session)
    calls: list[str] = []

    def _fake_call(prompt: str, *, settings: Settings, max_tokens: int = 300) -> str:
        calls.append(prompt)
        return "Fake explanation."

    monkeypatch.setattr(account_explanation, "_call_openrouter", _fake_call)

    result = account_explanation.explain_account(
        session, "CASE1", "A1",
        settings=_settings(), actor_type=ActorType.INVESTIGATOR, actor_id="U1",
    )
    session.commit()

    assert result["cached"] is False
    assert result["explanation"] == "Fake explanation."
    assert len(calls) == 1

    interactions = AiInteractionRepository(session).list_for_case_and_agent(
        "CASE1", AiAgent.RECOMMENDATION
    )
    assert len(interactions) == 1
    assert interactions[0].facts is not None
    assert interactions[0].facts["account_id"] == "A1"
    assert interactions[0].response_text == "Fake explanation."


def test_explain_account_second_call_is_cached_with_no_additional_llm_call(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(session)
    calls: list[str] = []

    def _fake_call(prompt: str, *, settings: Settings, max_tokens: int = 300) -> str:
        calls.append(prompt)
        return "Fake explanation."

    monkeypatch.setattr(account_explanation, "_call_openrouter", _fake_call)

    first = account_explanation.explain_account(
        session, "CASE1", "A1",
        settings=_settings(), actor_type=ActorType.INVESTIGATOR, actor_id="U1",
    )
    session.commit()
    assert len(calls) == 1

    second = account_explanation.explain_account(
        session, "CASE1", "A1",
        settings=_settings(), actor_type=ActorType.INVESTIGATOR, actor_id="U1",
    )
    session.commit()

    assert second["cached"] is True
    assert second["explanation"] == first["explanation"]
    assert len(calls) == 1  # no additional stub call


def test_explain_account_force_bypasses_cache(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(session)
    calls: list[str] = []

    def _fake_call(prompt: str, *, settings: Settings, max_tokens: int = 300) -> str:
        calls.append(prompt)
        return f"Explanation #{len(calls)}."

    monkeypatch.setattr(account_explanation, "_call_openrouter", _fake_call)

    first = account_explanation.explain_account(
        session, "CASE1", "A1",
        settings=_settings(), actor_type=ActorType.INVESTIGATOR, actor_id="U1",
    )
    session.commit()

    second = account_explanation.explain_account(
        session, "CASE1", "A1",
        settings=_settings(), actor_type=ActorType.INVESTIGATOR, actor_id="U1", force=True,
    )
    session.commit()

    assert len(calls) == 2
    assert second["cached"] is False
    assert second["explanation"] != first["explanation"]


def test_explain_account_facts_and_prompt_never_contain_narration_or_purpose(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(session)
    captured_prompts: list[str] = []

    def _fake_call(prompt: str, *, settings: Settings, max_tokens: int = 300) -> str:
        captured_prompts.append(prompt)
        return "Fake explanation."

    monkeypatch.setattr(account_explanation, "_call_openrouter", _fake_call)

    account_explanation.explain_account(
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


def test_explain_account_rejects_account_outside_case_scope(session: Session) -> None:
    _seed(session)
    with pytest.raises(ValueError, match="not in case"):
        account_explanation.explain_account(
            session, "CASE1", "A2",
            settings=_settings(), actor_type=ActorType.INVESTIGATOR, actor_id="U1",
        )


def test_call_openrouter_not_configured_raises_explanation_unavailable(session: Session) -> None:
    settings = Settings(env="dev", jwt_secret="test-secret", openrouter_api_key="")
    with pytest.raises(
        account_explanation.ExplanationUnavailableError,
        match=account_explanation._NOT_CONFIGURED_MESSAGE,
    ):
        account_explanation._call_openrouter("hello", settings=settings)


def test_explain_account_failure_is_not_cached(session: Session) -> None:
    # Regression test (code-review finding, Phase 5): a failed/"not
    # configured" call must never be written to `ai_interactions` and
    # served back as `cached: True` on a later call.
    _seed(session)
    settings = Settings(env="dev", jwt_secret="test-secret", openrouter_api_key="")

    first = account_explanation.explain_account(
        session, "CASE1", "A1",
        settings=settings, actor_type=ActorType.INVESTIGATOR, actor_id="U1",
    )
    session.commit()
    assert first["cached"] is False
    assert first["explanation"] == account_explanation._NOT_CONFIGURED_MESSAGE

    second = account_explanation.explain_account(
        session, "CASE1", "A1",
        settings=settings, actor_type=ActorType.INVESTIGATOR, actor_id="U1",
    )
    session.commit()
    assert second["cached"] is False  # still not cached, not a bad cache hit

    interactions = AiInteractionRepository(session).list_for_case_and_agent(
        "CASE1", AiAgent.RECOMMENDATION
    )
    assert interactions == []  # no failure ever persisted
