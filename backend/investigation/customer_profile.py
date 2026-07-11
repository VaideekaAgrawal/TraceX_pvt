"""
Complete Customer Profile (ROADMAP Phase 6; `SYSTEM_DEVELOPMENT_PLAN.md`
§4.2). Reuses every field the L1 Customer Snapshot already assembles
(`api.routes.cases.get_customer_snapshot`) plus the additional L2-only
pieces the spec names: expected-vs-actual behavior, prior-SAR count.

**Explicitly omitted, documented here (not silently missing) -- confirmed
via full grep of `db/models/reference.py`/`db/models/investigation.py`,
same scope-down precedent as Phase 1B's device/nominee cut:**

  - beneficial owner: no column anywhere on `Customer`/`Account` for this.
  - linked cards/loans/deposits: no `cards`/`loans`/`deposits` table exists
    in this schema (`docs/DATA_SCHEMA.md` has no such table).
  - risk-score TREND: only a single denormalized `Account.
    current_risk_score` exists (`db/models/reference.py::Account`
    docstring: "denormalized cache of the latest detection output"); there
    is no historical risk-score log to trend over. `investigation.
    previous_alerts.summarize`'s own `risk_trend` (alert-level, not
    account-risk-level) is the closest existing signal and is reused below
    for prior-alert/SAR history instead of fabricating a risk-score-over-
    time series that doesn't exist.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from db.repositories.reference import AccountRepository, CustomerRepository, TransactionRepository
from investigation import previous_alerts
from investigation.behavior_analysis import monthly_totals
from investigation.case_graph import CASE_SCOPE_TRANSACTION_LIMIT

#: See module docstring for why each of these has no backing schema to
#: source from -- surfaced in the response itself (`"omitted_fields"`) so
#: the gap is visible in the API, not just in this comment.
_OMITTED_FIELDS = [
    "beneficial_owner", "linked_cards", "linked_loans", "linked_deposits", "risk_score_trend",
]


def build_customer_profile(session: Session, case_id: str, account_id: str) -> dict[str, Any]:
    """Assemble the complete L2 customer profile for `account_id` within
    `case_id`. Reuses verbatim (per ROADMAP plan): `AccountRepository.get`,
    `CustomerRepository.get`, `AccountRepository.get_by_customer` (sibling
    accounts), `investigation.previous_alerts.summarize(..., exclude_case_id
    =case_id)` (prior-SAR count/history), and `TransactionRepository.
    list_for_account_in_window` + `investigation.behavior_analysis.
    monthly_totals` for actual-vs-`Account.expected_monthly_volume`
    variance."""
    account = AccountRepository(session).get(account_id)
    customer = (
        CustomerRepository(session).get(account.customer_id)
        if account is not None and account.customer_id is not None
        else None
    )
    siblings = (
        AccountRepository(session).get_by_customer(account.customer_id)
        if account is not None and account.customer_id is not None
        else []
    )
    sibling_items = [
        {
            "account_id": s.account_id,
            "account_type": s.account_type,
            "bank_name": s.bank_name,
            "branch_city": s.branch_city,
            "status": str(s.status),
            "current_risk_score": s.current_risk_score,
        }
        for s in siblings
        if account is None or s.account_id != account.account_id
    ]

    alert_summary = previous_alerts.summarize(session, account_id, exclude_case_id=case_id)

    txns = TransactionRepository(session).list_for_account_in_window(
        account_id, limit=CASE_SCOPE_TRANSACTION_LIMIT
    )
    monthly = monthly_totals(txns, account_id)
    actual_monthly_volume_avg = (
        sum(m["total"] for m in monthly) / len(monthly) if monthly else None
    )
    expected = (
        float(account.expected_monthly_volume)
        if account is not None and account.expected_monthly_volume is not None
        else None
    )
    variance_ratio = (
        actual_monthly_volume_avg / expected
        if actual_monthly_volume_avg is not None and expected is not None and expected > 0
        else None
    )

    return {
        "account_id": account_id,
        "customer_id": account.customer_id if account is not None else None,
        "name": customer.name if customer is not None else None,
        "entity_type": str(customer.entity_type) if customer is not None else None,
        "kyc_status": str(customer.kyc_status) if customer is not None else None,
        "edd_status": str(customer.edd_status) if customer is not None else None,
        "pep_status": customer.pep_status if customer is not None else None,
        "sanction_status": customer.sanction_status if customer is not None else None,
        "risk_rating": str(customer.risk_rating) if customer is not None else None,
        "occupation": customer.occupation if customer is not None else None,
        "employer": customer.employer if customer is not None else None,
        "declared_annual_income": (
            float(customer.declared_annual_income)
            if customer is not None and customer.declared_annual_income is not None
            else None
        ),
        "income_bracket": customer.income_bracket if customer is not None else None,
        "account_type": account.account_type if account is not None else None,
        "bank_name": account.bank_name if account is not None else None,
        "branch_city": account.branch_city if account is not None else None,
        "account_status": str(account.status) if account is not None else None,
        "kyc_tier": account.kyc_tier if account is not None else None,
        "opening_date": account.opening_date if account is not None else None,
        "current_risk_score": (
            float(account.current_risk_score)
            if account is not None and account.current_risk_score is not None
            else None
        ),
        "expected_monthly_volume": expected,
        "actual_monthly_volume_avg": actual_monthly_volume_avg,
        "expected_vs_actual_variance_ratio": variance_ratio,
        "prior_sar_count": alert_summary["prior_sar_count"],
        "total_prior_alerts": alert_summary["total_prior_alerts"],
        "sibling_accounts": sibling_items,
        "omitted_fields": list(_OMITTED_FIELDS),
    }
