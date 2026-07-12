from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from db.enums import ActorType, Channel
from db.repositories.reference import AccountRepository, TransactionRepository
from investigation.case_graph import add_flow_percentages, build_case_graph_store, shape_money_flow


def _seed_accounts(session: Session, *account_ids: str) -> None:
    repo = AccountRepository(session)
    for account_id in account_ids:
        repo.create(account_id=account_id, actor_type=ActorType.SYSTEM, actor_id=None)


def _seed_txn(
    session: Session, txn_id: str, source: str, dest: str, amount: float, ts: datetime
) -> None:
    TransactionRepository(session).create(
        txn_id=txn_id,
        timestamp=ts,
        source_account=source,
        dest_account=dest,
        amount=amount,
        channel=Channel.NEFT,
        is_laundering=0,
        ingested_at=ts,
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )


def test_build_case_graph_store_dedups_transaction_touching_two_case_accounts(
    session: Session,
) -> None:
    _seed_accounts(session, "A", "B", "C")
    session.commit()
    ts = datetime(2026, 1, 1, tzinfo=UTC)
    # T1 (A -> B) touches BOTH accounts in the case's scope -- the naive
    # "loop per account, pull its transactions" approach would otherwise
    # fetch it twice (once from A's window, once from B's).
    _seed_txn(session, "T1", "A", "B", 100.0, ts)
    _seed_txn(session, "T2", "B", "C", 50.0, ts)
    session.commit()

    store = build_case_graph_store(session, ["A", "B", "C"])

    assert len(store.transactions_df) == 2
    assert set(store.transactions_df["txn_id"]) == {"T1", "T2"}


def test_build_case_graph_store_empty_when_no_transactions(session: Session) -> None:
    _seed_accounts(session, "A")
    session.commit()

    store = build_case_graph_store(session, ["A"])

    assert store.transactions_df.empty
    assert store.get_stats()["num_nodes"] == 1  # node still present, no edges


def test_shape_money_flow_aggregates_by_counterparty(session: Session) -> None:
    _seed_accounts(session, "A", "B", "C")
    session.commit()
    ts = datetime(2026, 1, 1, tzinfo=UTC)
    _seed_txn(session, "T1", "A", "B", 100.0, ts)
    _seed_txn(session, "T2", "A", "B", 50.0, ts)  # second A->B txn: sums into one source bucket
    _seed_txn(session, "T3", "B", "C", 30.0, ts)  # B->C: C is a beneficiary of B
    session.commit()

    store = build_case_graph_store(session, ["A", "B", "C"])
    ego = store.get_ego_graph("B", radius=1)
    shaped = shape_money_flow(ego, "B")

    assert shaped["center"] == "B"
    assert shaped["sources"] == [{"account_id": "A", "total_amount": 150.0, "txn_count": 2}]
    assert shaped["beneficiaries"] == [{"account_id": "C", "total_amount": 30.0, "txn_count": 1}]


def test_shape_money_flow_ignores_self_loop(session: Session) -> None:
    shaped = shape_money_flow(
        {
            "edges": [
                {"source_account": "B", "dest_account": "B", "amount": 10.0},
                {"source_account": "A", "dest_account": "B", "amount": 20.0},
            ]
        },
        "B",
    )
    assert shaped["sources"] == [{"account_id": "A", "total_amount": 20.0, "txn_count": 1}]
    assert shaped["beneficiaries"] == []


def test_add_flow_percentages_computes_share_of_each_bucket_total(session: Session) -> None:
    _seed_accounts(session, "A", "B", "C", "D")
    session.commit()
    ts = datetime(2026, 1, 1, tzinfo=UTC)
    _seed_txn(session, "T1", "A", "B", 75.0, ts)  # source A: 75% of B's inflow
    _seed_txn(session, "T2", "C", "B", 25.0, ts)  # source C: 25% of B's inflow
    _seed_txn(session, "T3", "B", "D", 40.0, ts)  # only beneficiary: 100% of B's outflow
    session.commit()

    store = build_case_graph_store(session, ["A", "B", "C", "D"])
    ego = store.get_ego_graph("B", radius=1)
    shaped = add_flow_percentages(shape_money_flow(ego, "B"))

    sources_by_id = {s["account_id"]: s for s in shaped["sources"]}
    assert sources_by_id["A"]["pct_of_inflow"] == 75.0
    assert sources_by_id["C"]["pct_of_inflow"] == 25.0
    assert shaped["beneficiaries"][0]["pct_of_outflow"] == 100.0
    # Original fields untouched, just extended.
    assert sources_by_id["A"]["total_amount"] == 75.0


def test_add_flow_percentages_zero_total_is_zero_not_a_crash() -> None:
    shaped = add_flow_percentages({"center": "B", "sources": [], "beneficiaries": []})
    assert shaped == {"center": "B", "sources": [], "beneficiaries": []}


def test_add_flow_percentages_does_not_mutate_input() -> None:
    original = {
        "center": "B",
        "sources": [{"account_id": "A", "total_amount": 10.0, "txn_count": 1}],
        "beneficiaries": [],
    }
    add_flow_percentages(original)
    # The input dict's source entry must not have gained `pct_of_inflow`
    # (pure function -- returns a new structure, doesn't mutate `shaped`).
    assert "pct_of_inflow" not in original["sources"][0]
