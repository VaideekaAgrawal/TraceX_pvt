from __future__ import annotations

import pandas as pd
import pytest

from db.enums import ActorType
from db.repositories.detection import RuleDefinitionRepository
from detection.graph.networkx_store import NetworkXGraphStore
from detection.rules.engine import PrimitiveRegistry, RuleEngine, RuleEvaluator


def _ts(s: str) -> pd.Timestamp:
    return pd.Timestamp(s)


@pytest.fixture()
def cycle_txns() -> pd.DataFrame:
    # A tight round-trip cycle A->B->C->A.
    return pd.DataFrame(
        [
            {"source_account": "A", "dest_account": "B", "amount": 100_000.0,
             "timestamp": _ts("2026-01-01 10:00"), "channel": "NEFT"},
            {"source_account": "B", "dest_account": "C", "amount": 98_000.0,
             "timestamp": _ts("2026-01-01 10:10"), "channel": "NEFT"},
            {"source_account": "C", "dest_account": "A", "amount": 95_000.0,
             "timestamp": _ts("2026-01-01 10:20"), "channel": "NEFT"},
        ]
    )


@pytest.fixture()
def structuring_txns() -> pd.DataFrame:
    # 3 near-threshold transactions from D -> classic structuring.
    return pd.DataFrame(
        [
            {"source_account": "D", "dest_account": "E", "amount": 950_000.0,
             "timestamp": _ts("2026-01-01 10:00"), "channel": "NEFT"},
            {"source_account": "D", "dest_account": "F", "amount": 960_000.0,
             "timestamp": _ts("2026-01-02 10:00"), "channel": "NEFT"},
            {"source_account": "D", "dest_account": "G", "amount": 970_000.0,
             "timestamp": _ts("2026-01-03 10:00"), "channel": "NEFT"},
        ]
    )


def _store(*dfs: pd.DataFrame) -> NetworkXGraphStore:
    txns = pd.concat(dfs, ignore_index=True)
    accounts = pd.DataFrame(
        {"account_id": pd.unique(pd.concat([txns["source_account"], txns["dest_account"]]))}
    )
    return NetworkXGraphStore(accounts, txns)


# ── PrimitiveRegistry ────────────────────────────────────────────────────


def test_list_primitives_includes_all_11() -> None:
    primitives = PrimitiveRegistry.list_primitives()
    assert len(primitives) == 11
    assert "cycle" in primitives
    assert "generic_group_aggregate" in primitives


def test_evaluate_unknown_primitive_raises(cycle_txns) -> None:
    store = _store(cycle_txns)
    with pytest.raises(ValueError, match="Unknown primitive"):
        PrimitiveRegistry.evaluate("not_a_real_primitive", {}, store, None, cycle_txns)


# ── RuleEvaluator: Tier 1 passthrough ────────────────────────────────────


def test_tier1_single_condition_reproduces_detector_output(cycle_txns) -> None:
    store = _store(cycle_txns)
    rule = {
        "rule_id": "R1",
        "name": "Round trip rule",
        "detection_type": "round_trip",
        "severity": "HIGH",
        "rule_json": {"combinator": "AND", "conditions": [{"primitive": "cycle", "params": {}}]},
    }
    results = RuleEvaluator.evaluate_rule(rule, store, None, cycle_txns)
    assert len(results) == 1
    assert results[0].detection_type == "round_trip"
    assert set(results[0].account_ids) == {"A", "B", "C"}
    # Tier 1 preserves the detector's own full detail dict.
    assert "cycle_nodes" in results[0].details


def test_tier1_empty_conditions_returns_nothing(cycle_txns) -> None:
    store = _store(cycle_txns)
    rule = {
        "rule_id": "R0", "name": "Empty", "detection_type": "custom", "severity": "LOW",
        "rule_json": {"combinator": "AND", "conditions": []},
    }
    assert RuleEvaluator.evaluate_rule(rule, store, None, cycle_txns) == []


# ── RuleEvaluator: Tier 2 composition ────────────────────────────────────


def test_tier2_and_intersects_two_primitives(cycle_txns, structuring_txns) -> None:
    txns = pd.concat([cycle_txns, structuring_txns], ignore_index=True)
    store = _store(txns)
    accounts = pd.DataFrame(
        {"account_id": pd.unique(pd.concat([txns["source_account"], txns["dest_account"]]))}
    )
    # No account is in both the cycle and the structuring flag set -> AND is empty.
    rule = {
        "rule_id": "R2", "name": "AND rule", "detection_type": "custom", "severity": "HIGH",
        "rule_json": {
            "combinator": "AND",
            "conditions": [
                {"primitive": "cycle", "params": {}},
                {"primitive": "amount_band_count", "params": {}},
            ],
        },
    }
    results = RuleEvaluator.evaluate_rule(rule, store, accounts, txns)
    assert results == []


def test_tier2_or_unions_two_primitives(cycle_txns, structuring_txns) -> None:
    txns = pd.concat([cycle_txns, structuring_txns], ignore_index=True)
    store = _store(txns)
    accounts = pd.DataFrame(
        {"account_id": pd.unique(pd.concat([txns["source_account"], txns["dest_account"]]))}
    )
    rule = {
        "rule_id": "R3", "name": "OR rule", "detection_type": "custom", "severity": "HIGH",
        "rule_json": {
            "combinator": "OR",
            "conditions": [
                {"primitive": "cycle", "params": {}},
                {"primitive": "amount_band_count", "params": {}},
            ],
        },
    }
    results = RuleEvaluator.evaluate_rule(rule, store, accounts, txns)
    matched = {r.account_ids[0] for r in results}
    # A/B/C from the cycle, D from structuring.
    assert {"A", "B", "C", "D"} <= matched
    for r in results:
        assert r.detection_type == "custom"
        assert r.details["sub_type"] == "composite_rule"


def test_tier2_negate_inverts_the_match_set(cycle_txns) -> None:
    store = _store(cycle_txns)
    accounts = pd.DataFrame({"account_id": ["A", "B", "C", "ZZZ"]})
    rule = {
        "rule_id": "R4", "name": "Negate rule", "detection_type": "custom", "severity": "LOW",
        "rule_json": {
            "combinator": "AND",
            "conditions": [
                {"primitive": "cycle", "params": {}, "negate": True},
            ],
        },
    }
    results = RuleEvaluator.evaluate_rule(rule, store, accounts, cycle_txns)
    matched = {r.account_ids[0] for r in results}
    # Negating the cycle-match set over the account universe leaves only
    # the account that was NOT part of the cycle.
    assert matched == {"ZZZ"}


# ── RuleEngine: DB-backed run_all + dry_run ──────────────────────────────


def test_run_all_evaluates_only_enabled_rules(session, cycle_txns) -> None:
    repo = RuleDefinitionRepository(session)
    repo.create(
        rule_id="RULE-ENABLED",
        name="Enabled cycle rule",
        dsl={
            "detection_type": "round_trip",
            "severity": "HIGH",
            "combinator": "AND",
            "conditions": [{"primitive": "cycle", "params": {}}],
        },
        tier=1,
        confidence=0.9,
        enabled=True,
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    repo.create(
        rule_id="RULE-DISABLED",
        name="Disabled cycle rule",
        dsl={
            "detection_type": "round_trip",
            "severity": "HIGH",
            "combinator": "AND",
            "conditions": [{"primitive": "cycle", "params": {}}],
        },
        tier=1,
        confidence=0.9,
        enabled=False,
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    session.commit()

    store = _store(cycle_txns)
    engine = RuleEngine(session)
    grouped = engine.run_all(store, None, cycle_txns)

    assert "round_trip" in grouped
    assert len(grouped["round_trip"]) == 1


def test_run_all_skips_a_failing_rule_without_crashing(session, cycle_txns) -> None:
    repo = RuleDefinitionRepository(session)
    repo.create(
        rule_id="RULE-BAD",
        name="Bad primitive",
        dsl={
            "detection_type": "custom",
            "combinator": "AND",
            "conditions": [{"primitive": "does_not_exist", "params": {}}],
        },
        tier=1,
        confidence=0.5,
        enabled=True,
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    session.commit()

    store = _store(cycle_txns)
    engine = RuleEngine(session)
    grouped = engine.run_all(store, None, cycle_txns)
    assert grouped == {}


def test_dry_run_reports_matches_with_no_persistence(session, cycle_txns) -> None:
    store = _store(cycle_txns)
    engine = RuleEngine(session)
    result = engine.dry_run(
        rule_json={"combinator": "AND", "conditions": [{"primitive": "cycle", "params": {}}]},
        detection_type="round_trip",
        severity="HIGH",
        graph_store=store,
        accounts_df=None,
        transactions_df=cycle_txns,
    )
    assert result["matched_count"] == 3
    assert set(result["newly_flagged_accounts"]) == {"A", "B", "C"}
    assert len(result["sample_matches"]) == 1

    # No rule_definitions row was created by dry_run.
    assert RuleDefinitionRepository(session).list_enabled() == []
