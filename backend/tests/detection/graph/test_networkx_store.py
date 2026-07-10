from __future__ import annotations

import pandas as pd
import pytest

from detection.graph.networkx_store import NetworkXGraphStore
from detection.graph.store import GraphStore


def _ts(s: str) -> pd.Timestamp:
    return pd.Timestamp(s)


@pytest.fixture()
def accounts_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "account_id": ["A", "B", "C", "D", "E", "F", "G"],
            "branch_city": ["Mumbai", "Delhi", "Pune", "Mumbai", "Chennai", "Pune", "Pune"],
        }
    )


@pytest.fixture()
def transactions_df() -> pd.DataFrame:
    # A -> B -> C -> A is a 3-node round-trip cycle (feeds detect_cycles;
    # get_transaction_chains never revisits an already-visited node within a
    # chain, so a cycle never itself shows up as a "chain").
    # D -> E -> F -> G is a genuine 3-hop linear layering chain (feeds
    # get_transaction_chains).
    return pd.DataFrame(
        [
            {
                "txn_id": "T1",
                "source_account": "A",
                "dest_account": "B",
                "amount": 100_000.0,
                "timestamp": _ts("2026-01-01 10:00"),
                "channel": "NEFT",
                "is_laundering": 0,
            },
            {
                "txn_id": "T2",
                "source_account": "B",
                "dest_account": "C",
                "amount": 95_000.0,
                "timestamp": _ts("2026-01-01 10:10"),
                "channel": "NEFT",
                "is_laundering": 0,
            },
            {
                "txn_id": "T3",
                "source_account": "C",
                "dest_account": "A",
                "amount": 90_000.0,
                "timestamp": _ts("2026-01-01 10:20"),
                "channel": "NEFT",
                "is_laundering": 0,
            },
            {
                "txn_id": "T4",
                "source_account": "D",
                "dest_account": "E",
                "amount": 5_000.0,
                "timestamp": _ts("2026-01-02 09:00"),
                "channel": "UPI",
                "is_laundering": 0,
            },
            {
                "txn_id": "T5",
                "source_account": "E",
                "dest_account": "F",
                "amount": 4_800.0,
                "timestamp": _ts("2026-01-02 09:20"),
                "channel": "UPI",
                "is_laundering": 0,
            },
            {
                "txn_id": "T6",
                "source_account": "F",
                "dest_account": "G",
                "amount": 4_600.0,
                "timestamp": _ts("2026-01-02 09:40"),
                "channel": "UPI",
                "is_laundering": 0,
            },
        ]
    )


@pytest.fixture()
def store(accounts_df, transactions_df) -> NetworkXGraphStore:
    return NetworkXGraphStore(accounts_df, transactions_df)


def test_is_a_graph_store(store: NetworkXGraphStore) -> None:
    assert isinstance(store, GraphStore)


def test_build_creates_expected_nodes_and_edges(store: NetworkXGraphStore) -> None:
    assert store.graph.number_of_nodes() == 7
    assert store.graph.number_of_edges() == 6


def test_compute_centrality_shapes(store: NetworkXGraphStore) -> None:
    centrality = store.compute_centrality()
    assert set(centrality.keys()) == {"pagerank", "betweenness"}
    # A receives money (from C) so it should have nonzero pagerank.
    assert centrality["pagerank"]["A"] > 0
    # Cached: second call returns the same object without recomputation.
    assert store.compute_centrality() is centrality


def test_detect_cycles_finds_the_round_trip(store: NetworkXGraphStore) -> None:
    cycles = store.detect_cycles(max_length=5, max_cycles=10)
    cycle_sets = [frozenset(c) for c in cycles]
    assert frozenset({"A", "B", "C"}) in cycle_sets
    # D/E is not part of any cycle.
    assert not any({"D", "E"} & cs for cs in cycle_sets)


def test_get_transaction_chains_finds_the_3_hop_chain(store: NetworkXGraphStore) -> None:
    chains = store.get_transaction_chains(min_hops=3, time_window_minutes=60)
    assert len(chains) >= 1
    longest = max(chains, key=len)
    assert len(longest) == 3
    assert longest[0]["from"] == "D"
    assert longest[-1]["to"] == "G"


def test_get_transaction_chains_empty_when_no_hops_meet_min(store: NetworkXGraphStore) -> None:
    chains = store.get_transaction_chains(min_hops=10, time_window_minutes=60)
    assert chains == []


def test_get_ego_graph_radius_1_from_a(store: NetworkXGraphStore) -> None:
    result = store.get_ego_graph("A", radius=1)
    assert result["center"] == "A"
    node_ids = {n["account_id"] for n in result["nodes"]}
    # 1 hop from A touches B (outgoing) and C (incoming, via C->A).
    assert {"A", "B", "C"} <= node_ids
    assert "D" not in node_ids
    edge_txn_ids = {e["txn_id"] for e in result["edges"]}
    assert edge_txn_ids == {"T1", "T3"}


def test_get_ego_graph_radius_2_reaches_full_cycle(store: NetworkXGraphStore) -> None:
    result = store.get_ego_graph("A", radius=2)
    node_ids = {n["account_id"] for n in result["nodes"]}
    assert {"A", "B", "C"} <= node_ids
    edge_txn_ids = {e["txn_id"] for e in result["edges"]}
    assert edge_txn_ids == {"T1", "T2", "T3"}


def test_get_ego_graph_nodes_carry_account_columns(store: NetworkXGraphStore) -> None:
    result = store.get_ego_graph("A", radius=1)
    a_node = next(n for n in result["nodes"] if n["account_id"] == "A")
    assert a_node["branch_city"] == "Mumbai"


def test_get_ego_graph_unknown_account_returns_empty(store: NetworkXGraphStore) -> None:
    result = store.get_ego_graph("ZZZ", radius=2)
    assert result == {"nodes": [], "edges": [], "center": "ZZZ"}


def test_get_ego_graph_time_window_excludes_out_of_range_txns(store: NetworkXGraphStore) -> None:
    # Window covers only T1 (10:00) — T3 (10:20, C->A) should be excluded,
    # so the walk never reaches C via that edge within radius=1.
    result = store.get_ego_graph(
        "A", radius=1, time_window=(_ts("2026-01-01 09:55"), _ts("2026-01-01 10:05"))
    )
    edge_txn_ids = {e["txn_id"] for e in result["edges"]}
    assert edge_txn_ids == {"T1"}


def test_empty_transactions_df_builds_nodes_only() -> None:
    accounts = pd.DataFrame({"account_id": ["X", "Y"]})
    empty_cols = [
        "source_account",
        "dest_account",
        "amount",
        "timestamp",
        "channel",
        "is_laundering",
    ]
    empty_txns = pd.DataFrame(columns=empty_cols)
    store = NetworkXGraphStore(accounts, empty_txns)
    assert store.graph.number_of_nodes() == 2
    assert store.graph.number_of_edges() == 0
    assert store.compute_centrality() == {"pagerank": {}, "betweenness": {}}
    assert store.detect_cycles() == []
    assert store.get_transaction_chains() == []


def test_get_ego_graph_caps_per_account_fan_out() -> None:
    # A hub account with far more than the 500-row safety valve worth of
    # transactions touching it -- without the cap, get_ego_graph would
    # return all of them.
    hub_rows = [
        {
            "txn_id": f"HUB{i}",
            "source_account": "HUB",
            "dest_account": f"LEAF{i}",
            "amount": 100.0,
            "timestamp": _ts("2026-01-01 00:00") + pd.Timedelta(minutes=i),
            "channel": "UPI",
        }
        for i in range(600)
    ]
    accounts = pd.DataFrame({"account_id": ["HUB", *[f"LEAF{i}" for i in range(600)]]})
    txns = pd.DataFrame(hub_rows)
    store = NetworkXGraphStore(accounts, txns)

    result = store.get_ego_graph("HUB", radius=1)
    assert len(result["edges"]) == 500


def test_simple_digraph_is_cached_across_calls(transactions_df, accounts_df) -> None:
    store = NetworkXGraphStore(accounts_df, transactions_df)
    first = store._simple_digraph()
    second = store._simple_digraph()
    assert first is second


def test_detect_cycles_still_correct_after_simple_digraph_cache(store: NetworkXGraphStore) -> None:
    # Calling detect_cycles twice must not be affected by caching the
    # underlying simple digraph -- results should be stable.
    first = store.detect_cycles(max_length=5, max_cycles=10)
    second = store.detect_cycles(max_length=5, max_cycles=10)
    assert [frozenset(c) for c in first] == [frozenset(c) for c in second]
