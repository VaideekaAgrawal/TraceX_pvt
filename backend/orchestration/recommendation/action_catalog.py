"""The deterministic action catalog — ROADMAP Phase 9, slice 1.

**This catalog IS the action space.** A recommendation whose `action_id` is not
in here is rejected before it reaches an investigator (`engine.py`), exactly the
way the grounding validator rejects an uncited number. The LLM chooses *among*
these actions and writes grounded prose defending its choice; it cannot mint a
new one. "The model can only recommend things a human catalogued and a regulator
can look up" is a property we get by making the alternative unrepresentable —
the same move Phase 8 made for `case_id` and for ungrounded numbers.

Each action carries a **regulatory anchor**: the FATF Recommendation and the
Indian (RBI / PMLA) obligation it serves. That mapping is what lets a
recommendation be defended in the room this product is pitched into — not "the AI
suggested filing an STR" but "structuring was detected, which FATF R.20 and PMLA
s.12 require be reported to FIU-IND, so the recommended action is FILE_STR."

⚠️ **PROTOTYPE / ILLUSTRATIVE CITATIONS.** The FATF/RBI/PMLA references below are
hand-curated for a pitch demo and are deliberately at the level a compliance
officer would recognise, not a legal filing. They have NOT been reviewed by
counsel and must be verified against the current FATF Recommendations and RBI
Master Directions before any external or production use. They are structured as
data (not prose) precisely so that review is a diff on this one file.

## Eligibility

An action is *eligible* for a case when the typology it responds to actually
fired on that case (`rule_grounding.eligible_action_ids`). Typology-specific
actions (trace a layering chain) require their typology; cross-cutting actions
(expand the network, apply EDD) and disposition actions (file an STR, escalate,
close) are eligible on any case that produced at least one alert — there is
always a defensible "what next" once something has fired. The catalog declares
the rule; the engine enforces it.
"""
from __future__ import annotations

from dataclasses import dataclass

from db.enums import DetectionType


@dataclass(frozen=True)
class RegulatoryAnchor:
    """Why an action is defensible to a regulator. Prototype-level references
    (see module warning) — structured so they can be audited as data."""

    fatf: str
    """The FATF Recommendation served, e.g. "R.20 — Reporting of suspicious
    transactions". Empty for purely-internal workflow actions."""

    india: str
    """The Indian obligation (RBI Master Direction / PMLA section). Empty for
    purely-internal workflow actions."""


@dataclass(frozen=True)
class Action:
    """One recommendable next step. `action_id` is the stable identity the
    validator checks and the audit log records — never renumber it."""

    action_id: str
    title: str
    description: str
    #: The typologies this action responds to. Empty means it is not
    #: typology-gated: eligible on any case that produced an alert (disposition
    #: and cross-cutting actions).
    typologies: frozenset[DetectionType]
    regulatory_anchor: RegulatoryAnchor
    #: A hint to the model about which tools substantiate this action. Not
    #: enforced (the grounding validator enforces citations), but it steers the
    #: reasoning toward the evidence that makes the action defensible.
    supporting_tools: tuple[str, ...] = ()


# A shorthand so the catalog below reads as a table rather than a wall of kwargs.
_ANY: frozenset[DetectionType] = frozenset()


# ── The catalog ────────────────────────────────────────────────────────────
# Ordered: typology-specific investigative actions, then cross-cutting
# investigative actions, then disposition actions. Order here is also the
# stable presentation order used when two actions tie on rank.

_ACTIONS: tuple[Action, ...] = (
    # ── typology-specific investigation ──────────────────────────────────
    Action(
        action_id="TRACE_LAYERING_CHAIN",
        title="Trace the layering chain to its destination",
        description=(
            "Follow the multi-hop transfer chain hop by hop to identify the "
            "ultimate beneficiary and where the funds settle. Layering exists to "
            "break the audit trail between source and destination; reconstructing "
            "it is what defeats it."
        ),
        typologies=frozenset({DetectionType.layering}),
        regulatory_anchor=RegulatoryAnchor(
            fatf="R.16 — Wire transfers (originator/beneficiary information)",
            india="RBI KYC Master Direction 2016 — wire-transfer & remittance monitoring",
        ),
        supporting_tools=("get_ego_graph_summary", "get_money_flow", "get_timeline"),
    ),
    Action(
        action_id="INVESTIGATE_ROUND_TRIP",
        title="Investigate circular fund flow (round-tripping)",
        description=(
            "Examine the circular path where funds return to their origin, often "
            "via intermediaries, to establish whether it evidences round-tripping "
            "or trade-based laundering rather than legitimate settlement."
        ),
        typologies=frozenset({DetectionType.round_trip}),
        regulatory_anchor=RegulatoryAnchor(
            fatf="R.10 — Customer due diligence; R.16 — Wire transfers",
            india="PMLA 2002 — proceeds-of-crime tracing; RBI KYC MD 2016",
        ),
        supporting_tools=("get_ego_graph_summary", "get_money_flow"),
    ),
    Action(
        action_id="REVIEW_STRUCTURING_DEPOSITS",
        title="Review sub-threshold deposits for structuring",
        description=(
            "Review the pattern of deposits sitting just below reporting "
            "thresholds to establish whether they are deliberately structured "
            "(smurfing) to evade Cash Transaction Report obligations."
        ),
        typologies=frozenset({DetectionType.structuring}),
        regulatory_anchor=RegulatoryAnchor(
            fatf="R.10 — Customer due diligence; R.20 — Reporting",
            india="PMLA Rules — CTR (cash transactions > Rs.10 lakh) to FIU-IND",
        ),
        supporting_tools=("search_transactions", "get_behavior_analysis"),
    ),
    Action(
        action_id="REVIEW_DORMANCY_REACTIVATION",
        title="Review sudden reactivation of a dormant account",
        description=(
            "Examine why a long-dormant account reactivated with a burst of "
            "activity — a classic mule-account signature — and whether the "
            "reactivation is consistent with the customer's known profile."
        ),
        typologies=frozenset({DetectionType.dormancy}),
        regulatory_anchor=RegulatoryAnchor(
            fatf="R.10 — Ongoing customer due diligence",
            india="RBI KYC MD 2016 — inoperative/dormant account handling",
        ),
        supporting_tools=("get_behavior_analysis", "get_timeline"),
    ),
    Action(
        action_id="VERIFY_KYC_PROFILE_MISMATCH",
        title="Verify KYC against the transaction profile",
        description=(
            "Transaction volume is inconsistent with the customer's declared "
            "income/occupation profile. Verify KYC and obtain source-of-funds "
            "documentation to resolve the mismatch."
        ),
        typologies=frozenset({DetectionType.profile_mismatch}),
        regulatory_anchor=RegulatoryAnchor(
            fatf="R.10 — Customer due diligence (incl. source of funds)",
            india="RBI KYC MD 2016 — periodic KYC update & enhanced due diligence",
        ),
        supporting_tools=("get_account_facts", "get_behavior_analysis"),
    ),
    # ── cross-cutting investigation (eligible on any alerted case) ────────
    Action(
        action_id="EXPAND_NETWORK_INVESTIGATION",
        title="Expand the network investigation",
        description=(
            "Expand the transaction neighbourhood beyond the immediate accounts "
            "to map the wider network and surface intermediaries or a controlling "
            "hub not visible at one hop."
        ),
        typologies=_ANY,
        regulatory_anchor=RegulatoryAnchor(
            fatf="R.10 — Understanding the nature of the business relationship",
            india="RBI KYC MD 2016 — beneficial ownership & connected accounts",
        ),
        supporting_tools=("get_ego_graph_summary", "get_network_risk"),
    ),
    Action(
        action_id="REVIEW_RELATIONSHIP_LINKS",
        title="Review non-transactional relationship links",
        description=(
            "Investigate shared-attribute links (PAN, phone, device, address) "
            "between the parties, which can reveal coordination that transaction "
            "flow alone does not."
        ),
        typologies=_ANY,
        regulatory_anchor=RegulatoryAnchor(
            fatf="R.10 — Identifying connected/associated parties",
            india="RBI KYC MD 2016 — related-party & common-attribute review",
        ),
        supporting_tools=("get_relationships", "get_path_recommendation_facts"),
    ),
    Action(
        action_id="REVIEW_PRIOR_SAR_LINKS",
        title="Review adjacency to prior-SAR entities",
        description=(
            "One or more accounts are adjacent to entities that were the subject "
            "of a prior Suspicious Activity Report. Review those links, since "
            "recurrence materially raises suspicion."
        ),
        typologies=_ANY,
        regulatory_anchor=RegulatoryAnchor(
            fatf="R.10 — Ongoing due diligence on higher-risk relationships",
            india="PMLA 2002 — record retention; RBI KYC MD 2016 — EDD triggers",
        ),
        supporting_tools=("get_previous_alerts", "get_path_recommendation_facts"),
    ),
    Action(
        action_id="APPLY_ENHANCED_DUE_DILIGENCE",
        title="Apply enhanced due diligence",
        description=(
            "Apply enhanced due diligence to the higher-risk parties: obtain "
            "source-of-funds/wealth documentation and senior-management sign-off "
            "before the relationship continues."
        ),
        typologies=_ANY,
        regulatory_anchor=RegulatoryAnchor(
            fatf="R.10 — Enhanced due diligence for higher-risk customers",
            india="RBI KYC MD 2016 — EDD for high-risk customers",
        ),
        supporting_tools=("get_account_facts", "get_network_risk"),
    ),
    # ── disposition ──────────────────────────────────────────────────────
    Action(
        action_id="FILE_STR",
        title="File a Suspicious Transaction Report",
        description=(
            "The evidence supports a reasonable ground of suspicion. Prepare and "
            "file a Suspicious Transaction Report to FIU-IND within the "
            "prescribed timeline."
        ),
        typologies=_ANY,
        regulatory_anchor=RegulatoryAnchor(
            fatf="R.20 — Reporting of suspicious transactions",
            india="PMLA 2002 s.12 & PMLA Rules — STR to FIU-IND (RBI KYC MD ch. on reporting)",
        ),
        supporting_tools=("get_case_summary", "get_network_risk"),
    ),
    Action(
        action_id="PLACE_UNDER_MONITORING",
        title="Place under enhanced ongoing monitoring",
        description=(
            "Suspicion is not yet sufficient to report but the profile warrants "
            "closer watch. Place the account(s) under enhanced ongoing monitoring "
            "with a defined review date."
        ),
        typologies=_ANY,
        regulatory_anchor=RegulatoryAnchor(
            fatf="R.10 — Ongoing monitoring of the business relationship",
            india="RBI KYC MD 2016 — ongoing monitoring of transactions",
        ),
        supporting_tools=("get_case_summary", "get_behavior_analysis"),
    ),
    Action(
        action_id="ESCALATE_TO_L2",
        title="Escalate for deep (L2) investigation",
        description=(
            "The case exceeds first-line triage. Escalate to a Level-2 analyst "
            "for full network and evidentiary review."
        ),
        typologies=_ANY,
        regulatory_anchor=RegulatoryAnchor(
            fatf="R.1 — Risk-based approach (allocation of investigative resource)",
            india="Internal AML escalation workflow",
        ),
        supporting_tools=("get_case_summary", "get_network_risk"),
    ),
    Action(
        action_id="CLOSE_AS_FALSE_POSITIVE",
        title="Close as a false positive",
        description=(
            "The gathered evidence does not support the initial suspicion and is "
            "consistent with the customer's legitimate profile. Recommend closing "
            "the case as a false positive, with the reasoning recorded."
        ),
        typologies=_ANY,
        regulatory_anchor=RegulatoryAnchor(
            fatf="R.1 — Risk-based approach (documented disposition)",
            india="Internal AML disposition workflow (auditable close)",
        ),
        supporting_tools=("get_case_summary", "get_account_facts"),
    ),
)


#: action_id -> Action, the canonical lookup. Built once; the catalog is fixed.
CATALOG: dict[str, Action] = {a.action_id: a for a in _ACTIONS}


def all_actions() -> tuple[Action, ...]:
    """The full catalog in stable presentation order."""
    return _ACTIONS


def get_action(action_id: str) -> Action | None:
    """Look up an action, or None if `action_id` is not in the catalog. The
    engine treats None as an automatic rejection — a model that names an action
    outside the catalog has left the closed action space."""
    return CATALOG.get(action_id)


def actions_for_typologies(fired: set[DetectionType]) -> list[Action]:
    """Every action eligible given the set of typologies that fired on a case.

    A typology-specific action is eligible only if its typology is in `fired`.
    A non-typology-gated action (`typologies == _ANY`) is always eligible once
    *something* has fired — there is always a defensible disposition or
    network-expansion step. If nothing fired, `fired` is empty and only the
    cross-cutting/disposition actions come back; the engine additionally
    declines to recommend at all on a case with no alerts (nothing to ground)."""
    out: list[Action] = []
    for action in _ACTIONS:
        if not action.typologies or action.typologies & fired:
            out.append(action)
    return out
