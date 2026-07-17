"""Action catalog invariants — ROADMAP Phase 9.

The catalog is a closed action space; these guard the properties the engine
relies on: stable unique ids, a regulatory anchor on every action, and correct
typology gating."""
from __future__ import annotations

from db.enums import DetectionType
from orchestration.recommendation import action_catalog


def test_action_ids_are_unique() -> None:
    ids = [a.action_id for a in action_catalog.all_actions()]
    assert len(ids) == len(set(ids))


def test_catalog_lookup_matches_all_actions() -> None:
    assert set(action_catalog.CATALOG) == {a.action_id for a in action_catalog.all_actions()}


def test_every_action_carries_a_regulatory_anchor() -> None:
    # A recommendation's defensibility rests on its anchor; none may be missing.
    for action in action_catalog.all_actions():
        anchor = action.regulatory_anchor
        assert anchor.fatf, action.action_id
        assert anchor.india, action.action_id


def test_get_action_returns_none_for_an_unknown_id() -> None:
    assert action_catalog.get_action("NOT_A_REAL_ACTION") is None


def test_typology_specific_action_requires_its_typology() -> None:
    # TRACE_LAYERING_CHAIN is eligible only when layering fired.
    with_layering = {
        a.action_id for a in action_catalog.actions_for_typologies({DetectionType.layering})
    }
    without = {
        a.action_id for a in action_catalog.actions_for_typologies({DetectionType.structuring})
    }
    assert "TRACE_LAYERING_CHAIN" in with_layering
    assert "TRACE_LAYERING_CHAIN" not in without


def test_cross_cutting_and_disposition_actions_are_always_eligible() -> None:
    # FILE_STR / EXPAND_NETWORK_INVESTIGATION have no typology gate: eligible on
    # any fired typology.
    for fired in ({DetectionType.layering}, {DetectionType.structuring}, {DetectionType.dormancy}):
        ids = {a.action_id for a in action_catalog.actions_for_typologies(fired)}
        assert "FILE_STR" in ids
        assert "EXPAND_NETWORK_INVESTIGATION" in ids


def test_structuring_specific_action_gated_correctly() -> None:
    ids = {a.action_id for a in action_catalog.actions_for_typologies({DetectionType.structuring})}
    assert "REVIEW_STRUCTURING_DEPOSITS" in ids
    assert "REVIEW_DORMANCY_REACTIVATION" not in ids
