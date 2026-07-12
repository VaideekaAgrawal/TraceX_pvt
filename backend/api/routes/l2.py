"""
`/cases/{case_id}/*` -- the L2 deep-investigation HTTP surface (ROADMAP
Phase 6): N-hop graph exploration, complete customer profile, searchable
transaction analysis, historical behaviour analysis, timeline
reconstruction, pattern explanation, and evidence management.

A separate router from `api.routes.cases` (already 564 lines / 14 routes
before this phase) rather than growing that file further -- both mount
under the same `/cases` prefix and are registered together in `api.app`.

Every account-scoped route goes through `foundation.auth.
require_case_scoped_account` (moved there from `api.routes.cases` this
phase -- this module is its second real caller); every case-scoped route
goes through `foundation.auth.require_case_access`. Matches `api.routes.
cases`'s transaction-boundary convention: every mutating route calls
`db.commit()` itself; the `investigation`/`orchestration` functions it
calls only flush, never commit.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.enums import Channel, EvidenceType, NoteSource
from db.models.investigation import Case
from db.models.platform import User
from db.models.reference import Account
from db.repositories.investigation import (
    CaseAccountRepository,
    CaseRepository,
    EvidenceRepository,
    NoteRepository,
)
from db.session import get_db
from foundation.auth import (
    actor_type_for_role,
    get_app_settings,
    get_current_user,
    require_case_access,
    require_case_scoped_account,
    require_case_scoped_account_with_ids,
)
from foundation.config import Settings
from investigation import behavior_analysis, customer_profile, timeline, transaction_search
from investigation.graph_filters import MAX_RADIUS, GraphFilters, get_filtered_ego_graph
from investigation.relationship_graph import build_case_relationship_graph
from orchestration import pattern_explanation

router = APIRouter(prefix="/cases", tags=["l2"])


# ── Response models ──────────────────────────────────────────────────────


class GraphNode(BaseModel):
    account_id: str
    branch_city: str | None
    role: str
    role_confidence: float
    current_risk_score: float | None
    has_prior_sar: bool
    hop_distance: int | None


class GraphEdge(BaseModel):
    txn_id: str
    source_account: str
    dest_account: str
    amount: float
    timestamp: datetime
    channel: str
    is_laundering: bool
    from_bank: str | None
    to_bank: str | None


class NHopGraphResponse(BaseModel):
    center: str
    radius: int
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class RelationshipNode(BaseModel):
    customer_id: str
    name: str | None
    in_case_scope: bool


class RelationshipEdge(BaseModel):
    id: int
    entity_a: str
    entity_b: str
    shared_attribute: str
    confidence: float
    method: str
    discovered_at: datetime


class RelationshipGraphResponse(BaseModel):
    case_id: str
    nodes: list[RelationshipNode]
    edges: list[RelationshipEdge]


class SiblingAccountItem(BaseModel):
    account_id: str
    account_type: str
    bank_name: str | None
    branch_city: str | None
    status: str
    current_risk_score: float | None


class CustomerProfileResponse(BaseModel):
    account_id: str
    customer_id: str | None
    name: str | None
    entity_type: str | None
    kyc_status: str | None
    edd_status: str | None
    pep_status: bool | None
    sanction_status: bool | None
    risk_rating: str | None
    occupation: str | None
    employer: str | None
    declared_annual_income: float | None
    income_bracket: str | None
    account_type: str | None
    bank_name: str | None
    branch_city: str | None
    account_status: str | None
    kyc_tier: str | None
    opening_date: datetime | None
    current_risk_score: float | None
    expected_monthly_volume: float | None
    actual_monthly_volume_avg: float | None
    expected_vs_actual_variance_ratio: float | None
    prior_sar_count: int
    total_prior_alerts: int
    sibling_accounts: list[SiblingAccountItem]
    omitted_fields: list[str]


class TransactionSearchItem(BaseModel):
    txn_id: str
    timestamp: datetime
    amount: float
    channel: str
    txn_type: str
    source_account: str
    dest_account: str
    source_branch_city: str | None
    dest_branch_city: str | None
    source_account_type: str | None
    dest_account_type: str | None
    direction: Literal["in", "out"] | None
    is_laundering: bool


class TransactionSearchResponse(BaseModel):
    items: list[TransactionSearchItem]
    total_count: int
    limit: int
    offset: int


class MonthlyTotalItem(BaseModel):
    month: str
    total_in: float
    total_out: float
    total: float
    txn_count: int


class CashDepositMonthItem(BaseModel):
    month: str
    cash_deposit_total: float
    txn_count: int


class TransferMonthItem(BaseModel):
    month: str
    transfer_total: float
    txn_count: int


class DormancyReactivationEvent(BaseModel):
    gap_start: datetime
    gap_end: datetime
    gap_days: int
    burst_txn_count: int


class DormancyReactivationResult(BaseModel):
    reactivation_detected: bool
    events: list[DormancyReactivationEvent]


class VelocityIncreaseResult(BaseModel):
    recent_avg_weekly_txn_count: float
    baseline_avg_weekly_txn_count: float
    ratio: float | None
    velocity_increase_detected: bool


class BehaviorAnalysisResponse(BaseModel):
    account_id: str
    monthly_totals: list[MonthlyTotalItem]
    cash_deposit_trend: list[CashDepositMonthItem]
    transfer_trend: list[TransferMonthItem]
    dormancy_reactivation: DormancyReactivationResult
    velocity_increase: VelocityIncreaseResult
    deferred: list[str]


class TimelineEventItem(BaseModel):
    txn_id: str
    timestamp: datetime
    direction: Literal["in", "out"]
    counterparty_account_id: str
    amount: float
    channel: str
    is_laundering: bool


class TimelineResponse(BaseModel):
    account_id: str
    events: list[TimelineEventItem]


class PatternExplanationResponse(BaseModel):
    alert_id: str
    explanation: str
    cached: bool
    model: str
    generated_at: datetime
    rule_anchors: dict[str, Any] | None
    pattern_signature: str


class EvidenceCreateRequest(BaseModel):
    type: EvidenceType
    ref_id: str | None = None
    label: str | None = None
    payload: dict[str, Any] | None = None
    file_path: str | None = None


class EvidenceItem(BaseModel):
    evidence_id: str
    case_id: str
    type: str
    ref_id: str | None
    label: str | None
    payload: dict[str, Any] | None
    file_path: str | None
    pinned: bool
    added_by: str
    added_at: datetime


class NoteCreateRequest(BaseModel):
    body: str


class NoteItem(BaseModel):
    note_id: str
    case_id: str
    author_id: str | None
    source: str
    body: str
    created_at: datetime


# ── N-hop graph exploration ───────────────────────────────────────────────


@router.get("/{case_id}/accounts/{account_id}/graph", response_model=NHopGraphResponse)
def get_account_graph(
    radius: int = Query(default=2),
    suspicious_only: bool = Query(default=False),
    min_risk_score: float | None = Query(default=None),
    min_amount: float | None = Query(default=None),
    max_amount: float | None = Query(default=None),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    channels: list[str] | None = Query(default=None),
    direction: Literal["in", "out"] | None = Query(default=None),
    roles: list[str] | None = Query(default=None),
    prior_sar_only: bool = Query(default=False),
    case: Case = Depends(require_case_access),
    account_and_ids: tuple[Account, list[str]] = Depends(require_case_scoped_account_with_ids),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NHopGraphResponse:
    """N-hop ego-graph around `account_id`, with the full L2 filter set
    applied (`investigation.graph_filters`). `radius` is clamped to
    `MAX_RADIUS` here (the real safety valve -- `get_filtered_ego_graph`
    clamps again defensively). Also closes the ROADMAP Phase 4
    `graph_expanded` audit-hook deferral: this is the case-scoped
    graph-view endpoint that deferral was waiting on.

    Uses `require_case_scoped_account_with_ids` (not the plain
    `require_case_scoped_account`) so the case's scoped account-id set --
    already computed by that dependency to validate `account_id` -- is
    reused for `get_filtered_ego_graph` instead of being re-queried
    (code-review finding, Phase 6)."""
    account, case_account_ids = account_and_ids
    clamped_radius = min(radius, MAX_RADIUS)
    filters = GraphFilters(
        suspicious_only=suspicious_only,
        min_risk_score=min_risk_score,
        min_amount=min_amount,
        max_amount=max_amount,
        start=start,
        end=end,
        channels=channels,
        direction=direction,
        roles=roles,
        prior_sar_only=prior_sar_only,
    )
    result = get_filtered_ego_graph(
        db,
        case.case_id,
        account.account_id,
        radius=clamped_radius,
        filters=filters,
        case_account_ids=case_account_ids,
    )
    CaseRepository(db).mark_graph_expanded(
        case.case_id, actor_type=actor_type_for_role(user.role), actor_id=user.user_id
    )
    db.commit()
    return NHopGraphResponse(**result)


# ── Relationship Explorer v1 ──────────────────────────────────────────────


@router.get("/{case_id}/relationships", response_model=RelationshipGraphResponse)
def get_case_relationships(
    case: Case = Depends(require_case_access), db: Session = Depends(get_db)
) -> RelationshipGraphResponse:
    """The Relationship Explorer full version this phase's ROADMAP entry
    ties to this file (Phase 6 explicitly stubbed this route out --
    "Relationship Explorer full version (Phase 7 stub only)"). Pure read
    over already-discovered `relationships` rows (`investigation.
    relationship_graph.build_case_relationship_graph`) -- this route never
    runs discovery itself; that's a separate global batch job
    (`investigation.relationship_discovery`, invoked via `scripts.
    discover_relationships`/`demo_data.seed`, not HTTP-triggered this
    phase). GET-only, read-only: no audit hook beyond `require_case_access`
    since nothing is mutated."""
    account_ids = CaseAccountRepository(db).list_account_ids_for_case(case.case_id)
    result = build_case_relationship_graph(db, case.case_id, account_ids)
    return RelationshipGraphResponse(**result)


# ── Complete Customer Profile ─────────────────────────────────────────────


@router.get("/{case_id}/accounts/{account_id}/profile", response_model=CustomerProfileResponse)
def get_customer_profile(
    case: Case = Depends(require_case_access),
    account: Account = Depends(require_case_scoped_account),
    db: Session = Depends(get_db),
) -> CustomerProfileResponse:
    profile = customer_profile.build_customer_profile(db, case.case_id, account.account_id)
    return CustomerProfileResponse(**profile)


# ── Complete Transaction Analysis ─────────────────────────────────────────


@dataclass
class _TransactionSearchParams:
    """Shared query-param set for both transaction-search routes below --
    factored out so the ~10 filter params aren't duplicated verbatim across
    two route signatures. FastAPI resolves a dataclass the same way it
    resolves a function's parameters when used via `Depends()`."""

    min_amount: float | None = Query(default=None)
    max_amount: float | None = Query(default=None)
    start: datetime | None = Query(default=None)
    end: datetime | None = Query(default=None)
    channels: list[str] | None = Query(default=None)
    direction: Literal["in", "out"] | None = Query(default=None)
    txn_type: str | None = Query(default=None)
    limit: int = Query(default=200, le=1000)
    offset: int = Query(default=0, ge=0)
    sort: str = Query(default="timestamp_desc")


def _parse_channels(channels: list[str] | None) -> list[Channel] | None:
    if not channels:
        return None
    try:
        return [Channel(c) for c in channels]
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"invalid channel: {exc}") from exc


@router.get("/{case_id}/transactions/search", response_model=TransactionSearchResponse)
def search_case_transactions(
    params: _TransactionSearchParams = Depends(),
    case: Case = Depends(require_case_access),
    db: Session = Depends(get_db),
) -> TransactionSearchResponse:
    result = transaction_search.search(
        db,
        case.case_id,
        min_amount=params.min_amount,
        max_amount=params.max_amount,
        start=params.start,
        end=params.end,
        channels=_parse_channels(params.channels),
        direction=params.direction,
        txn_type=params.txn_type,
        limit=params.limit,
        offset=params.offset,
        sort=params.sort,
    )
    return TransactionSearchResponse(**result)


@router.get(
    "/{case_id}/accounts/{account_id}/transactions/search",
    response_model=TransactionSearchResponse,
)
def search_account_transactions(
    params: _TransactionSearchParams = Depends(),
    case: Case = Depends(require_case_access),
    account_and_ids: tuple[Account, list[str]] = Depends(require_case_scoped_account_with_ids),
    db: Session = Depends(get_db),
) -> TransactionSearchResponse:
    # Reuses the scoped account-id set `require_case_scoped_account_with_ids`
    # already computed to validate `account_id`, instead of re-querying it
    # inside `transaction_search.search` (code-review finding, Phase 6).
    account, case_account_ids = account_and_ids
    result = transaction_search.search(
        db,
        case.case_id,
        account_id=account.account_id,
        case_account_ids=case_account_ids,
        min_amount=params.min_amount,
        max_amount=params.max_amount,
        start=params.start,
        end=params.end,
        channels=_parse_channels(params.channels),
        direction=params.direction,
        txn_type=params.txn_type,
        limit=params.limit,
        offset=params.offset,
        sort=params.sort,
    )
    return TransactionSearchResponse(**result)


# ── Historical Behaviour Analysis ─────────────────────────────────────────


@router.get("/{case_id}/accounts/{account_id}/behavior", response_model=BehaviorAnalysisResponse)
def get_account_behavior(
    case: Case = Depends(require_case_access),
    account: Account = Depends(require_case_scoped_account),
    db: Session = Depends(get_db),
) -> BehaviorAnalysisResponse:
    result = behavior_analysis.analyze(db, case.case_id, account.account_id)
    return BehaviorAnalysisResponse(**result)


# ── Timeline reconstruction ────────────────────────────────────────────────


@router.get("/{case_id}/accounts/{account_id}/timeline", response_model=TimelineResponse)
def get_account_timeline(
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    case: Case = Depends(require_case_access),
    account: Account = Depends(require_case_scoped_account),
    db: Session = Depends(get_db),
) -> TimelineResponse:
    result = timeline.build_timeline(db, case.case_id, account.account_id, start=start, end=end)
    return TimelineResponse(**result)


# ── Pattern explanation ────────────────────────────────────────────────────


@router.get(
    "/{case_id}/alerts/{alert_id}/pattern-explanation", response_model=PatternExplanationResponse
)
def get_pattern_explanation(
    alert_id: str,
    force: bool = Query(default=False),
    case: Case = Depends(require_case_access),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_app_settings),
    db: Session = Depends(get_db),
) -> PatternExplanationResponse:
    """`alert_id` is not an account-scoped path param (no `require_case_
    scoped_account` dependency applies) -- `orchestration.pattern_
    explanation.explain_pattern` itself validates `alert.case_id == case_id`
    and that the alert shares an account with the case's scope, raising
    `ValueError` (mapped to 404 here) otherwise."""
    try:
        result = pattern_explanation.explain_pattern(
            db,
            case.case_id,
            alert_id,
            settings=settings,
            actor_type=actor_type_for_role(user.role),
            actor_id=user.user_id,
            force=force,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    db.commit()
    return PatternExplanationResponse(**result)


# ── Evidence management ────────────────────────────────────────────────────


def _evidence_item(evidence: Any) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence.evidence_id,
        case_id=evidence.case_id,
        type=str(evidence.type),
        ref_id=evidence.ref_id,
        label=evidence.label,
        payload=evidence.payload,
        file_path=evidence.file_path,
        pinned=evidence.pinned,
        added_by=evidence.added_by,
        added_at=evidence.added_at,
    )


def _note_item(note: Any) -> NoteItem:
    return NoteItem(
        note_id=note.note_id,
        case_id=note.case_id,
        author_id=note.author_id,
        source=str(note.source),
        body=note.body,
        created_at=note.created_at,
    )


@router.post(
    "/{case_id}/evidence", response_model=EvidenceItem, status_code=status.HTTP_201_CREATED
)
def create_evidence(
    body: EvidenceCreateRequest,
    case: Case = Depends(require_case_access),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EvidenceItem:
    """Every evidence "type" the spec names maps onto this one call with no
    new persistence: bookmark txn/account -> `type=TRANSACTION`/`ACCOUNT`
    with `ref_id`; save a graph snapshot/highlighted path -> `type=
    GRAPH_SNAPSHOT` with an arbitrary `payload` (e.g. the exact
    filter+radius+highlighted-edges a saved view represents); attach a
    document -> `type=DOCUMENT` with `file_path` as metadata only (no
    upload/storage plumbing -- no existing infra anywhere in this codebase
    to build on, flagged rather than silently stubbed)."""
    evidence = EvidenceRepository(db).create(
        evidence_id=f"EVD-{uuid4().hex[:12].upper()}",
        case_id=case.case_id,
        type=body.type,
        ref_id=body.ref_id,
        label=body.label,
        payload=body.payload,
        file_path=body.file_path,
        added_by=user.user_id,
        actor_type=actor_type_for_role(user.role),
        actor_id=user.user_id,
    )
    db.commit()
    return _evidence_item(evidence)


@router.patch("/{case_id}/evidence/{evidence_id}/pin", response_model=EvidenceItem)
def pin_evidence(
    evidence_id: str,
    case: Case = Depends(require_case_access),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EvidenceItem:
    repo = EvidenceRepository(db)
    evidence = repo.get(evidence_id)
    if evidence is None or evidence.case_id != case.case_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Evidence not found in this case")
    updated = repo.pin(
        evidence_id, actor_type=actor_type_for_role(user.role), actor_id=user.user_id
    )
    db.commit()
    return _evidence_item(updated)


@router.get("/{case_id}/evidence", response_model=list[EvidenceItem])
def list_evidence(
    pinned: bool | None = Query(default=None),
    case: Case = Depends(require_case_access),
    db: Session = Depends(get_db),
) -> list[EvidenceItem]:
    repo = EvidenceRepository(db)
    if pinned is True:
        items = repo.list_pinned_for_case(case.case_id)
    else:
        items = repo.list_for_case(case.case_id)
        if pinned is False:
            items = [e for e in items if not e.pinned]
    return [_evidence_item(e) for e in items]


@router.post("/{case_id}/notes", response_model=NoteItem, status_code=status.HTTP_201_CREATED)
def create_note(
    body: NoteCreateRequest,
    case: Case = Depends(require_case_access),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NoteItem:
    """"Collaborate with other investigators" (spec) -- the existing
    `added_by`/`author_id` + timestamp audit trail already on `Evidence`/
    `Note` (`db/models/investigation.py`) IS the collaboration mechanism
    here; no new real-time feature is built for this phase."""
    note = NoteRepository(db).create(
        note_id=f"NOTE-{uuid4().hex[:12].upper()}",
        case_id=case.case_id,
        source=NoteSource.INVESTIGATOR,
        body=body.body,
        author_id=user.user_id,
        actor_type=actor_type_for_role(user.role),
        actor_id=user.user_id,
    )
    db.commit()
    return _note_item(note)


@router.get("/{case_id}/notes", response_model=list[NoteItem])
def list_notes(
    case: Case = Depends(require_case_access), db: Session = Depends(get_db)
) -> list[NoteItem]:
    notes = NoteRepository(db).list_for_case(case.case_id)
    return [_note_item(n) for n in notes]
