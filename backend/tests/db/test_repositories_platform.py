"""
Round-trip tests for `db.repositories.platform`: UserRepository,
WatchlistRepository, IngestionLogRepository, and light read coverage of
AuditLogRepository (the dedicated hash-chain proof lives in
`test_repositories_audit_chain.py`).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from db.enums import ActorType, CaseLevel, CaseStatus, Priority, UserRole, WatchEntityType
from db.repositories.investigation import CaseRepository
from db.repositories.platform import (
    AuditLogRepository,
    IngestionLogRepository,
    UserRepository,
    WatchlistRepository,
)
from db.repositories.reference import AccountRepository


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


def test_user_repository_list_by_ids(session: Session) -> None:
    repo = UserRepository(session)
    repo.create(
        user_id="U1",
        username="inv1",
        email="inv1@example.com",
        password_hash="x",
        role=UserRole.INVESTIGATOR,
        full_name="Investigator One",
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    repo.create(
        user_id="U2",
        username="inv2",
        email="inv2@example.com",
        password_hash="x",
        role=UserRole.INVESTIGATOR,
        full_name="Investigator Two",
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    session.commit()

    assert {u.user_id for u in repo.list_by_ids(["U1", "U2", "NOPE"])} == {"U1", "U2"}
    assert repo.list_by_ids([]) == []


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


# ── ROADMAP Phase 14: list_filtered/count_filtered (GET /audit-log) ────────


def _seed_audit_fixture(session: Session) -> None:
    """Three distinguishable rows: an `account_created` row with no actor
    (case_id=None), a `case_created` row by U1 scoped to CASE1, and an
    `escalated` row by U2 scoped to CASE1 -- enough combinations to exercise
    every filter dimension independently."""
    AccountRepository(session).create(account_id="A1", actor_type=ActorType.SYSTEM, actor_id=None)
    CaseRepository(session).create(
        case_id="CASE1",
        primary_account_id="A1",
        status=CaseStatus.NEW,
        level=CaseLevel.L1,
        priority=Priority.P2,
        actor_type=ActorType.INVESTIGATOR,
        actor_id="U1",
    )
    CaseRepository(session).update(
        "CASE1",
        priority=Priority.P1,
        action="escalated",
        actor_type=ActorType.ADMIN,
        actor_id="U2",
    )
    session.commit()


def test_audit_log_list_filtered_by_case_id(session: Session) -> None:
    _seed_audit_fixture(session)
    repo = AuditLogRepository(session)
    rows = repo.list_filtered(case_id="CASE1")
    assert {r.action for r in rows} == {"case_created", "escalated"}
    assert repo.count_filtered(case_id="CASE1") == 2


def test_audit_log_list_filtered_by_actor_id(session: Session) -> None:
    _seed_audit_fixture(session)
    repo = AuditLogRepository(session)
    rows = repo.list_filtered(actor_id="U2")
    assert [r.action for r in rows] == ["escalated"]
    assert repo.count_filtered(actor_id="U2") == 1
    assert repo.list_filtered(actor_id="NOBODY") == []


def test_audit_log_list_filtered_by_single_action_string(session: Session) -> None:
    _seed_audit_fixture(session)
    repo = AuditLogRepository(session)
    rows = repo.list_filtered(action="case_created")
    assert [r.action for r in rows] == ["case_created"]
    assert repo.count_filtered(action="case_created") == 1


def test_audit_log_list_filtered_by_action_list(session: Session) -> None:
    _seed_audit_fixture(session)
    repo = AuditLogRepository(session)
    rows = repo.list_filtered(action=["case_created", "escalated"])
    assert {r.action for r in rows} == {"case_created", "escalated"}
    assert repo.count_filtered(action=["case_created", "escalated"]) == 2


def test_audit_log_list_filtered_by_since(session: Session) -> None:
    _seed_audit_fixture(session)
    repo = AuditLogRepository(session)
    far_future = datetime.now(UTC) + timedelta(days=1)
    far_past = datetime.now(UTC) - timedelta(days=1)
    assert repo.list_filtered(since=far_future) == []
    assert repo.count_filtered(since=far_future) == 0
    assert len(repo.list_filtered(since=far_past)) == len(repo.list_filtered())


def test_audit_log_list_filtered_orders_most_recent_first(session: Session) -> None:
    """Deliberately the opposite order from `list_for_case`/`list_since`
    (both ascending) -- this method serves a "what just happened" feed."""
    _seed_audit_fixture(session)
    repo = AuditLogRepository(session)
    rows = repo.list_filtered()
    ids = [r.id for r in rows]
    assert ids == sorted(ids, reverse=True)


def test_audit_log_list_filtered_limit_and_offset(session: Session) -> None:
    _seed_audit_fixture(session)
    repo = AuditLogRepository(session)
    total = repo.count_filtered()
    assert total >= 3
    page1 = repo.list_filtered(limit=1, offset=0)
    page2 = repo.list_filtered(limit=1, offset=1)
    assert len(page1) == 1
    assert len(page2) == 1
    assert page1[0].id != page2[0].id


def test_audit_log_list_filtered_and_count_filtered_empty_when_no_rows_match(
    session: Session,
) -> None:
    repo = AuditLogRepository(session)
    assert repo.list_filtered(case_id="NOPE") == []
    assert repo.count_filtered(case_id="NOPE") == 0
