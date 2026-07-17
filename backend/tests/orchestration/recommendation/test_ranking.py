"""Deterministic ranking — ROADMAP Phase 9.

Ranking is evidence-weighted and deterministic; these pin the ordering
properties the engine and investigator depend on."""
from __future__ import annotations

from db.enums import DetectionType
from orchestration.recommendation import action_catalog, ranking
from orchestration.recommendation.rule_grounding import CaseGrounding, RuleFiring


def _firing(
    typology: DetectionType, severity: str, score: float, accounts: list[str]
) -> RuleFiring:
    return RuleFiring(
        alert_id=f"AL-{typology}-{severity}",
        typology=typology,
        triggering_account_ids=accounts,
        score=score,
        severity=severity,
    )


def test_critical_firing_scores_higher_than_medium() -> None:
    action = action_catalog.get_action("TRACE_LAYERING_CHAIN")
    assert action is not None
    critical = CaseGrounding("C", [_firing(DetectionType.layering, "CRITICAL", 0.9, ["A"])])
    medium = CaseGrounding("C", [_firing(DetectionType.layering, "MEDIUM", 0.5, ["A"])])
    assert ranking.score_action(action, critical) > ranking.score_action(action, medium)


def test_more_implicated_accounts_raise_the_score() -> None:
    action = action_catalog.get_action("TRACE_LAYERING_CHAIN")
    assert action is not None
    narrow = CaseGrounding("C", [_firing(DetectionType.layering, "HIGH", 0.7, ["A"])])
    wide = CaseGrounding(
        "C", [_firing(DetectionType.layering, "HIGH", 0.7, ["A", "B", "C", "D", "E"])]
    )
    assert ranking.score_action(action, wide) > ranking.score_action(action, narrow)


def test_action_with_no_relevant_firing_scores_zero() -> None:
    # A structuring-specific action against a layering-only case.
    action = action_catalog.get_action("REVIEW_STRUCTURING_DEPOSITS")
    assert action is not None
    ground = CaseGrounding("C", [_firing(DetectionType.layering, "HIGH", 0.7, ["A"])])
    assert ranking.score_action(action, ground) == 0.0


def test_rank_actions_is_deterministic_and_tie_broken_by_catalog_order() -> None:
    a1 = action_catalog.get_action("FILE_STR")
    a2 = action_catalog.get_action("ESCALATE_TO_L2")
    assert a1 is not None and a2 is not None
    # Equal scores → catalog order decides; FILE_STR precedes ESCALATE_TO_L2.
    ranked = ranking.rank_actions([(a2, 0.5), (a1, 0.5)])
    assert [a.action_id for a, _, _ in ranked] == ["FILE_STR", "ESCALATE_TO_L2"]
    assert [r for _, _, r in ranked] == [1, 2]
