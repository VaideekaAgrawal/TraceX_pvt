"""Rule grounding — ROADMAP Phase 9, slice 2.

A rule firing must reach the investigator as a **structured evidence record**,
not a verdict string. This module reads a case's *already-persisted* alerts
(never re-detects — same discipline as `pattern_explanation`) and turns each into
a `RuleFiring`: which rule fired, the threshold it tested, the typology, the
accounts that triggered it, and the detector's score/severity.

Two things are built from these firings:

1. **`ai_interactions.rule_anchors`** — the JSON that makes a recommendation
   reconstructable by a regulator *without trusting the model at all*. The model
   might describe a layering chain; the rule anchor records that `builtin_layering`
   (primitive `chain`, min 3 hops within 120 minutes) fired on these specific
   accounts with this score. One is the narrative, the other is the receipt.

2. **The eligible action set** — the typologies that actually fired gate which
   catalog actions the engine will even offer the model
   (`action_catalog.actions_for_typologies`). The rules define the action space;
   this is where "the rules define it" becomes literal.

**Threshold provenance.** The observed *amounts* a recommendation cites come from
the tool layer (`get_account_facts` etc.), grounded by Phase 8's validator. What
this module adds is the *threshold those amounts were tested against* — read from
the `RuleDefinition` DSL, falling back to `PrimitiveRegistry`'s documented
defaults for any param the rule left implicit. Keeping the two apart is
deliberate: the threshold is a property of the rule (deterministic, auditable
here) and the observed value is a property of the data (grounded there).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from db.enums import DetectionType
from db.repositories.detection import AlertRepository, RuleDefinitionRepository
from detection.rules.engine import PrimitiveRegistry

from . import action_catalog


@dataclass(frozen=True)
class RuleFiring:
    """One alert, reduced to the deterministic evidence behind it."""

    alert_id: str
    typology: DetectionType
    triggering_account_ids: list[str]
    score: float
    severity: str
    #: The rule that produced it, if any. ML-only alerts (no `rule_ids`) leave
    #: these null — the typology is still known, the threshold simply isn't a
    #: rule threshold.
    rule_id: str | None = None
    rule_name: str | None = None
    primitive: str | None = None
    #: The threshold parameters this firing was tested against (rule DSL params
    #: merged over the primitive's documented defaults). Empty for ML-only alerts.
    threshold: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe form for `ai_interactions.rule_anchors`."""
        return {
            "alert_id": self.alert_id,
            "typology": str(self.typology),
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "primitive": self.primitive,
            "threshold": self.threshold,
            "triggering_account_ids": list(self.triggering_account_ids),
            "score": self.score,
            "severity": self.severity,
        }


@dataclass
class CaseGrounding:
    """The full deterministic evidence picture for one case."""

    case_id: str
    firings: list[RuleFiring]

    @property
    def fired_typologies(self) -> set[DetectionType]:
        return {f.typology for f in self.firings}

    @property
    def eligible_action_ids(self) -> list[str]:
        """The action_ids the engine may offer the model, gated by what fired.
        Empty when nothing fired — the engine declines to recommend at all in
        that case, since there is no evidence to ground a recommendation on."""
        if not self.firings:
            return []
        return [a.action_id for a in action_catalog.actions_for_typologies(self.fired_typologies)]

    def to_rule_anchors(self) -> dict[str, Any]:
        """The `ai_interactions.rule_anchors` payload: every firing, plus the
        derived typology/eligibility summary. This is the auditable receipt."""
        return {
            "case_id": self.case_id,
            "firings": [f.to_dict() for f in self.firings],
            "fired_typologies": sorted(str(t) for t in self.fired_typologies),
            "eligible_action_ids": self.eligible_action_ids,
        }


def _threshold_from_rule(rule: Any) -> tuple[str | None, dict[str, Any]]:
    """(primitive, threshold-params) for an already-loaded `RuleDefinition`.

    Reads the first condition's primitive — Tier-1 built-ins have exactly one —
    and layers the rule's explicit params over that primitive's documented
    defaults, so a rule that relied on a default still records the real number it
    tested against rather than an empty dict. Pure over the passed rule (no DB
    fetch) so the caller loads the rule exactly once."""
    conditions = (rule.dsl or {}).get("conditions", [])
    if not conditions:
        return None, {}
    first = conditions[0]
    primitive = first.get("primitive")
    if not primitive:
        return None, {}
    defaults = PrimitiveRegistry.DEFAULTS.get(primitive, {})
    merged = {**defaults, **(first.get("params") or {})}
    return primitive, merged


def ground_case(session: Session, case_id: str) -> CaseGrounding:
    """Build the deterministic evidence picture for a case from its persisted
    alerts. Pure read — no detection, no writes."""
    alerts = AlertRepository(session).list_for_case(case_id)
    firings: list[RuleFiring] = []
    for alert in alerts:
        rule_ids = alert.rule_ids or []
        # An alert can name several rules (composite/multiple detectors); the
        # first rule id is the one whose threshold we record, which matches how
        # `list_for_case` already treats the highest-risk alert as primary.
        primary_rule_id = str(rule_ids[0]) if rule_ids else None
        primitive: str | None = None
        threshold: dict[str, Any] = {}
        rule_name: str | None = None
        if primary_rule_id is not None:
            # Load the rule exactly once — both its name and its threshold come
            # from this single fetch.
            rule = RuleDefinitionRepository(session).get(primary_rule_id)
            if rule is not None:
                rule_name = rule.name
                primitive, threshold = _threshold_from_rule(rule)
        firings.append(
            RuleFiring(
                alert_id=alert.alert_id,
                typology=alert.detection_type,
                triggering_account_ids=[str(a) for a in (alert.account_ids or [])],
                score=alert.score,
                severity=str(alert.severity),
                rule_id=primary_rule_id,
                rule_name=rule_name,
                primitive=primitive,
                threshold=threshold,
            )
        )
    return CaseGrounding(case_id=case_id, firings=firings)
