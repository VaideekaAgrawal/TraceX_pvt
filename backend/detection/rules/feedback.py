"""Rule-confidence learning from investigator verdicts — ROADMAP Phase 12.

This closes the half of the feedback loop the RL bandit doesn't: when a case is
resolved, the rules that fired for it earn or lose standing based on whether the
verdict confirmed them. A rule whose alerts keep closing as TRUE_POSITIVE drifts
toward high confidence; one whose alerts keep closing as FALSE_POSITIVE drifts
down — a running, auditable precision estimate per rule, learned from real
outcomes rather than the static `seed.py` default.

The update is a bounded EWMA on `RuleDefinition.confidence` toward the verdict's
target (1.0 for a confirmed true positive, 0.0 for a false positive), with a
small learning rate so a single verdict nudges rather than swings, and clamped to
`[_FLOOR, _CEIL]`:

- never exactly 0.0 — a noisy rule trends toward the floor (visibly low, and
  surfaced in the governance metrics) but stays enabled; *disabling* a rule is a
  human decision (`RuleDefinition.enabled`, via the admin review queue), not
  something one bad week of feedback does automatically.
- never exactly 1.0 — feedback estimates precision, it doesn't certify it.

`ENHANCED_MONITORING` counts as a positive outcome (the alert flagged something
worth watching), mirroring `investigation.rl_features.CLOSING_REWARD` — the same
`is_true_positive = reward > 0` split `close_case` feeds the bandit, so the two
halves of the loop never disagree about what a verdict meant.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from db.enums import ActorType
from db.repositories.detection import RuleDefinitionRepository

logger = logging.getLogger(__name__)

#: EWMA step. Small on purpose: ~7 consistent verdicts to move confidence
#: halfway to the target, so a single mistaken close can't tank a good rule.
_LEARNING_RATE = 0.1
#: Confidence is clamped to this band — see module docstring for why neither
#: endpoint is reachable (a rule is never auto-killed nor auto-certified).
_FLOOR = 0.05
_CEIL = 0.99


@dataclass(frozen=True)
class ConfidenceChange:
    """One rule's confidence move, for logging and the governance surface."""

    rule_id: str
    old: float
    new: float


def _step(old: float, target: float) -> float:
    moved = old + _LEARNING_RATE * (target - old)
    return max(_FLOOR, min(_CEIL, moved))


def adjust_rule_confidence(
    session: Session,
    rule_ids: list[str] | None,
    *,
    is_true_positive: bool,
    actor_type: ActorType,
    actor_id: str | None,
) -> list[ConfidenceChange]:
    """Nudge each fired rule's `confidence` toward the verdict outcome and
    persist it (audited `rule_definition_updated`). Does NOT commit — the caller
    (`investigation.cases.close_case`) owns the transaction. Unknown/removed
    rule_ids are skipped (a stale id on an old alert must not abort a close).
    Returns the changes applied, most-moved first."""
    if not rule_ids:
        return []
    target = 1.0 if is_true_positive else 0.0
    repo = RuleDefinitionRepository(session)
    changes: list[ConfidenceChange] = []
    for rule_id in rule_ids:
        rule = repo.get(rule_id)
        if rule is None:
            # An alert can outlive the rule that fired it; a verdict on such a
            # case still closes, it just teaches nothing about a rule that's gone.
            logger.debug("skipping confidence update for unknown rule %s", rule_id)
            continue
        old = rule.confidence  # capture before update() mutates the row in place
        new = _step(old, target)
        if new == old:
            continue
        repo.update(rule_id, confidence=new, actor_type=actor_type, actor_id=actor_id)
        changes.append(ConfidenceChange(rule_id=rule_id, old=old, new=new))
    changes.sort(key=lambda c: abs(c.new - c.old), reverse=True)
    if changes:
        logger.info(
            "verdict (%s) adjusted %d rule confidence(s): %s",
            "TP" if is_true_positive else "FP", len(changes),
            ", ".join(f"{c.rule_id} {c.old:.3f}->{c.new:.3f}" for c in changes[:5]),
        )
    return changes
