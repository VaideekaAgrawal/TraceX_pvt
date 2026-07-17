"""
`/cases/{case_id}/*` -- the L1 triage HTTP surface (ROADMAP Phase 5): the
first real caller of `foundation.auth.require_case_access` and the first
business-logic routes this backend exposes beyond `/auth/*`.

Every route is case-scoped via `require_case_access`; account-level
sub-resources additionally go through `require_case_scoped_account`, which
404s if the requested `account_id` isn't in `case_accounts` -- that table
*is* the case-scoping security boundary (`db/repositories/investigation.py`).

Matches `api.routes.auth`'s transaction-boundary convention: every mutating
route calls `db.commit()` itself; the `investigation`/`orchestration`
functions it calls only flush, never commit.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.enums import CaseResolution, CaseStatus, NoteSource, Priority, UserRole
from db.models.investigation import Case
from db.models.platform import User
from db.models.reference import Account
from db.repositories.detection import AlertRepository
from db.repositories.investigation import (
    CASE_SORT_KEYS,
    CaseAccountRepository,
    CaseRepository,
    NoteRepository,
)
from db.repositories.reference import AccountRepository, CustomerRepository, TransactionRepository
from db.session import get_db
from foundation.auth import (
    actor_type_for_role,
    get_app_settings,
    get_current_user,
    require_case_access,
    require_case_read_access,
    require_case_scoped_account_read,
)
from foundation.config import Settings
from investigation import account_facts, case_graph, previous_alerts
from investigation.cases import close_case
from investigation.fsm import InvalidTransitionError, transition_case
from investigation.network_risk import compute_network_risk
from investigation.similar_cases import find_similar_cases
from orchestration.account_explanation import explain_account

router = APIRouter(prefix="/cases", tags=["cases"])


# ── System-wide (role-scoped) case list ───────────────────────────────────
#
# `GET /cases` -- distinct from every route below, which is scoped to one
# `{case_id}` via `require_case_access`. This is the Investigation Workspace
# landing view's data source (`docs/FRONTEND_ROADMAP.md` Phase 15,
# decision 8): "what am I working on", not the Dashboard's system-wide
# `GET /alerts` (Phase 14). Placed ahead of the `{case_id}`-scoped routes for
# visual grouping with this file's other list-style route -- path collision
# with `/cases/{case_id}/...` isn't a real concern, FastAPI matches `/cases`
# vs. `/cases/{case_id}/...` by segment count.

#: Admin/Compliance's queue is "cases waiting on my review/closure action" --
#: NOT "assigned to me" in the Investigator sense (maker-checker model,
#: `docs/FRONTEND_ROADMAP.md` Phase 15 / §1). A `status` filter they supply
#: must narrow within this set, not escape it.
_ADMIN_QUEUE_STATUSES = {CaseStatus.AWAITING_REVIEW, CaseStatus.ESCALATED}


class CaseListItem(BaseModel):
    case_id: str
    primary_account_id: str
    status: CaseStatus
    priority: Priority
    assigned_to: str | None
    updated_at: datetime


class CaseListResponse(BaseModel):
    items: list[CaseListItem]
    total_count: int
    limit: int
    offset: int


@dataclass
class _CaseListParams:
    """Shared query-param set for `GET /cases` -- mirrors `api.routes.
    alerts._AlertListParams`'s dataclass-`Depends()` convention."""

    status: CaseStatus | None = Query(default=None)
    priority: Priority | None = Query(default=None)
    sort: str | None = Query(default=None)
    limit: int = Query(default=200, le=1000)
    offset: int = Query(default=0, ge=0)


def _case_list_item(case: Case) -> CaseListItem:
    return CaseListItem(
        case_id=case.case_id,
        primary_account_id=case.primary_account_id,
        status=case.status,
        priority=case.priority,
        assigned_to=case.assigned_to,
        updated_at=case.updated_at,
    )


@router.get("", response_model=CaseListResponse)
def list_cases(
    params: _CaseListParams = Depends(),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CaseListResponse:
    """Role-scoped case list -- the primary way an investigator finds work
    (`docs/FRONTEND_ROADMAP.md` Phase 15). `sort` defaults to
    `"updated_at_desc"` when not given; always SQL-ordered (no RL-reranking
    step here, unlike `GET /alerts`).

    - `ADMIN_COMPLIANCE`: scoped to `_ADMIN_QUEUE_STATUSES` (their
      review/closure queue, not an assignment-based queue). A `status`
      filter outside that set is rejected (400) rather than silently
      returning an empty page. `assigned_to` stays unset -- the admin
      queue isn't assignee-scoped.
    - `INVESTIGATOR`: scoped to `assigned_to = user.user_id` (their own
      queue, reusing the same scoping idea `require_case_access` already
      enforces per-case). Any `CaseStatus` `status` filter is legal here --
      it's just an additional narrowing filter, no special validation.
    """
    if params.sort is not None and params.sort not in CASE_SORT_KEYS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"invalid sort: {params.sort!r}")

    statuses: list[CaseStatus] | None
    if user.role == UserRole.ADMIN_COMPLIANCE:
        if params.status is not None and params.status not in _ADMIN_QUEUE_STATUSES:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "status must be AWAITING_REVIEW or ESCALATED for the Admin/Compliance queue",
            )
        statuses = [params.status] if params.status is not None else list(_ADMIN_QUEUE_STATUSES)
        assigned_to = None
    else:
        statuses = [params.status] if params.status is not None else None
        assigned_to = user.user_id

    repo = CaseRepository(db)
    total_count = repo.count_filtered(
        statuses=statuses, priority=params.priority, assigned_to=assigned_to
    )
    page = repo.list_filtered(
        statuses=statuses,
        priority=params.priority,
        assigned_to=assigned_to,
        sort=params.sort or "updated_at_desc",
        limit=params.limit,
        offset=params.offset,
    )
    return CaseListResponse(
        items=[_case_list_item(c) for c in page],
        total_count=total_count,
        limit=params.limit,
        offset=params.offset,
    )


@router.get("/{case_id}", response_model=CaseListItem)
def get_case(case: Case = Depends(require_case_read_access)) -> CaseListItem:
    """Single-case lookup -- the gap `workspace-shell.tsx`'s `?case=`
    deep-link handler and the Similar Historical Cases / Previous
    Investigation History "open this case" flow both need: neither the
    current investigator's own tab cache nor `GET /cases` (role-scoped to
    "my queue"/admin review queue) can resolve an arbitrary `case_id` a
    panel merely references. Returns the same `CaseListItem` shape `GET
    /cases` already returns per row, so the frontend's Zustand tab store's
    `openCase(item: CaseListItem)` can consume this directly.

    `require_case_read_access`, not `require_case_access` -- this is a GET,
    and any authenticated user may open any case's detail once they know its
    `case_id` (see that dependency's docstring)."""
    return _case_list_item(case)


# ── Response models ──────────────────────────────────────────────────────


class AlertSummaryItem(BaseModel):
    alert_id: str
    detection_type: str
    primary_account_id: str
    account_ids: list[str]
    score: float
    risk_score: float
    severity: str
    priority: str
    confidence: str | None
    status: str
    rule_ids: list[str] | None
    created_at: datetime
    last_seen_at: datetime


class SiblingAccount(BaseModel):
    account_id: str
    account_type: str
    bank_name: str | None
    branch_city: str | None
    status: str
    current_risk_score: float | None


class CustomerSnapshotResponse(BaseModel):
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
    declared_annual_income: float | None
    income_bracket: str | None
    sibling_accounts: list[SiblingAccount]


class GeoRiskResponse(BaseModel):
    account_id: str
    branch_city: str | None
    bank_name: str | None
    bank_id: str | None
    counterparty_bank_count: int
    counterparty_banks: list[str]
    counterparty_city_count: int
    counterparty_cities: list[str]


class TransactionSummaryResponse(BaseModel):
    account_id: str
    total_in: float
    total_out: float
    txn_count: int
    counterparty_count: int
    channel_breakdown: dict[str, int]


class TransactionPurposeItem(BaseModel):
    txn_id: str
    timestamp: datetime
    direction: Literal["in", "out"]
    counterparty_account_id: str
    amount: float
    channel: str
    purpose: str | None
    narration: str | None


class TransactionPurposeResponse(BaseModel):
    account_id: str
    transactions: list[TransactionPurposeItem]
    purpose_distribution: dict[str, int]


class RiskTrendPoint(BaseModel):
    alert_id: str
    created_at: datetime
    risk_score: float
    #: Nullable -- some alerts have no case yet (`investigation.previous_
    #: alerts.summarize`'s `risk_trend.append(...)`, `alert.case_id`). Lets
    #: the frontend make a prior-alert row clickable through to its case,
    #: the same mechanism Similar Historical Cases already uses.
    case_id: str | None


class PreviousAlertsResponse(BaseModel):
    account_id: str
    total_prior_alerts: int
    prior_sar_count: int
    prior_false_positive_count: int
    prior_monitoring_count: int
    risk_trend: list[RiskTrendPoint]


class MoneyFlowNode(BaseModel):
    account_id: str
    total_amount: float
    txn_count: int
    #: Share of total inflow (`sources`) / outflow (`beneficiaries`), 0-100.
    #: (code-review finding, Phase 7: `investigation.path_facts` computes
    #: this exact percentage from the same `shape_money_flow` output for its
    #: fund-flow fact group, via `case_graph.add_flow_percentages` -- this
    #: route wasn't surfacing it to the L1 UI even though the underlying
    #: data was identical.)
    pct_of_total: float


class MoneyFlowResponse(BaseModel):
    center: str
    sources: list[MoneyFlowNode]
    beneficiaries: list[MoneyFlowNode]


class NetworkRiskResponse(BaseModel):
    case_id: str
    network_risk_score: float | None
    network_risk_reasons: dict[str, Any] | None


class SimilarCaseItem(BaseModel):
    case_id: str
    similarity: float
    typology: str | None
    outcome: str | None
    computed_at: datetime


class SimilarCasesResponse(BaseModel):
    case_id: str
    similar_cases: list[SimilarCaseItem]


class ExplanationResponse(BaseModel):
    account_id: str
    explanation: str
    cached: bool
    model: str
    generated_at: datetime


class DecisionRequest(BaseModel):
    decision: Literal["close_fp", "request_info", "escalate"]
    reason: str
    note: str | None = None


class DecisionResponse(BaseModel):
    case_id: str
    status: str
    resolution: str | None


# ── Data-assembly endpoints ──────────────────────────────────────────────


@router.get("/{case_id}/summary/alerts", response_model=list[AlertSummaryItem])
def get_alert_summary(
    case: Case = Depends(require_case_read_access), db: Session = Depends(get_db)
) -> list[AlertSummaryItem]:
    alerts = AlertRepository(db).list_for_case(case.case_id)
    return [
        AlertSummaryItem(
            alert_id=a.alert_id,
            detection_type=str(a.detection_type),
            primary_account_id=a.primary_account_id,
            account_ids=a.account_ids,
            score=a.score,
            risk_score=a.risk_score,
            severity=str(a.severity),
            priority=str(a.priority),
            confidence=a.confidence,
            status=a.status,
            rule_ids=a.rule_ids,
            created_at=a.created_at,
            last_seen_at=a.last_seen_at,
        )
        for a in alerts
    ]


@router.get(
    "/{case_id}/accounts/{account_id}/customer-snapshot", response_model=CustomerSnapshotResponse
)
def get_customer_snapshot(
    account: Account = Depends(require_case_scoped_account_read), db: Session = Depends(get_db)
) -> CustomerSnapshotResponse:
    customer = (
        CustomerRepository(db).get(account.customer_id)
        if account.customer_id is not None
        else None
    )
    siblings = (
        AccountRepository(db).get_by_customer(account.customer_id)
        if account.customer_id is not None
        else []
    )
    sibling_items = [
        SiblingAccount(
            account_id=s.account_id,
            account_type=s.account_type,
            bank_name=s.bank_name,
            branch_city=s.branch_city,
            status=str(s.status),
            current_risk_score=s.current_risk_score,
        )
        for s in siblings
        if s.account_id != account.account_id
    ]
    return CustomerSnapshotResponse(
        account_id=account.account_id,
        customer_id=account.customer_id,
        name=customer.name if customer is not None else None,
        entity_type=str(customer.entity_type) if customer is not None else None,
        kyc_status=str(customer.kyc_status) if customer is not None else None,
        edd_status=str(customer.edd_status) if customer is not None else None,
        pep_status=customer.pep_status if customer is not None else None,
        sanction_status=customer.sanction_status if customer is not None else None,
        risk_rating=str(customer.risk_rating) if customer is not None else None,
        occupation=customer.occupation if customer is not None else None,
        declared_annual_income=(
            float(customer.declared_annual_income)
            if customer is not None and customer.declared_annual_income is not None
            else None
        ),
        income_bracket=customer.income_bracket if customer is not None else None,
        sibling_accounts=sibling_items,
    )


@router.get("/{case_id}/accounts/{account_id}/geo-risk", response_model=GeoRiskResponse)
def get_geo_risk(
    account: Account = Depends(require_case_scoped_account_read), db: Session = Depends(get_db)
) -> GeoRiskResponse:
    # `limit=CASE_SCOPE_TRANSACTION_LIMIT`, not the repository's own
    # oldest-first-capped-at-500 default -- see `investigation.case_graph.
    # CASE_SCOPE_TRANSACTION_LIMIT`'s docstring (code-review finding,
    # Phase 5: the default silently dropped a high-volume account's most
    # recent counterparty activity from this view).
    txns = TransactionRepository(db).list_for_account_in_window(
        account.account_id, limit=case_graph.CASE_SCOPE_TRANSACTION_LIMIT
    )
    banks: set[str] = set()
    counterparties: set[str] = set()
    for t in txns:
        if t.source_account == account.account_id:
            counterparties.add(t.dest_account)
            if t.to_bank:
                banks.add(t.to_bank)
        elif t.dest_account == account.account_id:
            counterparties.add(t.source_account)
            if t.from_bank:
                banks.add(t.from_bank)
    # Batched lookup (code-review finding, Phase 5: this used to `.get()`
    # each counterparty account one at a time).
    counterparty_accounts = AccountRepository(db).list_by_ids(list(counterparties))
    cities = {a.branch_city for a in counterparty_accounts if a.branch_city}
    return GeoRiskResponse(
        account_id=account.account_id,
        branch_city=account.branch_city,
        bank_name=account.bank_name,
        bank_id=account.bank_id,
        counterparty_bank_count=len(banks),
        counterparty_banks=sorted(banks),
        counterparty_city_count=len(cities),
        counterparty_cities=sorted(cities),
    )


@router.get(
    "/{case_id}/accounts/{account_id}/transaction-summary",
    response_model=TransactionSummaryResponse,
)
def get_transaction_summary(
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    account: Account = Depends(require_case_scoped_account_read),
    db: Session = Depends(get_db),
) -> TransactionSummaryResponse:
    # `limit=CASE_SCOPE_TRANSACTION_LIMIT` -- see that constant's docstring
    # (code-review finding, Phase 5: the repository's own default silently
    # dropped a high-volume account's most recent transactions).
    txns = TransactionRepository(db).list_for_account_in_window(
        account.account_id, start=start, end=end, limit=case_graph.CASE_SCOPE_TRANSACTION_LIMIT
    )
    stats = account_facts.transaction_stats(txns, account.account_id)
    return TransactionSummaryResponse(account_id=account.account_id, **stats)


@router.get(
    "/{case_id}/accounts/{account_id}/transaction-purpose",
    response_model=TransactionPurposeResponse,
)
def get_transaction_purpose(
    account: Account = Depends(require_case_scoped_account_read), db: Session = Depends(get_db)
) -> TransactionPurposeResponse:
    """Raw per-transaction purpose/narration/amount/channel + a purpose
    distribution -- data assembly only, per the ROADMAP plan: no invented
    "declared vs. actual purpose consistency" heuristic (no formula for one
    exists anywhere in this codebase or its spec)."""
    # `limit=CASE_SCOPE_TRANSACTION_LIMIT` -- see that constant's docstring
    # (code-review finding, Phase 5).
    txns = TransactionRepository(db).list_for_account_in_window(
        account.account_id, limit=case_graph.CASE_SCOPE_TRANSACTION_LIMIT
    )
    items: list[TransactionPurposeItem] = []
    distribution: dict[str, int] = {}
    for t in txns:
        direction: Literal["in", "out"] = "out" if t.source_account == account.account_id else "in"
        counterparty = t.dest_account if direction == "out" else t.source_account
        purpose_key = t.purpose or "unspecified"
        distribution[purpose_key] = distribution.get(purpose_key, 0) + 1
        items.append(
            TransactionPurposeItem(
                txn_id=t.txn_id,
                timestamp=t.timestamp,
                direction=direction,
                counterparty_account_id=counterparty,
                amount=float(t.amount),
                channel=str(t.channel),
                purpose=t.purpose,
                narration=t.narration,
            )
        )
    return TransactionPurposeResponse(
        account_id=account.account_id, transactions=items, purpose_distribution=distribution
    )


@router.get(
    "/{case_id}/accounts/{account_id}/previous-alerts", response_model=PreviousAlertsResponse
)
def get_previous_alerts(
    case: Case = Depends(require_case_read_access),
    account: Account = Depends(require_case_scoped_account_read),
    db: Session = Depends(get_db),
) -> PreviousAlertsResponse:
    summary = previous_alerts.summarize(db, account.account_id, exclude_case_id=case.case_id)
    return PreviousAlertsResponse(account_id=account.account_id, **summary)


@router.get("/{case_id}/accounts/{account_id}/money-flow", response_model=MoneyFlowResponse)
def get_money_flow(
    case: Case = Depends(require_case_read_access),
    account: Account = Depends(require_case_scoped_account_read),
    db: Session = Depends(get_db),
) -> MoneyFlowResponse:
    account_ids = CaseAccountRepository(db).list_account_ids_for_case(case.case_id)
    graph = case_graph.build_case_graph_store(db, account_ids)
    ego = graph.get_ego_graph(account.account_id, radius=1)
    shaped = case_graph.add_flow_percentages(case_graph.shape_money_flow(ego, account.account_id))
    return MoneyFlowResponse(
        center=shaped["center"],
        sources=[
            MoneyFlowNode(
                account_id=s["account_id"],
                total_amount=s["total_amount"],
                txn_count=s["txn_count"],
                pct_of_total=s["pct_of_inflow"],
            )
            for s in shaped["sources"]
        ],
        beneficiaries=[
            MoneyFlowNode(
                account_id=b["account_id"],
                total_amount=b["total_amount"],
                txn_count=b["txn_count"],
                pct_of_total=b["pct_of_outflow"],
            )
            for b in shaped["beneficiaries"]
        ],
    )


# ── Network Risk Score ────────────────────────────────────────────────────


def _compute_and_respond(db: Session, case: Case, user: User) -> NetworkRiskResponse:
    """Shared by `get_network_risk`'s lazy-compute path and
    `recompute_network_risk` (code-review finding, Phase 5: the two
    handlers were near-identical -- compute, commit, build the same
    response -- differing only in *when* they call this)."""
    case = compute_network_risk(
        db, case.case_id, actor_type=actor_type_for_role(user.role), actor_id=user.user_id
    )
    db.commit()
    return NetworkRiskResponse(
        case_id=case.case_id,
        network_risk_score=case.network_risk_score,
        network_risk_reasons=case.network_risk_reasons,
    )


@router.get("/{case_id}/network-risk", response_model=NetworkRiskResponse)
def get_network_risk(
    case: Case = Depends(require_case_read_access),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NetworkRiskResponse:
    """Returns the stored score/reasons; lazy-computes and commits once if
    `Case.network_risk_score` is still `None` (first view of this case),
    matching `network_risk_score`/`_reasons`'s "stored, not recomputed each
    view" design (`db/models/investigation.py::Case` docstring)."""
    if case.network_risk_score is None:
        return _compute_and_respond(db, case, user)
    return NetworkRiskResponse(
        case_id=case.case_id,
        network_risk_score=case.network_risk_score,
        network_risk_reasons=case.network_risk_reasons,
    )


@router.post("/{case_id}/network-risk/recompute", response_model=NetworkRiskResponse)
def recompute_network_risk(
    case: Case = Depends(require_case_access),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NetworkRiskResponse:
    return _compute_and_respond(db, case, user)


# ── Similar Historical Cases ──────────────────────────────────────────────


@router.get("/{case_id}/similar-cases", response_model=SimilarCasesResponse)
def get_similar_cases(
    top_k: int = Query(default=5),
    case: Case = Depends(require_case_read_access),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SimilarCasesResponse:
    """Cosine similarity over the RL 16-dim feature vector
    (`investigation.similar_cases`). GET-only, no `/recompute` sibling --
    unlike Network Risk Score's stored-then-lazily-computed score, every
    call here is already a live query (the query case's own vector is
    computed on-the-fly, never persisted -- see that module's docstring),
    so there is nothing to lazily cache."""
    results = find_similar_cases(
        db,
        case.case_id,
        top_k=top_k,
        actor_type=actor_type_for_role(user.role),
        actor_id=user.user_id,
    )
    return SimilarCasesResponse(
        case_id=case.case_id,
        similar_cases=[
            SimilarCaseItem(
                case_id=r.case_id,
                similarity=r.similarity,
                typology=r.typology,
                outcome=str(r.outcome) if r.outcome is not None else None,
                computed_at=r.computed_at,
            )
            for r in results
        ],
    )


# ── AI account explanation ────────────────────────────────────────────────


@router.get(
    "/{case_id}/accounts/{account_id}/explanation", response_model=ExplanationResponse
)
def get_account_explanation(
    force: bool = Query(default=False),
    case: Case = Depends(require_case_read_access),
    account: Account = Depends(require_case_scoped_account_read),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_app_settings),
    db: Session = Depends(get_db),
) -> ExplanationResponse:
    result = explain_account(
        db,
        case.case_id,
        account.account_id,
        settings=settings,
        actor_type=actor_type_for_role(user.role),
        actor_id=user.user_id,
        force=force,
    )
    db.commit()
    return ExplanationResponse(**result)


# ── Start investigation (ASSIGNED -> IN_PROGRESS) ─────────────────────────


@router.post("/{case_id}/start", response_model=CaseListItem)
def start_investigation(
    case: Case = Depends(require_case_access),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CaseListItem:
    """The missing `ASSIGNED -> IN_PROGRESS` step. Before this route existed,
    no route anywhere exposed it, so a freshly-assigned case could never
    legally reach `ESCALATED`/`AWAITING_REVIEW`/`CLOSED_FP` at all through
    the API -- `investigation.fsm.VALID_TRANSITIONS` itself was always
    correct (`ASSIGNED -> ESCALATED` directly is correctly rejected), the
    gap was purely a missing route (flagged but not fixed in `docs/
    SESSION_LOG.md` Sessions 22 and 24, both of which had to call
    `investigation.fsm.transition_case` directly as a manual verify-setup
    workaround).

    Deliberately a separate, dedicated route rather than folded into
    `/decision`'s `DecisionRequest` -- `/decision` conflates "decisions"
    (terminal-ish actions requiring a typed `reason`) with this being a
    mundane "I've started working on this" state event that needs no
    reason, matching this codebase's own precedent of `PATCH /alerts/
    {alert_id}/assign` being its own dedicated action route rather than
    jammed into `/decision`.

    Stays on `require_case_access` (assignment-gated), NOT `require_case_
    read_access` -- this is a real state mutation and must remain
    restricted to the assigned Investigator or Admin/Compliance, same as
    every other write route.

    `InvalidTransitionError` -> 409 (matches `make_decision`'s existing
    pattern) -- e.g. calling this on a case that's already past `ASSIGNED`
    409s cleanly rather than raising unhandled. No `reason`/`note` -- this
    isn't a decision, just a status event; the `case_status_history` row
    `transition_case` writes is the audit trail."""
    try:
        updated = transition_case(
            db,
            case.case_id,
            CaseStatus.IN_PROGRESS,
            actor_type=actor_type_for_role(user.role),
            actor_id=user.user_id,
        )
    except InvalidTransitionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    db.commit()
    return _case_list_item(updated)


# ── L1 decision endpoint ──────────────────────────────────────────────────


@router.post("/{case_id}/decision", response_model=DecisionResponse)
def make_decision(
    body: DecisionRequest,
    case: Case = Depends(require_case_access),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DecisionResponse:
    """Close-as-FP | Request-info | Escalate, mapped onto the real
    `investigation.fsm.VALID_TRANSITIONS` graph:

      - `escalate` -> `ESCALATED` (legal only from `IN_PROGRESS`), open to
        any investigator with case access.
      - `request_info` -> `AWAITING_REVIEW` (legal only from `IN_PROGRESS`),
        same access as escalate -- deliberately routes into the same status
        Admin/Compliance monitors to close from.
      - `close_fp` -> `close_case(..., FALSE_POSITIVE)`. FSM-legal from
        `IN_PROGRESS`/`AWAITING_REVIEW`/`ESCALATED`, but RBAC is a separate
        layer on top: only `ADMIN_COMPLIANCE` may execute it
        (`SYSTEM_DEVELOPMENT_PLAN.md` §5 -- "only Admin/Compliance closes
        cases"), even though the FSM itself would permit an Investigator's
        direct `IN_PROGRESS -> CLOSED_FP`. Checked here, per-decision-value,
        rather than a blanket `Depends(require_role(...))` on the whole
        route, since `escalate`/`request_info` must stay open to
        Investigators on this same endpoint.

    `InvalidTransitionError` -> 409. If `note` is present, it's recorded as
    a `Note` after a successful transition. `escalate`/`request_info`
    intentionally do NOT write `DetectionFeedback`/RL feedback -- only
    `close_case`'s closing resolutions have a reward mapping
    (`investigation.rl_features.CLOSING_REWARD`); their audit trail is the
    `case_status_history` + `audit_log` rows `transition_case` already
    produces, plus the optional note.
    """
    actor_type = actor_type_for_role(user.role)

    try:
        if body.decision == "escalate":
            updated = transition_case(
                db,
                case.case_id,
                CaseStatus.ESCALATED,
                actor_type=actor_type,
                actor_id=user.user_id,
                reason=body.reason,
            )
        elif body.decision == "request_info":
            updated = transition_case(
                db,
                case.case_id,
                CaseStatus.AWAITING_REVIEW,
                actor_type=actor_type,
                actor_id=user.user_id,
                reason=body.reason,
            )
        else:  # "close_fp"
            if user.role != UserRole.ADMIN_COMPLIANCE:
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN, "Only Admin/Compliance may close a case"
                )
            updated = close_case(
                db,
                case.case_id,
                CaseResolution.FALSE_POSITIVE,
                actor_type=actor_type,
                actor_id=user.user_id,
                reason=body.reason,
            )
    except InvalidTransitionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    if body.note:
        NoteRepository(db).create(
            note_id=f"NOTE-{uuid4().hex[:12].upper()}",
            case_id=case.case_id,
            source=NoteSource.INVESTIGATOR,
            body=f"[{body.decision}] {body.note}",
            author_id=user.user_id,
            actor_type=actor_type,
            actor_id=user.user_id,
        )

    db.commit()
    return DecisionResponse(
        case_id=updated.case_id,
        status=str(updated.status),
        resolution=str(updated.resolution) if updated.resolution is not None else None,
    )
