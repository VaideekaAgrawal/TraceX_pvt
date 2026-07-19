"""
Idempotent seed of the built-in Rule Engine rules -- one Tier-1 rule per
pre-existing pattern detector, ported from the archive's
`infrastructure.database.Database._seed_builtin_rules_if_missing` (same
`rule_id`/name/`detection_type`/severity/primitive choices), adapted to this
port's `RuleDefinitionRepository`/`rule_definitions.dsl` shape (see
`detection/rules/engine.py`'s module docstring for the JSON shape).

Not part of Phase 3's file list -- added here (ROADMAP Phase 4) because
without it, a fresh DB has zero enabled `rule_definitions` rows and
`RuleEngine.run_all` (correctly) returns nothing to alert on. Phase 3 ported
the DSL/evaluator engine itself but never seeded any actual rule rows; this
is the small piece of plumbing that makes `scripts/run_detection_pipeline.py`
produce real alerts end to end, which is squarely Phase 4's charge ("alert
generation from detection results"), not a Phase 3 gap being opportunistically
fixed here.

Two archive-vs-port differences, both deliberate:
  1. `params` are left empty (`{}`) rather than mirroring the archive's
     explicit threshold values -- every ported detector already defaults
     each param key from `DEFAULT_DETECTION_CONFIG` (`detection/config.py`)
     when the key is absent from `params` (confirmed identical values), so
     an empty dict reproduces the exact same behavior without duplicating
     tuned thresholds into seed data (a second place they could drift out
     of sync).
  2. The archive seeded 11 built-in rules, three of which
     (`builtin_fan_out`, `builtin_fan_in`, `builtin_bipartite`) use
     `detection_type in {"fan_out", "fan_in"}` -- neither is a member of
     this port's `DetectionType` enum (`db/enums.py`: only layering,
     round_trip, structuring, dormancy, profile_mismatch survived the
     Phase 1 schema design). Alerts can only be persisted with a valid
     `DetectionType` (`investigation.alerts.generate_alerts_from_detection`
     skips anything else with a warning), so those 3 rules are not seeded
     here. This is a real, pre-existing schema/archive gap -- not something
     Phase 4 is scoped to fix by extending the enum -- flagged in
     `docs/SESSION_LOG.md`.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from db.enums import ActorType
from db.models.detection import RuleDefinition
from db.repositories.detection import RuleDefinitionRepository

_BUILTIN_RULES: list[dict[str, str]] = [
    {
        "rule_id": "builtin_round_trip",
        "name": "Round-Trip Circular Flow",
        "detection_type": "round_trip",
        "severity": "HIGH",
        "primitive": "cycle",
    },
    {
        "rule_id": "builtin_layering",
        "name": "Multi-Hop Layering Chain",
        "detection_type": "layering",
        "severity": "HIGH",
        "primitive": "chain",
    },
    {
        "rule_id": "builtin_structuring_classic",
        "name": "Structuring - Near-Threshold Amounts",
        "detection_type": "structuring",
        "severity": "HIGH",
        "primitive": "amount_band_count",
    },
    {
        "rule_id": "builtin_structuring_split",
        "name": "Structuring - Split Daily Total",
        "detection_type": "structuring",
        "severity": "HIGH",
        "primitive": "split_sum_threshold",
    },
    {
        "rule_id": "builtin_dormancy",
        "name": "Dormant Account Reactivation",
        "detection_type": "dormancy",
        "severity": "MEDIUM",
        "primitive": "inactivity_then_burst",
    },
    {
        "rule_id": "builtin_income_mismatch",
        "name": "Income vs. Volume Mismatch",
        "detection_type": "profile_mismatch",
        "severity": "MEDIUM",
        "primitive": "volume_vs_declared_income_ratio",
    },
    {
        "rule_id": "builtin_peer_deviation",
        "name": "Peer Group Volume Deviation",
        "detection_type": "profile_mismatch",
        "severity": "MEDIUM",
        "primitive": "peer_zscore_deviation",
    },
    {
        "rule_id": "builtin_behavioural_shift",
        "name": "Sudden Behavioural Shift",
        "detection_type": "profile_mismatch",
        "severity": "MEDIUM",
        "primitive": "behavioural_shift",
    },
]

#: Invented starting point, not derived from any spec -- Phase 12's feedback
#: loop (`detection.rules.feedback`) adjusts `rule_definitions.confidence` from
#: real investigator verdicts from here. Public because the Phase 12 admin review
#: queue mints an approved proposal at the same starting confidence -- one source
#: of truth for "a brand-new rule's confidence."
DEFAULT_RULE_CONFIDENCE = 0.75
#: Back-compat alias for the pre-Phase-12 private name used within this module.
_DEFAULT_CONFIDENCE = DEFAULT_RULE_CONFIDENCE


def seed_builtin_rules(
    session: Session, *, actor_type: ActorType, actor_id: str | None
) -> list[RuleDefinition]:
    """Create any of `_BUILTIN_RULES` not already present (by `rule_id`).
    Idempotent (`INSERT`-only, skips existing rows) -- safe to call on every
    pipeline run. Only flushes (via `RuleDefinitionRepository`); the caller
    owns the commit."""
    repo = RuleDefinitionRepository(session)
    created: list[RuleDefinition] = []
    for spec in _BUILTIN_RULES:
        if repo.get(spec["rule_id"]) is not None:
            continue
        dsl = {
            "detection_type": spec["detection_type"],
            "severity": spec["severity"],
            "combinator": "AND",
            "conditions": [{"primitive": spec["primitive"], "params": {}, "negate": False}],
        }
        rule = repo.create(
            rule_id=spec["rule_id"],
            name=spec["name"],
            dsl=dsl,
            tier=1,
            confidence=_DEFAULT_CONFIDENCE,
            enabled=True,
            created_by=None,
            actor_type=actor_type,
            actor_id=actor_id,
        )
        created.append(rule)
    return created
