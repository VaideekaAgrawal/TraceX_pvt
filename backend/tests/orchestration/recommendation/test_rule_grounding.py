"""Rule grounding — ROADMAP Phase 9. Turns persisted alerts into structured
evidence and the eligible-action set."""
from __future__ import annotations

from sqlalchemy.orm import Session

from db.enums import DetectionType
from orchestration.recommendation import rule_grounding


def test_ground_case_builds_a_firing_from_the_alert(case_with_layering_alert: Session) -> None:
    ground = rule_grounding.ground_case(case_with_layering_alert, "CASE-REC-1")
    assert len(ground.firings) == 1
    firing = ground.firings[0]
    assert firing.typology == DetectionType.layering
    assert firing.rule_id == "builtin_layering"
    assert firing.primitive == "chain"
    assert set(firing.triggering_account_ids) == {"ACC-REC-1", "ACC-REC-2"}


def test_threshold_is_populated_from_the_rule_defaults(case_with_layering_alert: Session) -> None:
    # The seeded rule leaves params empty, so the threshold must fall back to the
    # chain primitive's documented defaults rather than an empty dict.
    ground = rule_grounding.ground_case(case_with_layering_alert, "CASE-REC-1")
    threshold = ground.firings[0].threshold
    assert threshold.get("min_hops") == 3
    assert "time_window_minutes" in threshold


def test_eligible_actions_are_gated_by_fired_typology(case_with_layering_alert: Session) -> None:
    ground = rule_grounding.ground_case(case_with_layering_alert, "CASE-REC-1")
    eligible = set(ground.eligible_action_ids)
    assert "TRACE_LAYERING_CHAIN" in eligible          # layering fired
    assert "FILE_STR" in eligible                       # disposition, always eligible
    assert "REVIEW_STRUCTURING_DEPOSITS" not in eligible  # structuring did not fire


def test_rule_anchors_payload_is_json_shaped(case_with_layering_alert: Session) -> None:
    ground = rule_grounding.ground_case(case_with_layering_alert, "CASE-REC-1")
    anchors = ground.to_rule_anchors()
    assert anchors["case_id"] == "CASE-REC-1"
    assert anchors["fired_typologies"] == ["layering"]
    assert anchors["firings"][0]["rule_id"] == "builtin_layering"
    assert "eligible_action_ids" in anchors


def test_no_alerts_means_no_firings_and_no_eligible_actions(session: Session) -> None:
    # A case id with no alerts (nothing seeded) grounds to empty.
    ground = rule_grounding.ground_case(session, "CASE-DOES-NOT-EXIST")
    assert ground.firings == []
    assert ground.eligible_action_ids == []
