"""
`investigation.timeline` -- ROADMAP Phase 6 timeline reconstruction +
timeline<->graph sync contract. The sync-contract assertion (`txn_id`
overlap with a graph-filter edge set for the same underlying data) is the
one genuinely load-bearing test here; the rest is ordering/windowing.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from db.enums import ActorType, CaseLevel, CaseStatus, Channel, Priority
from db.repositories.investigation import CaseAccountRepository, CaseRepository
from db.repositories.reference import AccountRepository, TransactionRepository
from investigation.graph_filters import GraphFilters, get_filtered_ego_graph
from investigation.timeline import build_timeline


def _seed_account(session: Session, account_id: str) -> None:
    AccountRepository(session).create(
        account_id=account_id, actor_type=ActorType.SYSTEM, actor_id=None
    )


def _seed_txn(
    session: Session, txn_id: str, src: str, dst: str, amount: float, ts: datetime
) -> None:
    TransactionRepository(session).create(
        txn_id=txn_id, timestamp=ts, source_account=src, dest_account=dst, amount=amount,
        channel=Channel.NEFT, is_laundering=0, ingested_at=ts,
        actor_type=ActorType.SYSTEM, actor_id=None,
    )


def _seed_case_with_accounts(session: Session, case_id: str, account_ids: list[str]) -> None:
    CaseRepository(session).create(
        case_id=case_id, primary_account_id=account_ids[0], status=CaseStatus.IN_PROGRESS,
        level=CaseLevel.L2, priority=Priority.P2, actor_type=ActorType.SYSTEM, actor_id=None,
    )
    for account_id in account_ids:
        CaseAccountRepository(session).add_account(
            case_id=case_id, account_id=account_id, actor_type=ActorType.SYSTEM, actor_id=None
        )


def test_build_timeline_ascending_order_regardless_of_insertion_order(session: Session) -> None:
    _seed_account(session, "A")
    _seed_account(session, "B")
    session.commit()

    late = datetime(2026, 3, 1, tzinfo=UTC)
    early = datetime(2026, 1, 1, tzinfo=UTC)
    mid = datetime(2026, 2, 1, tzinfo=UTC)
    # Insert out of chronological order deliberately.
    _seed_txn(session, "T_LATE", "A", "B", 300.0, late)
    _seed_txn(session, "T_EARLY", "B", "A", 100.0, early)
    _seed_txn(session, "T_MID", "A", "B", 200.0, mid)
    _seed_case_with_accounts(session, "CASE1", ["A", "B"])
    session.commit()

    timeline = build_timeline(session, "CASE1", "A")

    assert [e["txn_id"] for e in timeline["events"]] == ["T_EARLY", "T_MID", "T_LATE"]
    assert timeline["events"][0]["direction"] == "in"  # B -> A
    assert timeline["events"][1]["direction"] == "out"  # A -> B


def test_build_timeline_respects_window(session: Session) -> None:
    _seed_account(session, "A")
    _seed_account(session, "B")
    session.commit()
    early = datetime(2026, 1, 1, tzinfo=UTC)
    mid = datetime(2026, 2, 1, tzinfo=UTC)
    late = datetime(2026, 3, 1, tzinfo=UTC)
    _seed_txn(session, "T1", "A", "B", 100.0, early)
    _seed_txn(session, "T2", "A", "B", 100.0, mid)
    _seed_txn(session, "T3", "A", "B", 100.0, late)
    _seed_case_with_accounts(session, "CASE1", ["A", "B"])
    session.commit()

    timeline = build_timeline(
        session, "CASE1", "A",
        start=datetime(2026, 1, 15, tzinfo=UTC), end=datetime(2026, 2, 15, tzinfo=UTC),
    )

    assert [e["txn_id"] for e in timeline["events"]] == ["T2"]


def test_build_timeline_rejects_account_outside_case_scope(session: Session) -> None:
    """Regression test (code-review finding, Phase 6): `build_timeline`
    must defense-in-depth-validate `account_id` is in `case_id`'s scope,
    same as `orchestration.pattern_explanation._assemble_facts` already
    did."""
    _seed_account(session, "A")
    session.commit()
    CaseRepository(session).create(
        case_id="CASE1", primary_account_id="A", status=CaseStatus.IN_PROGRESS,
        level=CaseLevel.L2, priority=Priority.P2, actor_type=ActorType.SYSTEM, actor_id=None,
    )
    session.commit()  # deliberately no CaseAccountRepository.add_account

    with pytest.raises(ValueError, match="not in case"):
        build_timeline(session, "CASE1", "A")


def test_timeline_txn_id_overlaps_graph_filter_edges_for_same_data(session: Session) -> None:
    """The sync-contract assertion: every timeline event's `txn_id` is the
    same key `investigation.graph_filters.get_filtered_ego_graph`'s edges
    carry, for the same underlying seed data -- a frontend correlates
    timeline<->graph purely by that shared key."""
    _seed_account(session, "CENTER")
    _seed_account(session, "OTHER")
    session.commit()
    ts1 = datetime(2026, 1, 1, tzinfo=UTC)
    ts2 = datetime(2026, 1, 2, tzinfo=UTC)
    _seed_txn(session, "SHARED1", "CENTER", "OTHER", 100.0, ts1)
    _seed_txn(session, "SHARED2", "OTHER", "CENTER", 50.0, ts2)
    session.commit()

    CaseRepository(session).create(
        case_id="CASE1", primary_account_id="CENTER", status=CaseStatus.IN_PROGRESS,
        level=CaseLevel.L2, priority=Priority.P2, actor_type=ActorType.SYSTEM, actor_id=None,
    )
    for account_id in ("CENTER", "OTHER"):
        CaseAccountRepository(session).add_account(
            case_id="CASE1", account_id=account_id, actor_type=ActorType.SYSTEM, actor_id=None
        )
    session.commit()

    timeline = build_timeline(session, "CASE1", "CENTER")
    graph = get_filtered_ego_graph(
        session, "CASE1", "CENTER", radius=1, filters=GraphFilters(),
        case_account_ids=["CENTER", "OTHER"],
    )

    timeline_txn_ids = {e["txn_id"] for e in timeline["events"]}
    graph_txn_ids = {e["txn_id"] for e in graph["edges"]}
    assert timeline_txn_ids == graph_txn_ids == {"SHARED1", "SHARED2"}
