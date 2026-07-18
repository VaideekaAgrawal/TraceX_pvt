"""
Rule Engine — a small set of parametrized graph/aggregation "primitives"
that both the 11 built-in rules (one per pre-existing detector sub-check)
and any user-defined rule compose. Ported unchanged (algorithmically) from
`archive/fund-flow-tracker/services/detection/rule_engine.py`.

Two tiers of rule:
  Tier 1 — a rule with exactly one, non-negated condition. Its primitive's
           native DetectionResults are returned directly (full detail
           preserved), so a built-in rule reproduces its original detector
           byte-for-byte.
  Tier 2 — 2+ conditions combined with AND/OR (and optional per-condition
           NOT). Each condition reduces to a per-account match set; the
           combinator intersects/unions them, and one synthetic
           DetectionResult is emitted per matched account.

Persistence swap from the archive (ROADMAP Phase 3): `RuleEngine.run_all`
read rules via `infrastructure.database.get_database().list_rules
(enabled_only=True)`; this port reads via `RuleDefinitionRepository.
list_enabled()` instead. `PrimitiveRegistry`/`RuleEvaluator` remain pure
functions with no DB dependency, as instructed.

`rule_definitions.dsl` JSON shape (this port's own design — the archive's
`rule_json` covered only `combinator`/`conditions`; `detection_type`/
`severity` were separate columns on its old ad-hoc `rules` table that this
schema's `rule_definitions` doesn't have):

    {
        "detection_type": "layering",       # what an emitted DetectionResult.detection_type will be
        "severity": "HIGH",                 # default severity for composite (Tier 2) matches
        "combinator": "AND",                # "AND" | "OR" -- Tier 2 only
        "conditions": [
            {"primitive": "chain", "params": {...}, "negate": false},
            ...
        ],
    }
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from db.repositories.detection import RuleDefinitionRepository
from detection.detectors.dormancy import DormancyDetector
from detection.detectors.fan_out import FanOutFanInDetector
from detection.detectors.layering import LayeringDetector
from detection.detectors.profile import ProfileMismatchDetector
from detection.detectors.round_trip import RoundTripDetector
from detection.detectors.structuring import StructuringDetector
from detection.graph.store import GraphStore
from detection.types import DetectionResult

logger = logging.getLogger(__name__)


class PrimitiveRegistry:
    """Parameter schemas/defaults for every primitive, and the dispatch
    that evaluates one against the current graph/data."""

    SCHEMAS: dict[str, dict[str, str]] = {
        "cycle": {"max_length": "int", "max_cycles": "int", "min_return_ratio": "float"},
        "chain": {
            "min_hops": "int", "time_window_minutes": "int", "extended_min_hops": "int",
            "extended_window_minutes": "int", "decay_ratio_threshold": "float",
        },
        "fan_degree": {
            "direction": "enum:fan_out,fan_in", "min_degree": "int", "window_days": "int",
        },
        "bipartite_scatter_gather": {"min_side": "int", "window_days": "int"},
        "amount_band_count": {
            "lower": "float", "upper": "float", "min_count": "int", "window_days": "int",
        },
        "split_sum_threshold": {"lower": "float", "upper": "float", "min_count": "int"},
        "inactivity_then_burst": {
            "threshold_days": "int", "min_burst_txns": "int", "multiplier": "float",
        },
        "volume_vs_declared_income_ratio": {"ratio_threshold": "float"},
        "peer_zscore_deviation": {"z_threshold": "float", "min_peer_group_size": "int"},
        "behavioural_shift": {
            "shift_z_threshold": "float", "min_txn_count": "int", "rolling_window": "int",
        },
        "generic_group_aggregate": {
            "group_by": "enum:source_account,dest_account",
            "agg": "enum:SUM,COUNT,AVG,MAX,MIN",
            "field": "str", "window_days": "int", "operator": "enum:>,>=,<,<=,==",
            "value": "float",
        },
    }

    DEFAULTS: dict[str, dict[str, Any]] = {
        "cycle": {"max_length": 12, "max_cycles": 2000, "min_return_ratio": 0.85},
        "chain": {"min_hops": 3, "time_window_minutes": 120, "extended_min_hops": 4,
                  "extended_window_minutes": 43200, "decay_ratio_threshold": 0.5},
        "fan_degree": {"direction": "fan_out", "min_degree": 3, "window_days": 30},
        "bipartite_scatter_gather": {"min_side": 3, "window_days": 30},
        "amount_band_count": {
            "lower": 900_000, "upper": 1_000_000, "min_count": 3, "window_days": 30,
        },
        "split_sum_threshold": {"lower": 900_000, "upper": 1_000_000, "min_count": 2},
        "inactivity_then_burst": {
            "threshold_days": 180, "min_burst_txns": 5, "multiplier": 10.0,
        },
        "volume_vs_declared_income_ratio": {"ratio_threshold": 10},
        "peer_zscore_deviation": {"z_threshold": 3.0, "min_peer_group_size": 5},
        "behavioural_shift": {"shift_z_threshold": 3, "min_txn_count": 15, "rolling_window": 20},
        "generic_group_aggregate": {"group_by": "source_account", "agg": "SUM", "field": "amount",
                                     "window_days": 30, "operator": ">", "value": 1_000_000},
    }

    # Sane ceilings on params that drive expensive graph traversals.
    CEILINGS: dict[str, dict[str, float]] = {
        "cycle": {"max_length": 20, "max_cycles": 5000},
        "chain": {"extended_window_minutes": 129_600},  # 90 days
        "fan_degree": {"window_days": 365},
        "bipartite_scatter_gather": {"window_days": 365},
        "generic_group_aggregate": {"window_days": 365},
    }

    @classmethod
    def list_primitives(cls) -> dict[str, dict[str, Any]]:
        return {
            name: {"params": schema, "defaults": cls.DEFAULTS.get(name, {}),
                   "ceilings": cls.CEILINGS.get(name, {})}
            for name, schema in cls.SCHEMAS.items()
        }

    @staticmethod
    def evaluate(
        primitive: str,
        params: dict[str, Any],
        graph_store: GraphStore,
        accounts_df: pd.DataFrame | None,
        transactions_df: pd.DataFrame,
    ) -> list[DetectionResult]:
        if primitive == "cycle":
            return RoundTripDetector(params).detect(graph_store, transactions_df)

        if primitive == "chain":
            return LayeringDetector(params).detect(graph_store, transactions_df)

        if primitive == "fan_degree":
            det = FanOutFanInDetector(params)
            df = _sorted_by_time(transactions_df)
            window_ns = int(det.cfg.fan_out_time_window_days * 86_400 * 1e9)
            direction = params.get("direction", "fan_out")
            if direction == "fan_in":
                return det._detect_fan(
                    df, group_col="dest_account", target_col="source_account",
                    min_fan=det.cfg.fan_out_min_degree, window_ns=window_ns, direction="fan_in",
                )
            return det._detect_fan(
                df, group_col="source_account", target_col="dest_account",
                min_fan=det.cfg.fan_out_min_degree, window_ns=window_ns, direction="fan_out",
            )

        if primitive == "bipartite_scatter_gather":
            det = FanOutFanInDetector(params)
            df = _sorted_by_time(transactions_df)
            window_ns = int(det.cfg.fan_out_time_window_days * 86_400 * 1e9)
            return det._detect_bipartite(
                df, min_side=det.cfg.bipartite_min_side, window_ns=window_ns
            )

        if primitive == "amount_band_count":
            return StructuringDetector(params)._detect_classic(transactions_df)

        if primitive == "split_sum_threshold":
            return StructuringDetector(params)._detect_split(transactions_df)

        if primitive == "inactivity_then_burst":
            return DormancyDetector(params).detect(graph_store, transactions_df)

        if primitive == "volume_vs_declared_income_ratio":
            if accounts_df is None:
                return []
            return ProfileMismatchDetector(params)._detect_income_mismatch(
                transactions_df, accounts_df
            )

        if primitive == "peer_zscore_deviation":
            if accounts_df is None:
                return []
            return ProfileMismatchDetector(params)._detect_peer_deviation(
                transactions_df, accounts_df
            )

        if primitive == "behavioural_shift":
            if accounts_df is None:
                return []
            return ProfileMismatchDetector(params)._detect_behavioural_shift(
                transactions_df, accounts_df
            )

        if primitive == "generic_group_aggregate":
            return _generic_group_aggregate(params, transactions_df)

        raise ValueError(f"Unknown primitive: {primitive}")


def _sorted_by_time(transactions_df: pd.DataFrame) -> pd.DataFrame:
    df = transactions_df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df.sort_values("timestamp").reset_index(drop=True)


def _generic_group_aggregate(
    params: dict[str, Any], transactions_df: pd.DataFrame
) -> list[DetectionResult]:
    """Fully generic escape hatch: group by account, aggregate a field over
    a rolling window, and flag accounts whose aggregate crosses a
    threshold — for ad-hoc new rules that don't need a real primitive."""
    group_by = params.get("group_by", "source_account")
    agg = str(params.get("agg", "SUM")).upper()
    field = params.get("field", "amount")
    window_days = params.get("window_days", 30)
    operator = params.get("operator", ">")
    value = float(params.get("value", 0))

    if group_by not in ("source_account", "dest_account") or field not in transactions_df.columns:
        return []

    df = transactions_df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    cutoff = df["timestamp"].max() - pd.Timedelta(days=window_days)
    windowed = df[df["timestamp"] >= cutoff]
    if windowed.empty:
        return []

    agg_map = {"SUM": "sum", "COUNT": "count", "AVG": "mean", "MAX": "max", "MIN": "min"}
    grouped = windowed.groupby(group_by)[field].agg(agg_map.get(agg, "sum"))

    ops = {
        ">": lambda x: x > value, ">=": lambda x: x >= value,
        "<": lambda x: x < value, "<=": lambda x: x <= value,
        "==": lambda x: x == value,
    }
    matched = grouped[ops.get(operator, ops[">"])(grouped)]

    results = []
    for acc_id, agg_val in matched.items():
        deviation = min(abs(float(agg_val) - value) / max(abs(value), 1.0), 0.5)
        score = round(min(1.0, 0.5 + deviation), 3)
        results.append(DetectionResult(
            detection_type="custom",
            account_ids=[str(acc_id)],
            score=score,
            severity="MEDIUM",
            details={
                "sub_type": "generic_group_aggregate", "group_by": group_by, "agg": agg,
                "field": field, "window_days": window_days, "operator": operator,
                "threshold": value, "actual_value": round(float(agg_val), 2),
            },
            indicators=[
                f"{agg}({field}) over {window_days}d {operator} {value:,.0f}: "
                f"actual={agg_val:,.2f}"
            ],
        ))
    return results


class RuleEvaluator:
    """Evaluates one rule (Tier 1 or Tier 2) against the current data."""

    _SEVERITY_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}

    @classmethod
    def evaluate_rule(
        cls,
        rule: dict[str, Any],
        graph_store: GraphStore,
        accounts_df: pd.DataFrame | None,
        transactions_df: pd.DataFrame,
    ) -> list[DetectionResult]:
        rule_json = rule.get("rule_json", {})
        conditions = rule_json.get("conditions", [])
        combinator = str(rule_json.get("combinator", "AND")).upper()
        if not conditions:
            return []

        if len(conditions) == 1 and not conditions[0].get("negate", False):
            cond = conditions[0]
            results = PrimitiveRegistry.evaluate(
                cond["primitive"], cond.get("params", {}),
                graph_store, accounts_df, transactions_df,
            )
            for r in results:
                r.detection_type = rule["detection_type"]
            return results

        return cls._evaluate_composite(
            rule, combinator, conditions, graph_store, accounts_df, transactions_df
        )

    @classmethod
    def _evaluate_composite(
        cls, rule, combinator, conditions, graph_store, accounts_df, transactions_df
    ) -> list[DetectionResult]:
        condition_sets: list[set] = []
        contributions: dict[str, list[DetectionResult]] = {}
        primitives_used: list[str] = []

        all_accounts = (
            set(accounts_df["account_id"].astype(str)) if accounts_df is not None else set()
        )

        for cond in conditions:
            primitives_used.append(cond["primitive"])
            results = PrimitiveRegistry.evaluate(
                cond["primitive"], cond.get("params", {}),
                graph_store, accounts_df, transactions_df,
            )
            matched: set[str] = set()
            for r in results:
                matched.update(str(a) for a in r.account_ids)
                for acc in r.account_ids:
                    contributions.setdefault(str(acc), []).append(r)
            if cond.get("negate", False):
                matched = all_accounts - matched
            condition_sets.append(matched)

        if not condition_sets:
            final: set = set()
        elif combinator == "OR":
            final = set.union(*condition_sets)
        else:
            final = set.intersection(*condition_sets)

        results = []
        for acc in sorted(final):
            contribs = contributions.get(acc, [])
            score = max((c.score for c in contribs), default=0.5)
            severity = max(
                (c.severity for c in contribs),
                key=lambda s: cls._SEVERITY_RANK.get(s, 1),
                default=rule.get("severity", "MEDIUM"),
            )
            results.append(DetectionResult(
                detection_type=rule["detection_type"],
                account_ids=[acc],
                score=round(score, 3),
                severity=severity,
                details={
                    "sub_type": "composite_rule", "rule_id": rule.get("rule_id", ""),
                    "rule_name": rule.get("name", ""), "combinator": combinator,
                    "primitives": primitives_used,
                },
                indicators=[f"Matched composite rule '{rule.get('name', '')}' "
                           f"({combinator} of {', '.join(primitives_used)})"],
            ))
        return results


def rule_definition_to_dict(rule) -> dict[str, Any]:
    """Adapt a `RuleDefinition` ORM row (`db/models/detection.py`) into the
    plain dict `RuleEvaluator.evaluate_rule` expects. `dsl` carries
    everything the archive's separate `rule_json`/`detection_type`/
    `severity` fields used to (see module docstring) — this schema has no
    separate columns for the latter two, so they live inside `dsl`."""
    dsl = rule.dsl or {}
    return {
        "rule_id": rule.rule_id,
        "name": rule.name,
        "detection_type": dsl.get("detection_type", rule.name),
        "severity": dsl.get("severity", "MEDIUM"),
        "rule_json": {
            "combinator": dsl.get("combinator", "AND"),
            "conditions": dsl.get("conditions", []),
        },
    }


class RuleEngine:
    """Loads enabled rules from the DB and evaluates all of them — the
    single call the (Phase 4+) detection pipeline makes in place of a
    hardcoded per-detector-type list."""

    def __init__(self, session: Session):
        self.rule_repo = RuleDefinitionRepository(session)

    def run_all(
        self,
        graph_store: GraphStore,
        accounts_df: pd.DataFrame | None,
        transactions_df: pd.DataFrame,
    ) -> dict[str, list[DetectionResult]]:
        rules = self.rule_repo.list_enabled()
        grouped: dict[str, list[DetectionResult]] = {}
        for rule in rules:
            rule_dict = rule_definition_to_dict(rule)
            try:
                results = RuleEvaluator.evaluate_rule(
                    rule_dict, graph_store, accounts_df, transactions_df
                )
            except Exception:
                logger.exception(
                    "Rule %s ('%s') failed to evaluate — skipping", rule.rule_id, rule.name
                )
                continue
            grouped.setdefault(rule_dict["detection_type"], []).extend(results)
        return grouped

    def dry_run(
        self,
        rule_json: dict[str, Any],
        detection_type: str,
        severity: str,
        graph_store: GraphStore,
        accounts_df: pd.DataFrame | None,
        transactions_df: pd.DataFrame,
    ) -> dict[str, Any]:
        """Evaluate a draft, unsaved rule against current data with no side
        effects — lets an analyst preview impact before saving/enabling."""
        fake_rule = {
            "rule_id": "__dry_run__", "name": "Dry Run", "detection_type": detection_type,
            "severity": severity, "rule_json": rule_json,
        }
        results = RuleEvaluator.evaluate_rule(fake_rule, graph_store, accounts_df, transactions_df)
        matched_accounts = sorted({a for r in results for a in r.account_ids})
        return {
            "matched_count": len(matched_accounts),
            "sample_matches": [r.to_dict() for r in results[:20]],
            "newly_flagged_accounts": matched_accounts[:50],
        }
