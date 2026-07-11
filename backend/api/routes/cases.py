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

from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.enums import CaseResolution, CaseStatus, NoteSource, UserRole
from db.models.investigation import Case
from db.models.platform import User
from db.models.reference import Account
from db.repositories.detection import AlertRepository
from db.repositories.investigation import CaseAccountRepository, NoteRepository
from db.repositories.reference import AccountRepository, CustomerRepository, TransactionRepository
from db.session import get_db
from foundation.auth import (
    actor_type_for_role,
    get_app_settings,
    get_current_user,
    require_case_access,
)
from foundation.config import Settings
from investigation import account_facts, case_graph, previous_alerts
from investigation.cases import close_case
from investigation.fsm import InvalidTransitionError, transition_case
from investigation.network_risk import compute_network_risk
from orchestration.account_explanation import explain_account

router = APIRouter(prefix="/cases", tags=["cases"])


def require_case_scoped_account(
    account_id: str,
    case: Case = Depends(require_case_access),
    db: Session = Depends(get_db),
) -> Account:
    """404s if `account_id` isn't in `case`'s `case_accounts` scope (don't
    leak "this account exists elsewhere in the system" to an investigator
    who isn't scoped to it), else loads and returns the `Account` row."""
    scoped_ids = {ca.account_id for ca in CaseAccountRepository(db).list_for_case(case.case_id)}
    if account_id not in scoped_ids:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Account not in this case's scope")
    account = AccountRepository(db).get(account_id)
    if account is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Account not found")
    return account


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


class MoneyFlowResponse(BaseModel):
    center: str
    sources: list[MoneyFlowNode]
    beneficiaries: list[MoneyFlowNode]


class NetworkRiskResponse(BaseModel):
    case_id: str
    network_risk_score: float | None
    network_risk_reasons: dict[str, Any] | None


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
    case: Case = Depends(require_case_access), db: Session = Depends(get_db)
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
    account: Account = Depends(require_case_scoped_account), db: Session = Depends(get_db)
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
    account: Account = Depends(require_case_scoped_account), db: Session = Depends(get_db)
) -> GeoRiskResponse:
    txns = TransactionRepository(db).list_for_account_in_window(account.account_id)
    account_repo = AccountRepository(db)
    banks: set[str] = set()
    cities: set[str] = set()
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
    for counterparty_id in counterparties:
        counterparty = account_repo.get(counterparty_id)
        if counterparty is not None and counterparty.branch_city:
            cities.add(counterparty.branch_city)
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
    account: Account = Depends(require_case_scoped_account),
    db: Session = Depends(get_db),
) -> TransactionSummaryResponse:
    txns = TransactionRepository(db).list_for_account_in_window(
        account.account_id, start=start, end=end
    )
    stats = account_facts.transaction_stats(txns, account.account_id)
    return TransactionSummaryResponse(account_id=account.account_id, **stats)


@router.get(
    "/{case_id}/accounts/{account_id}/transaction-purpose",
    response_model=TransactionPurposeResponse,
)
def get_transaction_purpose(
    account: Account = Depends(require_case_scoped_account), db: Session = Depends(get_db)
) -> TransactionPurposeResponse:
    """Raw per-transaction purpose/narration/amount/channel + a purpose
    distribution -- data assembly only, per the ROADMAP plan: no invented
    "declared vs. actual purpose consistency" heuristic (no formula for one
    exists anywhere in this codebase or its spec)."""
    txns = TransactionRepository(db).list_for_account_in_window(account.account_id)
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
    case: Case = Depends(require_case_access),
    account: Account = Depends(require_case_scoped_account),
    db: Session = Depends(get_db),
) -> PreviousAlertsResponse:
    summary = previous_alerts.summarize(db, account.account_id, exclude_case_id=case.case_id)
    return PreviousAlertsResponse(account_id=account.account_id, **summary)


@router.get("/{case_id}/accounts/{account_id}/money-flow", response_model=MoneyFlowResponse)
def get_money_flow(
    case: Case = Depends(require_case_access),
    account: Account = Depends(require_case_scoped_account),
    db: Session = Depends(get_db),
) -> MoneyFlowResponse:
    account_ids = [ca.account_id for ca in CaseAccountRepository(db).list_for_case(case.case_id)]
    graph = case_graph.build_case_graph_store(db, account_ids)
    ego = graph.get_ego_graph(account.account_id, radius=1)
    shaped = case_graph.shape_money_flow(ego, account.account_id)
    return MoneyFlowResponse(**shaped)


# ── Network Risk Score ────────────────────────────────────────────────────


@router.get("/{case_id}/network-risk", response_model=NetworkRiskResponse)
def get_network_risk(
    case: Case = Depends(require_case_access),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NetworkRiskResponse:
    """Returns the stored score/reasons; lazy-computes and commits once if
    `Case.network_risk_score` is still `None` (first view of this case),
    matching `network_risk_score`/`_reasons`'s "stored, not recomputed each
    view" design (`db/models/investigation.py::Case` docstring)."""
    if case.network_risk_score is None:
        case = compute_network_risk(
            db, case.case_id, actor_type=actor_type_for_role(user.role), actor_id=user.user_id
        )
        db.commit()
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
    case = compute_network_risk(
        db, case.case_id, actor_type=actor_type_for_role(user.role), actor_id=user.user_id
    )
    db.commit()
    return NetworkRiskResponse(
        case_id=case.case_id,
        network_risk_score=case.network_risk_score,
        network_risk_reasons=case.network_risk_reasons,
    )


# ── AI account explanation ────────────────────────────────────────────────


@router.get(
    "/{case_id}/accounts/{account_id}/explanation", response_model=ExplanationResponse
)
def get_account_explanation(
    force: bool = Query(default=False),
    case: Case = Depends(require_case_access),
    account: Account = Depends(require_case_scoped_account),
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
