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

from sqlalchemy.orm import Session

from db.enums import ActorType, CaseResolution
from db.models.investigation import Case
from db.repositories.detection import AlertRepository
from db.repositories.investigation import CaseAccountRepository, CaseRepository
from db.repositories.reference import AccountRepository, CustomerRepository
from detection.scoring.ensemble import (
    HIGH_BETWEENNESS_THRESHOLD,
    HIGH_PAGERANK_THRESHOLD,
    RoleClassifier,
)
from investigation.case_graph import build_case_graph_store

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
    account_ids = [
        ca.account_id for ca in CaseAccountRepository(session).list_for_case(case_id)
    ]

    graph = build_case_graph_store(session, account_ids)

    roles = RoleClassifier().classify_all(graph)
    mule_linked_accounts = sum(1 for r in roles.values() if r["role"] == "MULE")

    cycles = graph.detect_cycles(max_length=_CYCLE_MAX_LENGTH, max_cycles=_CYCLE_MAX_CYCLES)
    cycles_detected = len(cycles)

    centrality = graph.compute_centrality()
    pagerank = centrality["pagerank"]
    betweenness = centrality["betweenness"]
    high_centrality_accounts = sum(
        1
        for account_id in account_ids
        if pagerank.get(account_id, 0.0) > HIGH_PAGERANK_THRESHOLD
        or betweenness.get(account_id, 0.0) > HIGH_BETWEENNESS_THRESHOLD
    )

    account_repo = AccountRepository(session)
    customer_repo = CustomerRepository(session)
    seen_customer_ids: set[str] = set()
    sanctioned_entities = 0
    pep_entities = 0
    for account_id in account_ids:
        account = account_repo.get(account_id)
        if account is None or account.customer_id is None:
            continue
        if account.customer_id in seen_customer_ids:
            continue
        seen_customer_ids.add(account.customer_id)
        customer = customer_repo.get(account.customer_id)
        if customer is None:
            continue
        if customer.sanction_status:
            sanctioned_entities += 1
        if customer.pep_status:
            pep_entities += 1

    alert_repo = AlertRepository(session)
    case_repo = CaseRepository(session)
    prior_case_ids: set[str] = set()
    for account_id in account_ids:
        for alert in alert_repo.list_for_primary_account(account_id):
            if alert.case_id is not None and alert.case_id != case_id:
                prior_case_ids.add(alert.case_id)
    previous_sars = sum(
        1
        for prior_case_id in prior_case_ids
        if (prior_case := case_repo.get(prior_case_id)) is not None
        and prior_case.resolution == CaseResolution.TRUE_POSITIVE_SAR
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
