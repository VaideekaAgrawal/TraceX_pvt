"""Recommendation Engine orchestration + validation — ROADMAP Phase 9.

These are the guardrail tests: an out-of-catalog action, an ineligible action,
and an ungrounded rationale must each be rejected *before* reaching the
investigator. The agentic loop is monkeypatched so nothing bills — the loop's
own mechanics are covered in `test_agent_loop.py`; here we drive its output
through the validator and persistence."""
from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.orm import Session

from db.enums import ActorType, AiAgent
from db.models.orchestration import AiInteraction
from foundation.config import Settings
from orchestration.agent_loop import AgentResult
from orchestration.grounding import FactBundle
from orchestration.recommendation import engine

ACTOR = ActorType.INVESTIGATOR
CASE_ID = "CASE-REC-1"
_FACT_KEY = "get_account_facts(account_id=ACC-REC-1).total_in"


def _settings() -> Settings:
    return Settings()


def _bundle_with_inflow() -> FactBundle:
    bundle = FactBundle()
    bundle.add_tool_result("get_account_facts", {"total_in": 250000.0}, {"account_id": "ACC-REC-1"})
    return bundle


def _grounded_rationale() -> dict[str, Any]:
    return {
        "claims": [
            {
                "statement": "Account ACC-REC-1 received a total inflow of 250000.0.",
                "citations": [{"fact_key": _FACT_KEY, "value": 250000.0}],
            }
        ]
    }


def _fake_loop(submission: dict[str, Any], bundle: FactBundle | None = None):
    """Build a stand-in for run_agent_loop that returns a canned AgentResult."""
    def _loop(**_kwargs: Any) -> AgentResult:
        return AgentResult(
            submission=submission, bundle=bundle or _bundle_with_inflow(),
            iterations=1, latency_ms=5,
        )
    return _loop


# ── happy path ──────────────────────────────────────────────────────────────


def test_valid_grounded_recommendation_is_accepted_ranked_and_persisted(
    case_with_layering_alert: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    submission = {
        "recommendations": [
            {"action_id": "TRACE_LAYERING_CHAIN", "rationale": _grounded_rationale()}
        ]
    }
    monkeypatch.setattr(engine, "run_agent_loop", _fake_loop(submission))

    result = engine.generate_recommendations(
        case_with_layering_alert, CASE_ID, settings=_settings(), actor_type=ACTOR, actor_id="U1"
    )

    assert len(result.recommendations) == 1
    rec = result.recommendations[0]
    assert rec.action_id == "TRACE_LAYERING_CHAIN"
    assert rec.rank == 1
    assert rec.confidence > 0
    assert "250000" in rec.narrative
    assert rec.regulatory_anchor["fatf"]
    assert rec.rule_anchor and rec.rule_anchor[0]["rule_id"] == "builtin_layering"
    assert _FACT_KEY in rec.cited_fact_keys

    # Persisted as an auditable ai_interactions row with facts + rule anchors.
    assert result.interaction_id is not None
    row = case_with_layering_alert.get(AiInteraction, result.interaction_id)
    assert row is not None
    assert row.agent == AiAgent.RECOMMENDATION
    assert row.facts and _FACT_KEY in row.facts
    assert row.rule_anchors and row.rule_anchors["fired_typologies"] == ["layering"]
    assert row.tools_called  # the loop's tool calls were recorded


# ── the three rejection paths ────────────────────────────────────────────────


def test_action_outside_the_catalog_is_rejected(
    case_with_layering_alert: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    submission = {
        "recommendations": [
            {"action_id": "DELETE_ALL_EVIDENCE", "rationale": _grounded_rationale()}
        ]
    }
    monkeypatch.setattr(engine, "run_agent_loop", _fake_loop(submission))
    result = engine.generate_recommendations(
        case_with_layering_alert, CASE_ID, settings=_settings(), actor_type=ACTOR, actor_id="U1"
    )
    assert result.recommendations == []
    assert result.rejected and result.rejected[0]["action_id"] == "DELETE_ALL_EVIDENCE"


def test_ineligible_but_real_action_is_rejected(
    case_with_layering_alert: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    # REVIEW_STRUCTURING_DEPOSITS is a real catalog action, but structuring did
    # not fire on this case — so it is not eligible and must be rejected.
    submission = {
        "recommendations": [
            {"action_id": "REVIEW_STRUCTURING_DEPOSITS", "rationale": _grounded_rationale()}
        ]
    }
    monkeypatch.setattr(engine, "run_agent_loop", _fake_loop(submission))
    result = engine.generate_recommendations(
        case_with_layering_alert, CASE_ID, settings=_settings(), actor_type=ACTOR, actor_id="U1"
    )
    assert result.recommendations == []
    assert result.rejected[0]["action_id"] == "REVIEW_STRUCTURING_DEPOSITS"


def test_ungrounded_rationale_is_rejected(
    case_with_layering_alert: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A real, eligible action, but the rationale states a number no tool produced.
    submission = {
        "recommendations": [
            {
                "action_id": "TRACE_LAYERING_CHAIN",
                "rationale": {
                    "claims": [
                        {
                            "statement": "The account moved a total of 9400000 through the chain.",
                            "citations": [{"fact_key": _FACT_KEY, "value": 250000.0}],
                        }
                    ]
                },
            }
        ]
    }
    monkeypatch.setattr(engine, "run_agent_loop", _fake_loop(submission))
    result = engine.generate_recommendations(
        case_with_layering_alert, CASE_ID, settings=_settings(), actor_type=ACTOR, actor_id="U1"
    )
    assert result.recommendations == []
    assert "ungrounded" in result.rejected[0]["reason"]


# ── no evidence → no model call ──────────────────────────────────────────────


def test_no_alerts_returns_empty_without_calling_the_model(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _explode(**_kwargs: Any) -> AgentResult:
        raise AssertionError("run_agent_loop must not be called when nothing fired")

    monkeypatch.setattr(engine, "run_agent_loop", _explode)
    result = engine.generate_recommendations(
        session, "CASE-EMPTY", settings=_settings(), actor_type=ACTOR, actor_id="U1"
    )
    assert result.recommendations == []
    assert result.interaction_id is None


# ── cross-question dialogue ──────────────────────────────────────────────────


def test_challenge_with_grounded_answer_is_persisted(
    case_with_layering_alert: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(engine, "run_agent_loop", _fake_loop(_grounded_rationale()))
    result = engine.answer_challenge(
        case_with_layering_alert, CASE_ID, "Why not close this as a false positive?",
        settings=_settings(), actor_type=ACTOR, actor_id="U1",
    )
    assert result.answered is True
    assert "250000" in result.narrative
    assert result.interaction_id is not None


def test_challenge_with_ungrounded_answer_is_not_persisted(
    case_with_layering_alert: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    ungrounded = {
        "claims": [
            {
                "statement": "There is definitely 9400000 of laundered money here.",
                "citations": [{"fact_key": _FACT_KEY, "value": 250000.0}],
            }
        ]
    }
    monkeypatch.setattr(engine, "run_agent_loop", _fake_loop(ungrounded))
    result = engine.answer_challenge(
        case_with_layering_alert, CASE_ID, "Prove it", settings=_settings(),
        actor_type=ACTOR, actor_id="U1",
    )
    assert result.answered is False
    assert result.interaction_id is None
    assert result.rejected_reason


def test_empty_challenge_is_rejected_without_a_model_call(
    case_with_layering_alert: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _explode(**_kwargs: Any) -> AgentResult:
        raise AssertionError("run_agent_loop must not be called for an empty question")

    monkeypatch.setattr(engine, "run_agent_loop", _explode)
    result = engine.answer_challenge(
        case_with_layering_alert, CASE_ID, "   ", settings=_settings(),
        actor_type=ACTOR, actor_id="U1",
    )
    assert result.answered is False
    assert result.interaction_id is None
