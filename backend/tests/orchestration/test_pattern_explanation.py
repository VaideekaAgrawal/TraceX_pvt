"""
`orchestration.pattern_explanation` -- ROADMAP Phase 6. Mirrors
`tests/orchestration/test_account_explanation.py`'s structure: cache hit on
repeat signature, cache miss on a different (unsorted-then-sorted)
account_ids set, zero `AiInteraction` rows on failure (the same regression
class `explain_account` was fixed for in Phase 5 -- must not regress here
either), `rule_anchors` populated on success.
"""
from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from db.enums import (
    ActorType,
    AiAgent,
    CaseLevel,
    CaseStatus,
    DetectionType,
    Priority,
    RiskLevel,
)
from db.repositories.detection import AlertRepository
from db.repositories.investigation import CaseAccountRepository, CaseRepository
from db.repositories.orchestration import AiInteractionRepository
from db.repositories.reference import AccountRepository
from foundation.config import Settings
from orchestration import pattern_explanation


def _seed(session: Session, *, account_ids: list[str] | None = None) -> None:
    account_ids = account_ids or ["A1", "A2"]
    for account_id in account_ids:
        AccountRepository(session).create(
            account_id=account_id, actor_type=ActorType.SYSTEM, actor_id=None
        )
    CaseRepository(session).create(
        case_id="CASE1", primary_account_id=account_ids[0], status=CaseStatus.IN_PROGRESS,
        level=CaseLevel.L2, priority=Priority.P1, actor_type=ActorType.SYSTEM, actor_id=None,
    )
    for account_id in account_ids:
        CaseAccountRepository(session).add_account(
            case_id="CASE1", account_id=account_id, actor_type=ActorType.SYSTEM, actor_id=None
        )
    AlertRepository(session).create(
        alert_id="AL1", detection_type=DetectionType.round_trip,
        primary_account_id=account_ids[0], account_ids=account_ids, score=0.85, risk_score=88.0,
        severity=RiskLevel.HIGH, priority=Priority.P1, confidence="high",
        rule_ids=["RULE_CYCLE_3"], status="open", source="pipeline", case_id="CASE1",
        actor_type=ActorType.SYSTEM, actor_id=None,
    )
    session.commit()


def _settings() -> Settings:
    return Settings(env="dev", jwt_secret="test-secret", openrouter_api_key="test-key")


def test_explain_pattern_first_call_writes_interaction_with_rule_anchors(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(session)
    calls: list[str] = []

    def _fake_call(prompt: str, *, settings: Settings, max_tokens: int = 300) -> str:
        calls.append(prompt)
        return "Fake pattern explanation."

    monkeypatch.setattr(pattern_explanation, "_call_openrouter", _fake_call)

    result = pattern_explanation.explain_pattern(
        session, "CASE1", "AL1",
        settings=_settings(), actor_type=ActorType.INVESTIGATOR, actor_id="U1",
    )
    session.commit()

    assert result["cached"] is False
    assert result["explanation"] == "Fake pattern explanation."
    assert len(calls) == 1
    assert result["rule_anchors"] == {
        "detection_type": "round_trip", "rule_ids": ["RULE_CYCLE_3"], "alert_id": "AL1",
    }

    interactions = AiInteractionRepository(session).list_for_case_and_agent(
        "CASE1", AiAgent.RECOMMENDATION
    )
    assert len(interactions) == 1
    assert interactions[0].rule_anchors is not None  # first real writer of this field
    assert interactions[0].facts is not None
    assert interactions[0].facts["pattern_signature"] == result["pattern_signature"]


def test_explain_pattern_cache_hit_on_repeat_signature(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(session)
    calls: list[str] = []

    def _fake_call(prompt: str, *, settings: Settings, max_tokens: int = 300) -> str:
        calls.append(prompt)
        return "Fake pattern explanation."

    monkeypatch.setattr(pattern_explanation, "_call_openrouter", _fake_call)

    first = pattern_explanation.explain_pattern(
        session, "CASE1", "AL1",
        settings=_settings(), actor_type=ActorType.INVESTIGATOR, actor_id="U1",
    )
    session.commit()
    assert len(calls) == 1

    second = pattern_explanation.explain_pattern(
        session, "CASE1", "AL1",
        settings=_settings(), actor_type=ActorType.INVESTIGATOR, actor_id="U1",
    )
    session.commit()

    assert second["cached"] is True
    assert second["explanation"] == first["explanation"]
    assert second["rule_anchors"] == first["rule_anchors"]
    assert len(calls) == 1  # no additional LLM call


def test_explain_pattern_force_bypasses_cache(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(session)
    calls: list[str] = []

    def _fake_call(prompt: str, *, settings: Settings, max_tokens: int = 300) -> str:
        calls.append(prompt)
        return f"Explanation #{len(calls)}."

    monkeypatch.setattr(pattern_explanation, "_call_openrouter", _fake_call)

    first = pattern_explanation.explain_pattern(
        session, "CASE1", "AL1",
        settings=_settings(), actor_type=ActorType.INVESTIGATOR, actor_id="U1",
    )
    session.commit()

    second = pattern_explanation.explain_pattern(
        session, "CASE1", "AL1",
        settings=_settings(), actor_type=ActorType.INVESTIGATOR, actor_id="U1", force=True,
    )
    session.commit()

    assert len(calls) == 2
    assert second["cached"] is False
    assert second["explanation"] != first["explanation"]


def test_compute_pattern_signature_is_order_independent() -> None:
    sig_a = pattern_explanation.compute_pattern_signature("round_trip", ["A1", "A2"])
    sig_b = pattern_explanation.compute_pattern_signature("round_trip", ["A2", "A1"])
    assert sig_a == sig_b


def test_compute_pattern_signature_differs_for_different_account_sets() -> None:
    sig_a = pattern_explanation.compute_pattern_signature("round_trip", ["A1", "A2"])
    sig_b = pattern_explanation.compute_pattern_signature("round_trip", ["A1", "A3"])
    assert sig_a != sig_b


def test_explain_pattern_different_alert_is_a_cache_miss(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(session, account_ids=["A1", "A2"])
    # A second alert on the same case, different detection_type -> different
    # pattern_signature -> must NOT reuse AL1's cached explanation.
    AlertRepository(session).create(
        alert_id="AL2", detection_type=DetectionType.layering,
        primary_account_id="A1", account_ids=["A1", "A2"], score=0.5, risk_score=50.0,
        severity=RiskLevel.MEDIUM, priority=Priority.P2, status="open", source="pipeline",
        case_id="CASE1", actor_type=ActorType.SYSTEM, actor_id=None,
    )
    session.commit()

    calls: list[str] = []

    def _fake_call(prompt: str, *, settings: Settings, max_tokens: int = 300) -> str:
        calls.append(prompt)
        return f"Explanation #{len(calls)}."

    monkeypatch.setattr(pattern_explanation, "_call_openrouter", _fake_call)

    pattern_explanation.explain_pattern(
        session, "CASE1", "AL1",
        settings=_settings(), actor_type=ActorType.INVESTIGATOR, actor_id="U1",
    )
    session.commit()
    result2 = pattern_explanation.explain_pattern(
        session, "CASE1", "AL2",
        settings=_settings(), actor_type=ActorType.INVESTIGATOR, actor_id="U1",
    )
    session.commit()

    assert len(calls) == 2  # both alerts triggered a real call
    assert result2["cached"] is False


def test_explain_pattern_rejects_alert_outside_case_scope(session: Session) -> None:
    _seed(session)
    CaseRepository(session).create(
        case_id="CASE2", primary_account_id="A1", status=CaseStatus.IN_PROGRESS,
        level=CaseLevel.L2, priority=Priority.P2, actor_type=ActorType.SYSTEM, actor_id=None,
    )
    session.commit()

    with pytest.raises(ValueError, match="does not belong to case"):
        pattern_explanation.explain_pattern(
            session, "CASE2", "AL1",
            settings=_settings(), actor_type=ActorType.INVESTIGATOR, actor_id="U1",
        )


def test_explain_pattern_failure_is_not_cached(session: Session) -> None:
    # Regression test (same class of bug `explain_account` was fixed for in
    # Phase 5): a failed/"not configured" call must never be written to
    # `ai_interactions` and served back as `cached: True` on a later call.
    _seed(session)
    settings = Settings(env="dev", jwt_secret="test-secret", openrouter_api_key="")

    first = pattern_explanation.explain_pattern(
        session, "CASE1", "AL1",
        settings=settings, actor_type=ActorType.INVESTIGATOR, actor_id="U1",
    )
    session.commit()
    assert first["cached"] is False
    assert first["rule_anchors"] is None

    second = pattern_explanation.explain_pattern(
        session, "CASE1", "AL1",
        settings=settings, actor_type=ActorType.INVESTIGATOR, actor_id="U1",
    )
    session.commit()
    assert second["cached"] is False  # still not cached, not a bad cache hit

    interactions = AiInteractionRepository(session).list_for_case_and_agent(
        "CASE1", AiAgent.RECOMMENDATION
    )
    assert interactions == []  # no failure ever persisted
