"""Watchlist screening + auto-escalation — ROADMAP Phase 11."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from db.enums import ActorType, EntityType, Priority, RiskLevel, WatchEntityType
from db.repositories.platform import WatchlistRepository
from db.repositories.reference import AccountRepository, CustomerRepository
from investigation.watchlist import WatchlistScreener, escalate_for_watchlist

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
