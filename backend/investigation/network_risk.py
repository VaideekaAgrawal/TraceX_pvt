"""
Network Risk Score (ROADMAP Phase 5; `SYSTEM_DEVELOPMENT_PLAN.md` §4.1:
"status: partial -> needs packaging"). A single 0-100 score, distinct from
any individual account's `current_risk_score`, reflecting network-level
danger across a case's linked accounts (`case_accounts`).

Reuse before rebuild (CLAUDE.md): every signal below is an existing
centrality/cycle/role/SAR-adjacent computation, not a new model --
`RoleClassifier.classify_all` (mule role), `NetworkXGraphStore.
detect_cycles`/`.compute_centrality` (all ported unchanged, Phase 3), and
the same `AlertRepository.list_for_primary_account` pattern
`investigation.previous_alerts` already uses for prior-SAR lookups. This
module's only real logic is the aggregation-and-explanation formula itself.

Deliberately omits "density"/"money concentration" (mentioned in
`SYSTEM_DEVELOPMENT_PLAN.md` §4.1's prose alongside the other signals, but
with no formula anywhere in the repo to port) -- documented deferred
refinement, not an oversight.
"""
from __future__ import annotations

from typing import Any

import numpy as np
from sqlalchemy.orm import Session

from db.enums import ActorType, CaseResolution
from db.models.investigation import Case
from db.repositories.detection import AlertRepository
from db.repositories.investigation import CaseAccountRepository, CaseRepository
from db.repositories.reference import AccountRepository, CustomerRepository
from detection.scoring.ensemble import RoleClassifier
from investigation.case_graph import build_case_graph_store

#: `EnsembleScorer.compute_confidence`'s `HIGH_PAGERANK_THRESHOLD`/
#: `HIGH_BETWEENNESS_THRESHOLD` (0.005/0.01) are calibrated for centrality
#: computed over the FULL transaction graph -- `NetworkXGraphStore.
#: compute_centrality`'s pandas approximation normalizes pagerank/
#: betweenness within whatever graph they're computed over, so a node's
#: score on a 300k-node graph and the same node's score on a case-scoped
#: graph of a handful of accounts aren't comparable in absolute terms
#: (code-review finding, Phase 5, verified against the test fixture's
#: 3-node cycle: pagerank there is ~60-70x that absolute threshold and
#: betweenness ~100x it, so nearly every account in any multi-account case
#: tripped "high centrality" regardless of genuine anomaly). This module
#: therefore does NOT import those constants -- it flags an account as
#: "high centrality" only if it's in the top quartile of THIS case's own
#: centrality distribution, i.e. relative to its own case graph, not an
#: absolute score tuned for a much larger one. Same p75-relative-threshold
#: idiom `detection.scoring.ensemble.RoleClassifier.classify_all` already
#: uses for role classification (`np.percentile(..., 75)`), reused here for
#: the same reason: it degrades gracefully at case scale instead of
#: requiring a graph-size-dependent absolute number. A single-node (or
#: single-value) case graph never flags anything -- the 75th percentile of
#: one value is that value itself, and the comparison below is strict `>`,
#: so a lone account has no network to be "central" within.
_HIGH_CENTRALITY_PERCENTILE = 75

#: Weighted, capped sub-scores clamped to an overall 0-100 total -- mirrors
#: `EnsembleScorer.compute_all`'s own pattern of per-signal weighted
#: contributions capped before summing. Judgment call (documented, per the
#: approved plan): these exact per-unit weights and per-bucket caps are
#: invented for this phase (no formula existed to port) -- reasonable, not
#: derived from any historical calibration.
_MULE_POINTS_PER_ACCOUNT = 6
_MULE_SCORE_CAP = 40
_SAR_POINTS_PER_CASE = 12
_SAR_SCORE_CAP = 30
_SANCTION_POINTS_PER_ENTITY = 10
_PEP_POINTS_PER_ENTITY = 4
_SANCTION_SCORE_CAP = 20
_CYCLE_POINTS_PER_CYCLE = 8
_HIGH_CENTRALITY_POINTS_PER_ACCOUNT = 3
_GRAPH_SCORE_CAP = 20

#: Bounded cycle detection budget for a case-scoped graph -- generous
#: relative to `NetworkXGraphStore.detect_cycles`'s own defaults (12/2000)
#: since a case's linked-account set is small (dozens, not the whole DB);
#: `max_length=8`/`max_cycles=50` keeps this fast without needing anywhere
#: near the full budget.
_CYCLE_MAX_LENGTH = 8
_CYCLE_MAX_CYCLES = 50


def compute_network_risk(
    session: Session, case_id: str, *, actor_type: ActorType, actor_id: str | None
) -> Case:
    """Recompute and persist `Case.network_risk_score`/`network_risk_reasons`
    for `case_id`. Does NOT commit -- caller owns the transaction boundary
    (matches `investigation.cases`/`investigation.fsm`'s convention).
    Raises `ValueError` (via `CaseRepository.update`) if the case doesn't
    exist."""
    account_ids = CaseAccountRepository(session).list_account_ids_for_case(case_id)

    graph = build_case_graph_store(session, account_ids)

    roles = RoleClassifier().classify_all(graph)
    mule_linked_accounts = sum(1 for r in roles.values() if r["role"] == "MULE")

    cycles = graph.detect_cycles(max_length=_CYCLE_MAX_LENGTH, max_cycles=_CYCLE_MAX_CYCLES)
    cycles_detected = len(cycles)

    centrality = graph.compute_centrality()
    pagerank = centrality["pagerank"]
    betweenness = centrality["betweenness"]
    # Case-graph-relative thresholds -- see the module-level comment above
    # `_HIGH_CENTRALITY_PERCENTILE` for why an absolute threshold doesn't
    # transfer from the full-database graph to this case-scoped one.
    pagerank_values = list(pagerank.values())
    betweenness_values = list(betweenness.values())
    pagerank_threshold = (
        float(np.percentile(pagerank_values, _HIGH_CENTRALITY_PERCENTILE))
        if pagerank_values
        else 0.0
    )
    betweenness_threshold = (
        float(np.percentile(betweenness_values, _HIGH_CENTRALITY_PERCENTILE))
        if betweenness_values
        else 0.0
    )
    high_centrality_accounts = sum(
        1
        for account_id in account_ids
        if pagerank.get(account_id, 0.0) > pagerank_threshold
        or betweenness.get(account_id, 0.0) > betweenness_threshold
    )

    # Batched account/customer lookups (code-review finding, Phase 5: this
    # used to `.get()` one account then one customer per case-linked
    # account, an N+1 round-trip pattern for what's already a small,
    # case-scoped id list).
    accounts = AccountRepository(session).list_by_ids(account_ids)
    customer_ids = sorted({a.customer_id for a in accounts if a.customer_id is not None})
    customers = CustomerRepository(session).list_by_ids(customer_ids)
    sanctioned_entities = sum(1 for c in customers if c.sanction_status)
    pep_entities = sum(1 for c in customers if c.pep_status)

    alert_repo = AlertRepository(session)
    case_repo = CaseRepository(session)
    prior_case_ids: set[str] = set()
    for account_id in account_ids:
        for alert in alert_repo.list_for_primary_account(account_id):
            if alert.case_id is not None and alert.case_id != case_id:
                prior_case_ids.add(alert.case_id)
    # Batched case lookup (code-review finding, Phase 5: this used to
    # `.get()` one case per unique prior-case id in a Python loop).
    prior_cases = case_repo.list_by_ids(list(prior_case_ids))
    previous_sars = sum(
        1
        for prior_case in prior_cases
        if prior_case.resolution == CaseResolution.TRUE_POSITIVE_SAR
    )

    mule_score = min(mule_linked_accounts * _MULE_POINTS_PER_ACCOUNT, _MULE_SCORE_CAP)
    sar_score = min(previous_sars * _SAR_POINTS_PER_CASE, _SAR_SCORE_CAP)
    sanction_score = min(
        sanctioned_entities * _SANCTION_POINTS_PER_ENTITY
        + pep_entities * _PEP_POINTS_PER_ENTITY,
        _SANCTION_SCORE_CAP,
    )
    graph_score = min(
        cycles_detected * _CYCLE_POINTS_PER_CYCLE
        + high_centrality_accounts * _HIGH_CENTRALITY_POINTS_PER_ACCOUNT,
        _GRAPH_SCORE_CAP,
    )
    network_risk_score = min(100.0, mule_score + sar_score + sanction_score + graph_score)

    # Illustrative order from the ROADMAP plan's own example ("8 linked mule
    # accounts, 3 previous SARs, 2 sanctioned entities") -- mule -> SAR ->
    # sanction. `pep_entities` is tracked in `network_risk_reasons` but
    # deliberately not surfaced in `summary` text, matching that example
    # (which lists `pep_entities: 0` without a "0 PEP entities" clause).
    summary_components: list[tuple[int, str]] = [
        (mule_linked_accounts, f"{mule_linked_accounts} linked mule accounts"),
        (previous_sars, f"{previous_sars} previous SARs"),
        (sanctioned_entities, f"{sanctioned_entities} sanctioned entities"),
    ]
    summary_parts = [text for count, text in summary_components if count > 0]
    summary = (
        ", ".join(summary_parts)
        if summary_parts
        else "No elevated network risk signals detected"
    )

    network_risk_reasons: dict[str, Any] = {
        "mule_linked_accounts": mule_linked_accounts,
        "previous_sars": previous_sars,
        "sanctioned_entities": sanctioned_entities,
        "pep_entities": pep_entities,
        "cycles_detected": cycles_detected,
        "high_centrality_accounts": high_centrality_accounts,
        "summary": summary,
    }

    return CaseRepository(session).update(
        case_id,
        network_risk_score=network_risk_score,
        network_risk_reasons=network_risk_reasons,
        actor_type=actor_type,
        actor_id=actor_id,
        action="network_risk_computed",
    )
