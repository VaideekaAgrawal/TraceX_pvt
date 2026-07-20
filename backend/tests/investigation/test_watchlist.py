"""Watchlist screening + auto-escalation — ROADMAP Phase 11."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from db.enums import (
    ActorType,
    Channel,
    DetectionType,
    EntityType,
    Priority,
    RiskLevel,
    WatchEntityType,
)
from db.repositories.detection import AlertRepository
from db.repositories.platform import WatchlistRepository
from db.repositories.reference import AccountRepository, CustomerRepository, TransactionRepository
from investigation.watchlist import WatchlistScreener, enrich_entry, escalate_for_watchlist

# `dict[str, Any]` so `**_SYS` unpacks cleanly into each repo's typed kwargs
# (an inferred `dict[str, ActorType | None]` fails every other keyword's type).
_SYS: dict[str, Any] = {"actor_type": ActorType.SYSTEM, "actor_id": None}


def _add(session: Session, etype: WatchEntityType, value: str, **kw) -> None:
    WatchlistRepository(session).create(
        entry_id=f"WL-{value}", entity_type=etype, entity_value=value,
        added_by="U1", **_SYS, **kw,
    )


def _account(session: Session, acc: str, cust: str | None) -> None:
    if cust and CustomerRepository(session).get(cust) is None:
        CustomerRepository(session).create(
            customer_id=cust, name="X", entity_type=EntityType.INDIVIDUAL,
            risk_rating=RiskLevel.LOW, **_SYS,
        )
    AccountRepository(session).create(account_id=acc, customer_id=cust, **_SYS)
    session.flush()


def test_screen_matches_a_watchlisted_account(session: Session) -> None:
    _account(session, "ACC1", "CUST1")
    _add(session, WatchEntityType.ACCOUNT, "ACC1", reason="mule")
    session.commit()
    hit = WatchlistScreener(session, ["ACC1"]).screen(["ACC1"])
    assert hit is not None and hit.entity_value == "ACC1"


def test_screen_matches_a_watchlisted_customer_via_its_account(session: Session) -> None:
    _account(session, "ACC2", "CUST2")
    _add(session, WatchEntityType.CUSTOMER, "CUST2", reason="prior SAR")
    session.commit()
    hit = WatchlistScreener(session, ["ACC2"]).screen(["ACC2"])
    assert hit is not None and hit.entity_type == WatchEntityType.CUSTOMER


def test_no_match_returns_none(session: Session) -> None:
    _account(session, "ACC3", "CUST3")
    _add(session, WatchEntityType.ACCOUNT, "OTHER-ACC")
    session.commit()
    assert WatchlistScreener(session, ["ACC3"]).screen(["ACC3"]) is None


def test_expired_entry_does_not_match(session: Session) -> None:
    _account(session, "ACC4", "CUST4")
    _add(session, WatchEntityType.ACCOUNT, "ACC4",
         expires_at=datetime.now(UTC) - timedelta(days=1))
    session.commit()
    assert WatchlistScreener(session, ["ACC4"]).screen(["ACC4"]) is None


def test_empty_watchlist_screener_is_empty(session: Session) -> None:
    screener = WatchlistScreener(session, ["ACC-X"])
    assert screener.is_empty
    assert screener.screen(["ACC-X"]) is None


def test_escalate_forces_p1_on_hit_only(session: Session) -> None:
    _account(session, "ACC5", "CUST5")
    _add(session, WatchEntityType.ACCOUNT, "ACC5")
    session.commit()
    screener = WatchlistScreener(session, ["ACC5", "ACC-CLEAN"])
    assert escalate_for_watchlist(Priority.P4, screener.screen(["ACC5"])) == Priority.P1
    assert escalate_for_watchlist(Priority.P3, screener.screen(["ACC-CLEAN"])) == Priority.P3


# ── enrich_entry — GET /watchlist display fields ─────────────────────────


def test_enrich_account_entry_resolves_display_name_and_risk(session: Session) -> None:
    CustomerRepository(session).create(
        customer_id="CUST-ENR1", name="Alice Sharma", entity_type=EntityType.INDIVIDUAL,
        risk_rating=RiskLevel.LOW, **_SYS,
    )
    AccountRepository(session).create(
        account_id="ACC-ENR1", customer_id="CUST-ENR1", current_risk_score=71.5, **_SYS,
    )
    entry = WatchlistRepository(session).create(
        entry_id="WL-ENR1", entity_type=WatchEntityType.ACCOUNT, entity_value="ACC-ENR1",
        added_by="U1", **_SYS,
    )
    session.commit()
    enrichment = enrich_entry(session, entry)
    assert enrichment.display_name == "Alice Sharma"
    assert enrichment.current_risk == 71.5
    assert enrichment.latest_activity is None
    assert enrichment.alerts == []


def test_enrich_customer_entry_resolves_display_name_directly(session: Session) -> None:
    CustomerRepository(session).create(
        customer_id="CUST-ENR2", name="Bob Rao", entity_type=EntityType.INDIVIDUAL,
        risk_rating=RiskLevel.LOW, **_SYS,
    )
    entry = WatchlistRepository(session).create(
        entry_id="WL-ENR2", entity_type=WatchEntityType.CUSTOMER, entity_value="CUST-ENR2",
        added_by="U1", **_SYS,
    )
    session.commit()
    enrichment = enrich_entry(session, entry)
    assert enrichment.display_name == "Bob Rao"
    # No per-customer numeric risk score column exists — honest `None`, not a
    # derived proxy (judgment call, see `investigation.watchlist.enrich_entry`).
    assert enrichment.current_risk is None


def test_enrich_account_entry_with_no_customer_has_no_display_name(session: Session) -> None:
    AccountRepository(session).create(account_id="ACC-ENR-NOCUST", **_SYS)
    entry = WatchlistRepository(session).create(
        entry_id="WL-ENR-NOCUST", entity_type=WatchEntityType.ACCOUNT,
        entity_value="ACC-ENR-NOCUST", added_by="U1", **_SYS,
    )
    session.commit()
    enrichment = enrich_entry(session, entry)
    assert enrichment.display_name is None


def test_enrich_latest_activity_is_most_recent_transaction(session: Session) -> None:
    _account(session, "ACC-ENR3", None)
    AccountRepository(session).create(account_id="ACC-ENR3-CP", **_SYS)
    older = datetime(2025, 1, 1, tzinfo=UTC)
    newer = datetime(2026, 1, 1, tzinfo=UTC)
    TransactionRepository(session).create(
        txn_id="TXN-ENR-OLD", timestamp=older, source_account="ACC-ENR3",
        dest_account="ACC-ENR3-CP", amount=100.0, channel=Channel.UPI, is_laundering=0,
        ingested_at=older, **_SYS,
    )
    TransactionRepository(session).create(
        txn_id="TXN-ENR-NEW", timestamp=newer, source_account="ACC-ENR3",
        dest_account="ACC-ENR3-CP", amount=200.0, channel=Channel.UPI, is_laundering=0,
        ingested_at=newer, **_SYS,
    )
    entry = WatchlistRepository(session).create(
        entry_id="WL-ENR3", entity_type=WatchEntityType.ACCOUNT, entity_value="ACC-ENR3",
        added_by="U1", **_SYS,
    )
    session.commit()
    enrichment = enrich_entry(session, entry)
    # SQLite round-trips a stored aware datetime as naive-but-UTC-valued (same
    # behavior `db.repositories._audit` already documents elsewhere) -- compare
    # on the naive value rather than assert tzinfo equality.
    assert enrichment.latest_activity is not None
    assert enrichment.latest_activity.replace(tzinfo=UTC) == newer


def test_enrich_alerts_filters_by_entry_created_at(session: Session) -> None:
    _account(session, "ACC-ENR4", None)
    entry = WatchlistRepository(session).create(
        entry_id="WL-ENR4", entity_type=WatchEntityType.ACCOUNT, entity_value="ACC-ENR4",
        added_by="U1", **_SYS,
    )
    session.commit()
    before = entry.created_at - timedelta(days=1)
    after = entry.created_at + timedelta(days=1)
    AlertRepository(session).create(
        alert_id="AL-ENR-BEFORE", detection_type=DetectionType.layering,
        primary_account_id="ACC-ENR4", account_ids=["ACC-ENR4"], score=0.5, risk_score=50.0,
        severity=RiskLevel.MEDIUM, priority=Priority.P3, status="open", source="pipeline",
        created_at=before, **_SYS,
    )
    AlertRepository(session).create(
        alert_id="AL-ENR-AFTER", detection_type=DetectionType.layering,
        primary_account_id="ACC-ENR4", account_ids=["ACC-ENR4"], score=0.9, risk_score=90.0,
        severity=RiskLevel.HIGH, priority=Priority.P1, status="open", source="pipeline",
        created_at=after, **_SYS,
    )
    session.commit()
    enrichment = enrich_entry(session, entry)
    assert [a.alert_id for a in enrichment.alerts] == ["AL-ENR-AFTER"]


def test_enrich_non_resolvable_entity_types_return_empty(session: Session) -> None:
    for etype in (WatchEntityType.DEVICE, WatchEntityType.MERCHANT, WatchEntityType.COMPANY):
        entry = WatchlistRepository(session).create(
            entry_id=f"WL-ENR-{etype}", entity_type=etype, entity_value="whatever",
            added_by="U1", **_SYS,
        )
        session.commit()
        enrichment = enrich_entry(session, entry)
        assert enrichment.display_name is None
        assert enrichment.current_risk is None
        assert enrichment.latest_activity is None
        assert enrichment.alerts == []


def test_enrich_account_entry_with_missing_account_returns_empty(session: Session) -> None:
    # A watchlisted account_id that no longer resolves to a real Account row
    # (e.g. deleted downstream) -- enrichment fails open to empty, not an error.
    entry = WatchlistRepository(session).create(
        entry_id="WL-ENR-GHOST", entity_type=WatchEntityType.ACCOUNT, entity_value="GHOST-ACC",
        added_by="U1", **_SYS,
    )
    session.commit()
    enrichment = enrich_entry(session, entry)
    assert enrichment.display_name is None
    assert enrichment.alerts == []
