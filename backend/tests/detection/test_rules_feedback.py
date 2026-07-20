"""Rule-confidence learning from verdicts — ROADMAP Phase 12
(`detection.rules.feedback.adjust_rule_confidence`)."""
from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from db.enums import ActorType
from db.repositories.detection import RuleDefinitionRepository
from detection.rules.feedback import _FLOOR, _LEARNING_RATE, adjust_rule_confidence


def _seed_rule(session: Session, rule_id: str, confidence: float) -> None:
    RuleDefinitionRepository(session).create(
        rule_id=rule_id, name=rule_id, dsl={"primitive": "chain"}, tier=1,
        confidence=confidence, actor_type=ActorType.SYSTEM, actor_id=None,
    )


def _conf(session: Session, rule_id: str) -> float:
    rule = RuleDefinitionRepository(session).get(rule_id)
    assert rule is not None
    return rule.confidence


def test_true_positive_nudges_confidence_up_toward_one(session: Session) -> None:
    _seed_rule(session, "R1", 0.50)
    changes = adjust_rule_confidence(
        session, ["R1"], is_true_positive=True,
        actor_type=ActorType.ADMIN, actor_id="A1",
    )
    # EWMA toward 1.0: 0.5 + 0.1*(1.0-0.5) = 0.55
    assert _conf(session, "R1") == 0.55
    assert len(changes) == 1
    assert changes[0].old == 0.50 and changes[0].new == 0.55


def test_false_positive_nudges_confidence_down_toward_zero(session: Session) -> None:
    _seed_rule(session, "R1", 0.50)
    adjust_rule_confidence(
        session, ["R1"], is_true_positive=False,
        actor_type=ActorType.ADMIN, actor_id="A1",
    )
    # EWMA toward 0.0: 0.5 + 0.1*(0.0-0.5) = 0.45
    assert _conf(session, "R1") == 0.45


def test_repeated_false_positives_trend_toward_floor_but_never_below(
    session: Session,
) -> None:
    _seed_rule(session, "R1", 0.20)
    for _ in range(200):
        adjust_rule_confidence(
            session, ["R1"], is_true_positive=False,
            actor_type=ActorType.ADMIN, actor_id="A1",
        )
    # Clamped at the floor — a noisy rule goes visibly low but is never
    # auto-disabled (that's a human decision via the `enabled` flag).
    assert _conf(session, "R1") == _FLOOR


def test_multiple_fired_rules_all_adjusted(session: Session) -> None:
    _seed_rule(session, "R1", 0.50)
    _seed_rule(session, "R2", 0.80)
    changes = adjust_rule_confidence(
        session, ["R1", "R2"], is_true_positive=True,
        actor_type=ActorType.ADMIN, actor_id="A1",
    )
    assert {c.rule_id for c in changes} == {"R1", "R2"}
    assert _conf(session, "R1") == pytest.approx(0.55)
    assert _conf(session, "R2") == pytest.approx(0.82)  # 0.8 + 0.1*0.2


def test_unknown_rule_id_skipped_not_raised(session: Session) -> None:
    _seed_rule(session, "R1", 0.50)
    # A stale rule_id on an old alert must not abort the close.
    changes = adjust_rule_confidence(
        session, ["R1", "GONE"], is_true_positive=True,
        actor_type=ActorType.ADMIN, actor_id="A1",
    )
    assert [c.rule_id for c in changes] == ["R1"]


def test_empty_or_none_rule_ids_noop(session: Session) -> None:
    assert adjust_rule_confidence(
        session, None, is_true_positive=True, actor_type=ActorType.ADMIN, actor_id="A1"
    ) == []
    assert adjust_rule_confidence(
        session, [], is_true_positive=False, actor_type=ActorType.ADMIN, actor_id="A1"
    ) == []


def test_learning_rate_is_conservative() -> None:
    # A single verdict moves confidence by at most LEARNING_RATE * full-span;
    # guards against a future tweak that would let one close swing a rule.
    assert _LEARNING_RATE <= 0.2
