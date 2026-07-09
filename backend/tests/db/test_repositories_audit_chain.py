"""
Dedicated proof of the `audit_log` SHA-256 hash chain (`docs/DATA_SCHEMA.md`
§3.5 / §4 decision 3): every repository write appends a row, the chain links
gaplessly across *different* repositories sharing one Session, each row's
hash is independently recomputable from its own stored columns plus the
previous row's stored hash, and mutating a stored row breaks verification.
"""
from __future__ import annotations

import itertools

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.enums import (
    ActorType,
    CaseLevel,
    CaseStatus,
    EntityType,
    NoteSource,
    Priority,
    RiskLevel,
    UserRole,
)
from db.models.platform import AuditLog
from db.repositories._audit import compute_row_hash, verify_chain
from db.repositories.investigation import CaseRepository, NoteRepository
from db.repositories.platform import AuditLogRepository, UserRepository
from db.repositories.reference import AccountRepository, CustomerRepository


def test_writes_across_different_repositories_form_one_gapless_chain(session: Session) -> None:
    # Five writes, deliberately via five different repositories, in one
    # Session -- proves the chain doesn't reset per-repository and that
    # `append_audit_log`'s flush-before-lookup keeps it gapless even though
    # nothing is committed until the very end.
    UserRepository(session).create(
        user_id="U1",
        username="inv1",
        email="inv1@example.com",
        password_hash="x",
        role=UserRole.INVESTIGATOR,
        full_name="Investigator One",
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    CustomerRepository(session).create(
        customer_id="C1",
        name="Alice",
        entity_type=EntityType.INDIVIDUAL,
        risk_rating=RiskLevel.LOW,
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    AccountRepository(session).create(
        account_id="A1", customer_id="C1", actor_type=ActorType.SYSTEM, actor_id=None
    )
    CaseRepository(session).create(
        case_id="CASE1",
        primary_account_id="A1",
        status=CaseStatus.NEW,
        level=CaseLevel.L1,
        priority=Priority.P2,
        assigned_to="U1",
        actor_type=ActorType.INVESTIGATOR,
        actor_id="U1",
    )
    NoteRepository(session).create(
        note_id="N1",
        case_id="CASE1",
        author_id="U1",
        source=NoteSource.INVESTIGATOR,
        body="Opened case.",
        actor_type=ActorType.INVESTIGATOR,
        actor_id="U1",
    )
    session.commit()

    rows = list(session.scalars(select(AuditLog).order_by(AuditLog.id.asc())))
    assert [r.action for r in rows] == [
        "user_created",
        "customer_created",
        "account_created",
        "case_created",
        "note_created",
    ]

    # -- prev_hash/row_hash linkage, row by row --
    assert rows[0].prev_hash is None
    for earlier, later in itertools.pairwise(rows):
        assert later.prev_hash == earlier.row_hash

    # -- every row_hash is independently recomputable from its own stored
    #    columns + the previous row's stored row_hash --
    prev_hash = None
    for row in rows:
        recomputed = compute_row_hash(
            prev_hash=prev_hash,
            actor_type=row.actor_type,
            actor_id=row.actor_id,
            action=row.action,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            case_id=row.case_id,
            details=row.details,
            created_at=row.created_at,
        )
        assert recomputed == row.row_hash
        prev_hash = row.row_hash

    # -- the repository-level verification helper agrees --
    assert AuditLogRepository(session).verify_chain() is True
    assert verify_chain(session) is True


def test_update_writes_capture_before_after_and_keep_chain_valid(session: Session) -> None:
    repo = CustomerRepository(session)
    repo.create(
        customer_id="C1",
        name="Alice",
        entity_type=EntityType.INDIVIDUAL,
        risk_rating=RiskLevel.LOW,
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    repo.update(
        "C1",
        risk_rating=RiskLevel.CRITICAL,
        actor_type=ActorType.INVESTIGATOR,
        actor_id="U1",
    )
    session.commit()

    rows = list(session.scalars(select(AuditLog).order_by(AuditLog.id.asc())))
    assert [r.action for r in rows] == ["customer_created", "customer_updated"]

    update_row = rows[1]
    assert update_row.details is not None
    assert update_row.details["before"]["risk_rating"] == "LOW"
    assert update_row.details["after"]["risk_rating"] == "CRITICAL"
    assert verify_chain(session) is True


def test_tampering_with_a_stored_row_breaks_verification(session: Session) -> None:
    repo = CustomerRepository(session)
    repo.create(
        customer_id="C1",
        name="Alice",
        entity_type=EntityType.INDIVIDUAL,
        risk_rating=RiskLevel.LOW,
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    repo.create(
        customer_id="C2",
        name="Bob",
        entity_type=EntityType.INDIVIDUAL,
        risk_rating=RiskLevel.LOW,
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    session.commit()

    assert verify_chain(session) is True

    # Tamper with the first row's recorded action, in place, the way an
    # attacker with raw DB access (but not the ability to recompute a valid
    # chain) would -- this must never be a path a repository exposes.
    first_row = session.scalars(select(AuditLog).order_by(AuditLog.id.asc())).first()
    assert first_row is not None
    first_row.action = "customer_created_TAMPERED"
    session.flush()

    assert verify_chain(session) is False

    # And tampering with the *second* row's prev_hash (attempting to relink
    # around a deleted/altered row) is equally caught.
    session.rollback()
    assert verify_chain(session) is True
    second_row = session.scalars(select(AuditLog).order_by(AuditLog.id.asc())).all()[1]
    second_row.prev_hash = "0" * 64
    session.flush()
    assert verify_chain(session) is False
