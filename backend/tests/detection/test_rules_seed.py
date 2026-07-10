from __future__ import annotations

from sqlalchemy.orm import Session

from db.enums import ActorType, DetectionType
from db.repositories.detection import RuleDefinitionRepository
from detection.rules.seed import _BUILTIN_RULES, seed_builtin_rules


def test_seed_builtin_rules_creates_all_rules_once(session: Session) -> None:
    created = seed_builtin_rules(session, actor_type=ActorType.SYSTEM, actor_id=None)
    session.commit()
    assert len(created) == len(_BUILTIN_RULES)

    repo = RuleDefinitionRepository(session)
    enabled = repo.list_enabled()
    assert len(enabled) == len(_BUILTIN_RULES)


def test_seed_builtin_rules_only_uses_valid_detection_types() -> None:
    valid_types = {dt.value for dt in DetectionType}
    for spec in _BUILTIN_RULES:
        assert spec["detection_type"] in valid_types


def test_seed_builtin_rules_is_idempotent(session: Session) -> None:
    first = seed_builtin_rules(session, actor_type=ActorType.SYSTEM, actor_id=None)
    session.commit()
    second = seed_builtin_rules(session, actor_type=ActorType.SYSTEM, actor_id=None)
    session.commit()

    assert len(first) == len(_BUILTIN_RULES)
    assert second == []

    repo = RuleDefinitionRepository(session)
    assert len(repo.list_enabled()) == len(_BUILTIN_RULES)


def test_seed_builtin_rules_dsl_shape_is_tier_one(session: Session) -> None:
    seed_builtin_rules(session, actor_type=ActorType.SYSTEM, actor_id=None)
    session.commit()

    repo = RuleDefinitionRepository(session)
    rule = repo.get("builtin_round_trip")
    assert rule is not None
    assert rule.tier == 1
    assert rule.dsl["conditions"][0]["primitive"] == "cycle"
    assert rule.dsl["conditions"][0]["params"] == {}
