"""
Round-trip tests for `db.repositories.platform`: UserRepository,
WatchlistRepository, IngestionLogRepository, and light read coverage of
AuditLogRepository (the dedicated hash-chain proof lives in
`test_repositories_audit_chain.py`).
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from db.enums import ActorType, UserRole, WatchEntityType
from db.repositories.platform import (
    AuditLogRepository,
    IngestionLogRepository,
    UserRepository,
    WatchlistRepository,
)


def test_user_repository_round_trip(session: Session) -> None:
    repo = UserRepository(session)
    repo.create(
        user_id="U1",
        username="inv1",
        email="inv1@example.com",
        password_hash="hash",
        role=UserRole.INVESTIGATOR,
        full_name="Investigator One",
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    session.commit()

    assert repo.get("U1") is not None
    assert repo.get_by_username("inv1") is not None
    assert repo.get_by_username("nobody") is None
    assert [u.user_id for u in repo.list_by_role(UserRole.INVESTIGATOR)] == ["U1"]

    updated = repo.record_login("U1", actor_type=ActorType.SYSTEM, actor_id=None)
    session.commit()
    assert updated.last_login_at is not None

    deactivated = repo.deactivate("U1", actor_type=ActorType.ADMIN, actor_id="U2")
    session.commit()
    assert deactivated.active is False
    assert repo.list_by_role(UserRole.INVESTIGATOR) == []


def test_watchlist_repository_round_trip(session: Session) -> None:
    UserRepository(session).create(
        user_id="U1",
        username="admin1",
        email="admin1@example.com",
        password_hash="x",
        role=UserRole.ADMIN_COMPLIANCE,
        full_name="Admin One",
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    session.commit()

    repo = WatchlistRepository(session)
    repo.create(
        entry_id="W1",
        entity_type=WatchEntityType.CUSTOMER,
        entity_value="C1",
        added_by="U1",
        actor_type=ActorType.ADMIN,
        actor_id="U1",
    )
    session.commit()

    assert repo.get("W1") is not None
    assert repo.get_active_by_value(WatchEntityType.CUSTOMER, "C1") is not None
    assert [w.entry_id for w in repo.list_active()] == ["W1"]

    deactivated = repo.deactivate("W1", actor_type=ActorType.ADMIN, actor_id="U1")
    session.commit()
    assert deactivated.active is False
    assert repo.list_active() == []
    assert repo.get_active_by_value(WatchEntityType.CUSTOMER, "C1") is None


def test_ingestion_log_repository_round_trip(session: Session) -> None:
    repo = IngestionLogRepository(session)
    repo.create(
        file_hash="hash1",
        filename="day1.csv",
        status="pending",
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    session.commit()

    assert repo.exists("hash1") is True
    assert repo.exists("hash2") is False

    updated = repo.update(
        "hash1",
        status="ingested",
        num_transactions=100,
        num_accounts=10,
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    session.commit()
    assert updated.status == "ingested"
    assert updated.num_transactions == 100


def test_audit_log_repository_reads(session: Session) -> None:
    UserRepository(session).create(
        user_id="U1",
        username="inv1",
        email="inv1@example.com",
        password_hash="x",
        role=UserRole.INVESTIGATOR,
        full_name="Investigator One",
        actor_type=ActorType.INVESTIGATOR,
        actor_id="U1",
    )
    session.commit()

    audit_repo = AuditLogRepository(session)
    rows = audit_repo.list_for_entity("user", "U1")
    assert len(rows) == 1
    assert rows[0].action == "user_created"
    assert audit_repo.verify_chain() is True
