"""Watchlist screening + alert auto-escalation — ROADMAP Phase 11.

A compliance reviewer can add a risky entity (a customer or an account) to the
watchlist; from then on, any detection alert that *touches* that entity is
auto-escalated to the top priority, so it cannot sit unnoticed at the bottom of a
queue. This is the persistent-monitoring half of Phase 11 (`docs/DATA_SCHEMA.md`
§3.5: "alerts touching a watchlisted entity get auto-priority"; FATF R.10 ongoing
due diligence on higher-risk relationships).

`WatchlistScreener` is built once per detection run (the active watchlist + the
account→customer map for the accounts under evaluation), then screened cheaply
per alert — the same "compute the shared thing once, read it many times" shape
`compute_workload` uses in the pipeline. Screening matches an alert's accounts
against `ACCOUNT` entries and those accounts' owning customers against `CUSTOMER`
entries; the other `WatchEntityType`s (DEVICE/MERCHANT/COMPANY) have no
corresponding column on `accounts`/`customers` yet, so they are recorded but
never match — recorded honestly rather than silently dropped.

`enrich_entry` (below) is the read-time counterpart for `GET /watchlist`: given
one entry, resolve its display name / current risk / latest activity / alert
history for the UI, rather than the frontend faking these client-side. Same
DEVICE/MERCHANT/COMPANY honesty convention applies — those three resolve to
`None`/`[]`, never a guess.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from db.enums import Priority, WatchEntityType
from db.models.base import utcnow
from db.models.platform import Watchlist
from db.models.reference import Account
from db.repositories.detection import AlertRepository
from db.repositories.platform import WatchlistRepository
from db.repositories.reference import AccountRepository, CustomerRepository, TransactionRepository

#: A watchlist hit forces the highest priority — the whole point of the feature.
_ESCALATED_PRIORITY = Priority.P1


def _as_aware(dt: datetime) -> datetime:
    """SQLite round-trips timestamps tz-naive; treat a naive `expires_at` as UTC
    so comparing it against an aware `utcnow()` doesn't raise (the same
    normalization `db/repositories/_audit.py` applies for its hash chain)."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


@dataclass(frozen=True)
class WatchlistHit:
    """Why an alert was escalated: the matched entry and the entity that matched."""

    entry_id: str
    entity_type: WatchEntityType
    entity_value: str


class WatchlistScreener:
    """Active-watchlist matcher, built once and screened many times."""

    def __init__(self, session: Session, account_ids: list[str]) -> None:
        now = utcnow()
        entries = [
            e
            for e in WatchlistRepository(session).list_active()
            if e.expires_at is None or _as_aware(e.expires_at) > now
        ]
        self._by_account: dict[str, Watchlist] = {
            e.entity_value: e for e in entries if e.entity_type == WatchEntityType.ACCOUNT
        }
        self._by_customer: dict[str, Watchlist] = {
            e.entity_value: e for e in entries if e.entity_type == WatchEntityType.CUSTOMER
        }
        # account -> customer for the accounts under evaluation (one batched query),
        # only if any CUSTOMER entry exists (no point otherwise).
        self._account_to_customer: dict[str, str] = {}
        if self._by_customer and account_ids:
            for account in AccountRepository(session).list_by_ids(account_ids):
                if account.customer_id is not None:
                    self._account_to_customer[account.account_id] = account.customer_id

    @property
    def is_empty(self) -> bool:
        return not self._by_account and not self._by_customer

    def screen(self, account_ids: list[str]) -> WatchlistHit | None:
        """The first watchlist entry any of these accounts (or their owning
        customers) hits, or None. Deterministic: account matches before customer
        matches, accounts in sorted order, so the same alert always reports the
        same hit."""
        for account_id in sorted(account_ids):
            entry = self._by_account.get(account_id)
            if entry is not None:
                return WatchlistHit(entry.entry_id, entry.entity_type, entry.entity_value)
        for account_id in sorted(account_ids):
            customer_id = self._account_to_customer.get(account_id)
            if customer_id is not None:
                entry = self._by_customer.get(customer_id)
                if entry is not None:
                    return WatchlistHit(entry.entry_id, entry.entity_type, entry.entity_value)
        return None


def escalate_for_watchlist(priority: Priority, hit: WatchlistHit | None) -> Priority:
    """The escalated priority for an alert, given its screening result. A hit
    forces `P1`; no hit leaves the computed priority untouched."""
    return _ESCALATED_PRIORITY if hit is not None else priority


# ── entry enrichment (GET /watchlist display fields) ─────────────────────
#
# The frontend needs each watchlist entry to show more than the raw record:
# who/what it resolves to, its current risk, its most recent activity, and
# every alert raised since it was added (so an entry is actionable, not just
# a name on a list). This is display-time enrichment, not a new persisted
# state -- computed fresh per `GET /watchlist` call.


@dataclass(frozen=True)
class WatchlistAlertRef:
    """One alert raised at/after this watchlist entry's `created_at`, for the
    entry's clickable alert-history list. `case_id` is nullable -- an alert
    with no case yet isn't openable, but that's the frontend's concern, not
    this layer's; the field is always present either way."""

    alert_id: str
    case_id: str | None
    created_at: datetime
    risk_score: float
    detection_type: str


@dataclass(frozen=True)
class WatchlistEnrichment:
    """Display/risk/activity/alert-history enrichment for one watchlist
    entry. `display_name`/`current_risk`/`latest_activity` are `None` (and
    `alerts` is `[]`) for DEVICE/MERCHANT/COMPANY entries -- there is no
    backing column to resolve those three types against, the same
    "recorded, never matched" honesty convention `WatchlistScreener`'s own
    docstring already establishes for screening, extended here to display."""

    display_name: str | None
    current_risk: float | None
    latest_activity: datetime | None
    alerts: list[WatchlistAlertRef]


_EMPTY_ENRICHMENT = WatchlistEnrichment(
    display_name=None, current_risk=None, latest_activity=None, alerts=[]
)


def _customer_name_for_account(session: Session, account: Account) -> str | None:
    """The owning customer's name for an ACCOUNT watchlist entry, or `None`
    if the account has no linked customer."""
    if account.customer_id is None:
        return None
    customer = CustomerRepository(session).get(account.customer_id)
    return customer.name if customer is not None else None


def _latest_activity(session: Session, account_ids: list[str]) -> datetime | None:
    """Most recent `Transaction.timestamp` touching any of `account_ids`
    (as source or dest). Reuses `TransactionRepository.search_for_accounts`
    (already batches over an account-id set and already supports
    `sort="timestamp_desc"`) rather than a new query -- only the newest row
    is needed, so `limit=1`."""
    if not account_ids:
        return None
    txns = TransactionRepository(session).search_for_accounts(
        account_ids, sort="timestamp_desc", limit=1
    )
    return txns[0].timestamp if txns else None


def _alerts_since(
    session: Session, account_ids: list[str], since: datetime
) -> list[WatchlistAlertRef]:
    """Alerts whose *primary* account is any of `account_ids`, raised at/
    after `since` (the watchlist entry's own `created_at`), newest first.
    Reuses `AlertRepository.list_for_primary_account(s)` (already ordered
    descending by `created_at`) and filters the date floor in Python --
    those repository methods have no date-floor parameter, and this
    codebase's own precedent (see `list_for_primary_accounts`'s docstring)
    is not to add one for a single small-scale caller. `_as_aware`
    normalizes both sides the same way `WatchlistScreener` already does for
    `expires_at`, so a naive-from-SQLite timestamp compares correctly
    against an aware one."""
    if not account_ids:
        return []
    since_aware = _as_aware(since)
    alerts = (
        AlertRepository(session).list_for_primary_account(account_ids[0])
        if len(account_ids) == 1
        else AlertRepository(session).list_for_primary_accounts(account_ids)
    )
    return [
        WatchlistAlertRef(
            alert_id=a.alert_id, case_id=a.case_id, created_at=a.created_at,
            risk_score=a.risk_score, detection_type=str(a.detection_type),
        )
        for a in alerts
        if _as_aware(a.created_at) >= since_aware
    ]


def enrich_entry(session: Session, entry: Watchlist) -> WatchlistEnrichment:
    """Resolve one watchlist entry's display name, current risk, latest
    activity, and post-entry alert history for `GET /watchlist`. Computed
    fresh per call, not stored -- the active watchlist is small (tens of
    entries, not thousands), so a straightforward per-entry query set is
    fine; this function itself fetches each of an entry's account/customer
    rows at most once and passes the resolved account-id set on to its two
    helpers rather than re-resolving it."""
    if entry.entity_type == WatchEntityType.ACCOUNT:
        account = AccountRepository(session).get(entry.entity_value)
        if account is None:
            return _EMPTY_ENRICHMENT
        display_name = _customer_name_for_account(session, account)
        current_risk = account.current_risk_score
        account_ids = [account.account_id]
    elif entry.entity_type == WatchEntityType.CUSTOMER:
        customer = CustomerRepository(session).get(entry.entity_value)
        if customer is None:
            return _EMPTY_ENRICHMENT
        display_name = customer.name
        # No per-customer numeric risk score column exists (only the coarse
        # `risk_rating` enum) -- `None` is the honest answer here, not a
        # derived "max across accounts" proxy (judgment call, see this
        # module's task brief: prefer the honest `None` over inventing a
        # derived figure `docs/DATA_SCHEMA.md` doesn't define).
        current_risk = None
        account_ids = [
            a.account_id
            for a in AccountRepository(session).list_by_customer_ids([customer.customer_id])
        ]
    else:
        # DEVICE / MERCHANT / COMPANY: no backing column to resolve against.
        return _EMPTY_ENRICHMENT

    return WatchlistEnrichment(
        display_name=display_name,
        current_risk=current_risk,
        latest_activity=_latest_activity(session, account_ids),
        alerts=_alerts_since(session, account_ids, entry.created_at),
    )
