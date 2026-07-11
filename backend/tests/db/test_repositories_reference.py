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


def test_list_for_account_in_window_most_recent_keeps_newest_within_limit(
    session: Session,
) -> None:
    """Regression test (code-review finding, Phase 6): the default
    `ORDER BY timestamp ASC LIMIT limit` keeps the OLDEST rows once an
    account exceeds `limit` -- `most_recent=True` must keep the NEWEST
    `limit` rows instead (still returned in ascending order)."""
    account_repo = AccountRepository(session)
    account_repo.create(account_id="A1", actor_type=ActorType.SYSTEM, actor_id=None)
    account_repo.create(account_id="A2", actor_type=ActorType.SYSTEM, actor_id=None)
    session.commit()

    txn_repo = TransactionRepository(session)
    for i in range(5):
        txn_repo.create(
            txn_id=f"T{i}",
            timestamp=datetime(2026, 1, 1 + i, tzinfo=UTC),
            source_account="A1",
            dest_account="A2",
            amount=100 + i,
            channel=Channel.UPI,
            is_laundering=0,
            ingested_at=NOW,
            actor_type=ActorType.SYSTEM,
            actor_id=None,
        )
    session.commit()

    oldest_first = txn_repo.list_for_account_in_window("A1", limit=3)
    assert [t.txn_id for t in oldest_first] == ["T0", "T1", "T2"]

    newest_first = txn_repo.list_for_account_in_window("A1", limit=3, most_recent=True)
    # Still ascending order, but the NEWEST 3, not the oldest 3.
    assert [t.txn_id for t in newest_first] == ["T2", "T3", "T4"]


def _seed_search_fixture(session: Session) -> TransactionRepository:
    account_repo = AccountRepository(session)
    for account_id in ("A1", "A2", "A3", "OUT"):
        account_repo.create(account_id=account_id, actor_type=ActorType.SYSTEM, actor_id=None)
    session.commit()

    txn_repo = TransactionRepository(session)
    ts = datetime(2026, 6, 1, tzinfo=UTC)
    txn_repo.create(
        txn_id="S1", timestamp=ts, source_account="A1", dest_account="A2", amount=100,
        channel=Channel.UPI, is_laundering=0, ingested_at=NOW,
        actor_type=ActorType.SYSTEM, actor_id=None,
    )
    txn_repo.create(
        txn_id="S2", timestamp=ts.replace(day=15), source_account="A2", dest_account="A3",
        amount=5_000, channel=Channel.NEFT, is_laundering=0, ingested_at=NOW,
        actor_type=ActorType.SYSTEM, actor_id=None,
    )
    txn_repo.create(
        txn_id="S3", timestamp=ts.replace(month=7), source_account="A3", dest_account="A1",
        amount=200, channel=Channel.UPI, is_laundering=0, ingested_at=NOW,
        actor_type=ActorType.SYSTEM, actor_id=None,
    )
    # Touches only the out-of-scope account -- must never surface regardless
    # of filters (the security-invariant this method exists to guarantee).
    txn_repo.create(
        txn_id="S_OUT", timestamp=ts, source_account="OUT", dest_account="OUT",
        amount=999_999, channel=Channel.UPI, is_laundering=0, ingested_at=NOW,
        actor_type=ActorType.SYSTEM, actor_id=None,
    )
    session.commit()
    return txn_repo


def test_search_for_accounts_filters_and_paginates(session: Session) -> None:
    txn_repo = _seed_search_fixture(session)
    scope = ["A1", "A2", "A3"]

    all_in_scope = txn_repo.search_for_accounts(scope)
    assert {t.txn_id for t in all_in_scope} == {"S1", "S2", "S3"}
    assert txn_repo.count_for_accounts(scope) == 3

    by_amount = txn_repo.search_for_accounts(scope, min_amount=1_000)
    assert [t.txn_id for t in by_amount] == ["S2"]
    assert txn_repo.count_for_accounts(scope, min_amount=1_000) == 1

    by_channel = txn_repo.search_for_accounts(scope, channels=[Channel.NEFT])
    assert [t.txn_id for t in by_channel] == ["S2"]

    by_window = txn_repo.search_for_accounts(
        scope, start=datetime(2026, 6, 10, tzinfo=UTC), end=datetime(2026, 6, 20, tzinfo=UTC)
    )
    assert [t.txn_id for t in by_window] == ["S2"]

    # direction is relative to the whole scope, not one account: "out" of
    # scope means source_account is in scope.
    outbound = txn_repo.search_for_accounts(scope, direction="out")
    assert {t.txn_id for t in outbound} == {"S1", "S2", "S3"}
    inbound_narrow = txn_repo.search_for_accounts(["A2"], direction="in")
    assert [t.txn_id for t in inbound_narrow] == ["S1"]

    page1 = txn_repo.search_for_accounts(scope, limit=2, sort="timestamp_asc")
    page2 = txn_repo.search_for_accounts(scope, limit=2, offset=2, sort="timestamp_asc")
    assert [t.txn_id for t in page1] == ["S1", "S2"]
    assert [t.txn_id for t in page2] == ["S3"]


def test_search_for_accounts_never_returns_out_of_scope_transactions(session: Session) -> None:
    txn_repo = _seed_search_fixture(session)
    # No filter loose enough to leak the out-of-scope account's transaction
    # into an in-scope search -- the security invariant
    # `investigation.transaction_search` structurally relies on.
    results = txn_repo.search_for_accounts(
        ["A1", "A2", "A3"], min_amount=0, max_amount=10_000_000
    )
    assert "S_OUT" not in {t.txn_id for t in results}


def test_search_for_accounts_empty_scope_returns_empty_no_query(session: Session) -> None:
    txn_repo = _seed_search_fixture(session)
    assert txn_repo.search_for_accounts([]) == []
    assert txn_repo.count_for_accounts([]) == 0
