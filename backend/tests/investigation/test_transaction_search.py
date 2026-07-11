"""
`investigation.transaction_search` -- ROADMAP Phase 6 Complete Transaction
Analysis. Beyond filter/pagination composition, the security-invariant test
is the one that actually matters: an account outside `case_id`'s scope must
never surface, regardless of how the caller queries.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from db.enums import ActorType, CaseLevel, CaseStatus, Channel, Priority
from db.repositories.investigation import CaseAccountRepository, CaseRepository
from db.repositories.reference import AccountRepository, TransactionRepository
from investigation.transaction_search import search

TS = datetime(2026, 1, 1, tzinfo=UTC)


def _seed_case_with_accounts(session: Session, account_ids: list[str]) -> None:
    for account_id in account_ids:
        AccountRepository(session).create(
            account_id=account_id, actor_type=ActorType.SYSTEM, actor_id=None
        )
    session.commit()
    CaseRepository(session).create(
        case_id="CASE1", primary_account_id=account_ids[0], status=CaseStatus.IN_PROGRESS,
        level=CaseLevel.L2, priority=Priority.P2, actor_type=ActorType.SYSTEM, actor_id=None,
    )
    for account_id in account_ids:
        CaseAccountRepository(session).add_account(
            case_id="CASE1", account_id=account_id, actor_type=ActorType.SYSTEM, actor_id=None
        )
    session.commit()


def _seed_txn(session: Session, txn_id: str, src: str, dst: str, amount: float) -> None:
    TransactionRepository(session).create(
        txn_id=txn_id, timestamp=TS, source_account=src, dest_account=dst, amount=amount,
        channel=Channel.UPI, is_laundering=0, ingested_at=TS,
        actor_type=ActorType.SYSTEM, actor_id=None,
    )


def test_search_whole_case_scope(session: Session) -> None:
    _seed_case_with_accounts(session, ["A1", "A2", "A3"])
    _seed_txn(session, "T1", "A1", "A2", 100.0)
    _seed_txn(session, "T2", "A2", "A3", 200.0)
    session.commit()

    result = search(session, "CASE1")

    assert {i["txn_id"] for i in result["items"]} == {"T1", "T2"}
    assert result["total_count"] == 2
    assert result["limit"] == 200
    assert result["offset"] == 0


def test_search_narrowed_to_one_account(session: Session) -> None:
    _seed_case_with_accounts(session, ["A1", "A2", "A3"])
    _seed_txn(session, "T1", "A1", "A2", 100.0)
    _seed_txn(session, "T2", "A2", "A3", 200.0)
    session.commit()

    result = search(session, "CASE1", account_id="A2")

    assert {i["txn_id"] for i in result["items"]} == {"T1", "T2"}  # both touch A2
    for item in result["items"]:
        assert item["direction"] in ("in", "out")


def test_search_resolves_branch_and_product_metadata(session: Session) -> None:
    AccountRepository(session).create(
        account_id="A1", branch_city="Mumbai", account_type="current",
        actor_type=ActorType.SYSTEM, actor_id=None,
    )
    AccountRepository(session).create(
        account_id="A2", branch_city="Delhi", account_type="savings",
        actor_type=ActorType.SYSTEM, actor_id=None,
    )
    session.commit()
    CaseRepository(session).create(
        case_id="CASE1", primary_account_id="A1", status=CaseStatus.IN_PROGRESS,
        level=CaseLevel.L2, priority=Priority.P2, actor_type=ActorType.SYSTEM, actor_id=None,
    )
    for account_id in ("A1", "A2"):
        CaseAccountRepository(session).add_account(
            case_id="CASE1", account_id=account_id, actor_type=ActorType.SYSTEM, actor_id=None
        )
    session.commit()
    _seed_txn(session, "T1", "A1", "A2", 500.0)
    session.commit()

    result = search(session, "CASE1")

    item = result["items"][0]
    assert item["source_branch_city"] == "Mumbai"
    assert item["dest_branch_city"] == "Delhi"
    assert item["source_account_type"] == "current"
    assert item["dest_account_type"] == "savings"


def test_search_pagination(session: Session) -> None:
    _seed_case_with_accounts(session, ["A1", "A2"])
    for i in range(5):
        _seed_txn(session, f"T{i}", "A1", "A2", 100.0 + i)
    session.commit()

    page1 = search(session, "CASE1", limit=2, offset=0, sort="amount_asc")
    page2 = search(session, "CASE1", limit=2, offset=2, sort="amount_asc")

    assert [i["txn_id"] for i in page1["items"]] == ["T0", "T1"]
    assert [i["txn_id"] for i in page2["items"]] == ["T2", "T3"]
    assert page1["total_count"] == 5


def test_search_never_leaks_out_of_scope_account_transactions(session: Session) -> None:
    """Security invariant: no filter combination, and no `account_id`
    narrowing, can surface a transaction touching an account outside
    `case_id`'s scope."""
    _seed_case_with_accounts(session, ["A1", "A2"])
    AccountRepository(session).create(
        account_id="OUTSIDE", actor_type=ActorType.SYSTEM, actor_id=None
    )
    session.commit()
    _seed_txn(session, "T1", "A1", "A2", 100.0)
    _seed_txn(session, "T_OUT", "OUTSIDE", "OUTSIDE", 999_999.0)
    session.commit()

    # Loosest possible whole-case query.
    result = search(session, "CASE1", min_amount=0, max_amount=10_000_000)
    assert "T_OUT" not in {i["txn_id"] for i in result["items"]}

    # An attempt to narrow to the out-of-scope account directly must yield
    # nothing, not the out-of-scope account's own activity.
    result_narrowed = search(session, "CASE1", account_id="OUTSIDE")
    assert result_narrowed["items"] == []
    assert result_narrowed["total_count"] == 0
