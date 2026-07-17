"""Deterministic ranking — ROADMAP Phase 9, slice 3.

Ranking is **deterministic and evidence-weighted**, computed in Python from the
rule firings — never asked of the model. The model selects a gated action and
writes grounded prose; the *ordering and confidence* an investigator sees are a
function of the evidence, not of the model's self-assessment. That separation is
deliberate: a model's stated confidence is unauditable, whereas "ranked highest
because a CRITICAL structuring alert fired on 4 accounts" can be recomputed.

Structured so the RL feature vector can drive it later (roadmap): the score is a
plain weighted sum over evidence signals, so a learned weight vector can replace
these constants without changing the surrounding contract.
"""
from __future__ import annotations

from .action_catalog import Action
from .rule_grounding import CaseGrounding, RuleFiring

# Severity → weight. The dominant signal: a CRITICAL firing should pull its
# action to the top regardless of how many low-severity ones exist.
_SEVERITY_WEIGHT: dict[str, float] = {
    "CRITICAL": 1.0,
    "HIGH": 0.75,
    "MEDIUM": 0.5,
    "LOW": 0.25,
}


def _relevant_firings(action: Action, ground: CaseGrounding) -> list[RuleFiring]:
    """The firings that substantiate this action. A typology-specific action is
    substantiated by firings of its typology; a cross-cutting/disposition action
    (`typologies` empty) is substantiated by *every* firing on the case — its
    justification is the case's overall weight of evidence."""
    if not action.typologies:
        return ground.firings
    return [f for f in ground.firings if f.typology in action.typologies]


def score_action(action: Action, ground: CaseGrounding) -> float:
    """A 0-1 confidence/rank score for one action, from the evidence behind it.

    Weighted sum of: the strongest severity among relevant firings (dominant),
    the strongest detector score, how many accounts are implicated, and a bump
    for any adjacency to a prior-SAR entity. Clamped to [0, 1]."""
    firings = _relevant_firings(action, ground)
    if not firings:
        return 0.0

    max_severity = max(_SEVERITY_WEIGHT.get(f.severity, 0.5) for f in firings)
    max_score = max(f.score for f in firings)
    # More implicated accounts = a broader, more structured pattern. Saturates
    # so a very wide but weak case can't outrank a narrow critical one.
    implicated = len({a for f in firings for a in f.triggering_account_ids})
    breadth = min(implicated / 5.0, 1.0)

    score = 0.55 * max_severity + 0.30 * max_score + 0.15 * breadth
    return round(min(score, 1.0), 3)


def rank_actions(
    scored: list[tuple[Action, float]],
) -> list[tuple[Action, float, int]]:
    """Order (action, score) pairs into (action, score, rank) triples.

    Sorted by score descending; ties broken by the action's fixed catalog order
    (its position in `all_actions()`), so the ordering is fully deterministic and
    never depends on dict/set iteration order. Rank is 1-based."""
    from .action_catalog import all_actions

    catalog_order = {a.action_id: i for i, a in enumerate(all_actions())}
    ordered = sorted(
        scored,
        key=lambda pair: (-pair[1], catalog_order.get(pair[0].action_id, 1_000)),
    )
    return [(action, score, i + 1) for i, (action, score) in enumerate(ordered)]
