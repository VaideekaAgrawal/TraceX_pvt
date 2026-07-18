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
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from db.enums import Priority, WatchEntityType
from db.models.base import utcnow
from db.models.platform import Watchlist
from db.repositories.platform import WatchlistRepository
from db.repositories.reference import AccountRepository

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
