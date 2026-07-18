"""Copilot engine — ROADMAP Phase 10. The agent loop is monkeypatched (nothing
bills); these drive its output through grounding + re-hydration + persistence.

The headline test is the decision-9 proof: the reply the investigator sees has a
NAME, and the persisted record has only the customer_id — the name never crossed
to the model and is not stored."""
from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.orm import Session

from db.enums import ActorType, UserRole
from db.models.orchestration import AiInteraction
from db.models.platform import User
from db.repositories.platform import UserRepository
from foundation.config import Settings
from orchestration.agent_loop import AgentResult
from orchestration.copilot import engine
from orchestration.grounding import FactBundle


def _fake_loop(submission: dict[str, Any], bundle: FactBundle):
    def _loop(**_kwargs: Any) -> AgentResult:
        return AgentResult(submission=submission, bundle=bundle, iterations=1, latency_ms=5)
    return _loop


def _settings() -> Settings:
    return Settings()


def test_grounded_answer_rehydrated_for_display_but_tokenised_at_rest(
    session: Session, investigator: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = FactBundle()
    bundle.add_tool_result(
        "get_account_facts",
        {"customer": {"customer_id": "CUST-REHY-1"}, "total_in": 5000.0},
        {"account_id": "ACC-MINE"},
    )
    key = "get_account_facts(account_id=ACC-MINE).total_in"
    submission = {
        "claims": [
            {
                "statement": "Customer CUST-REHY-1's account received a total of 5000.",
                "citations": [{"fact_key": key, "value": 5000.0}],
            }
        ]
    }
    monkeypatch.setattr(engine, "run_agent_loop", _fake_loop(submission, bundle))

    result = engine.ask(session, investigator, "summarise my case", settings=_settings())

    assert result.answered is True
    # What the investigator sees: the real name (re-hydrated), id kept for trace.
    assert "Rajesh Kumar Sharma (CUST-REHY-1)" in result.answer
    # What is stored: the tokenised customer_id, and NO name.
    row = session.get(AiInteraction, result.interaction_id)
    assert row is not None
    assert str(row.agent) == "COPILOT"
    assert "CUST-REHY-1" in row.response_text
    assert "Rajesh" not in row.response_text
    assert row.case_id is None  # cross-case interaction
    # And the facts persisted for audit never contained a name either.
    assert "Rajesh" not in str(row.facts)


def test_ungrounded_answer_is_not_shown_or_persisted(
    session: Session, investigator: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = FactBundle()
    bundle.add_tool_result("list_my_cases", {"case_count": 1}, {})
    submission = {
        "claims": [
            {
                "statement": "You have 9000000 in laundered funds.",
                "citations": [{"fact_key": "list_my_cases.case_count", "value": 1}],
            }
        ]
    }
    monkeypatch.setattr(engine, "run_agent_loop", _fake_loop(submission, bundle))
    result = engine.ask(session, investigator, "how bad is it", settings=_settings())
    assert result.answered is False
    assert result.interaction_id is None


def test_no_assigned_cases_short_circuits_without_a_model_call(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = UserRepository(session).create(
        user_id="U-EMPTY", username="empty", email="empty@example.com", password_hash="x",
        role=UserRole.INVESTIGATOR, full_name="Empty", actor_type=ActorType.SYSTEM, actor_id=None,
    )
    session.commit()

    def _explode(**_kwargs: Any) -> AgentResult:
        raise AssertionError("run_agent_loop must not be called with no cases")

    monkeypatch.setattr(engine, "run_agent_loop", _explode)
    result = engine.ask(session, empty, "anything", settings=_settings())
    assert result.answered is False
    assert result.interaction_id is None


def test_empty_question_short_circuits(
    session: Session, investigator: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _explode(**_kwargs: Any) -> AgentResult:
        raise AssertionError("run_agent_loop must not be called for an empty question")

    monkeypatch.setattr(engine, "run_agent_loop", _explode)
    result = engine.ask(session, investigator, "   ", settings=_settings())
    assert result.answered is False
    assert result.interaction_id is None
