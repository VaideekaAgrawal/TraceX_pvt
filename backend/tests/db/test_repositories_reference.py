"""
Round-trip tests for `db.repositories.reference`: CustomerRepository,
AccountRepository, TransactionRepository.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from db.enums import (
    AccountStatus,
    ActorType,
    Channel,
    EntityType,
    KycStatus,
    RiskLevel,
)
from db.repositories.reference import AccountRepository, CustomerRepository, TransactionRepository

NOW = datetime(2026, 7, 1, tzinfo=UTC)


def test_customer_repository_round_trip(session: Session) -> None:
    repo = CustomerRepository(session)
    customer = repo.create(
        customer_id="C1",
        name="Alice Example",
        entity_type=EntityType.INDIVIDUAL,
        risk_rating=RiskLevel.LOW,
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    session.commit()

    fetched = repo.get("C1")
    assert fetched is not None
    assert fetched.name == "Alice Example"
    assert fetched.kyc_status == KycStatus.PENDING  # model default applied

    updated = repo.update(
        "C1",
        risk_rating=RiskLevel.HIGH,
        kyc_status=KycStatus.VERIFIED,
        actor_type=ActorType.INVESTIGATOR,
        actor_id="U1",
    )
    session.commit()

    assert updated.risk_rating == RiskLevel.HIGH
    assert updated.kyc_status == KycStatus.VERIFIED
    refetched = repo.get("C1")
    assert refetched is not None
    assert refetched.risk_rating == RiskLevel.HIGH
    assert customer.customer_id == "C1"


def test_account_repository_round_trip_and_get_by_customer(session: Session) -> None:
    CustomerRepository(session).create(
        customer_id="C1",
        name="Alice",
        entity_type=EntityType.INDIVIDUAL,
        risk_rating=RiskLevel.LOW,
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )

    repo = AccountRepository(session)
    repo.create(
        account_id="A1", customer_id="C1", actor_type=ActorType.SYSTEM, actor_id=None
    )
    repo.create(
        account_id="A2", customer_id="C1", actor_type=ActorType.SYSTEM, actor_id=None
    )
    repo.create(account_id="A3", actor_type=ActorType.SYSTEM, actor_id=None)
    session.commit()

    assert repo.get("A1") is not None
    accounts = repo.get_by_customer("C1")
    assert {a.account_id for a in accounts} == {"A1", "A2"}

    updated = repo.update(
        "A1",
        status=AccountStatus.DORMANT,
        current_risk_score=42.5,
        actor_type=ActorType.INVESTIGATOR,
        actor_id="U1",
    )
    session.commit()
    assert updated.status == AccountStatus.DORMANT
    assert updated.current_risk_score == 42.5


def test_transaction_repository_create_and_list_for_account_in_window(session: Session) -> None:
    account_repo = AccountRepository(session)
    account_repo.create(account_id="A1", actor_type=ActorType.SYSTEM, actor_id=None)
    account_repo.create(account_id="A2", actor_type=ActorType.SYSTEM, actor_id=None)
    session.commit()

    txn_repo = TransactionRepository(session)
    early = datetime(2026, 6, 1, tzinfo=UTC)
    mid = datetime(2026, 6, 15, tzinfo=UTC)
    late = datetime(2026, 7, 1, tzinfo=UTC)

    txn_repo.create(
        txn_id="T1",
        timestamp=early,
        source_account="A1",
        dest_account="A2",
        amount=100,
        channel=Channel.UPI,
        is_laundering=0,
        ingested_at=NOW,
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    txn_repo.create(
        txn_id="T2",
        timestamp=mid,
        source_account="A1",
        dest_account="A2",
        amount=200,
        channel=Channel.NEFT,
        is_laundering=0,
        ingested_at=NOW,
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    txn_repo.create(
        txn_id="T3",
        timestamp=late,
        source_account="A2",
        dest_account="A1",
        amount=300,
        channel=Channel.IMPS,
        is_laundering=0,
        ingested_at=NOW,
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    session.commit()

    assert txn_repo.get("T1") is not None

    windowed = txn_repo.list_for_account_in_window(
        "A1", start=datetime(2026, 6, 10, tzinfo=UTC), end=datetime(2026, 6, 20, tzinfo=UTC)
    )
    assert [t.txn_id for t in windowed] == ["T2"]

    as_source_only = txn_repo.list_for_account_in_window("A1", as_dest=False)
    assert {t.txn_id for t in as_source_only} == {"T1", "T2"}

    all_for_a1 = txn_repo.list_for_account_in_window("A1")
    assert {t.txn_id for t in all_for_a1} == {"T1", "T2", "T3"}
