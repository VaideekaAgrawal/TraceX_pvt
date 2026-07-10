"""
`NetworkXGraphStore` — the (only, per ROADMAP decision 5) `GraphStore`
implementation for this phase. Ported from `archive/fund-flow-tracker/
services/graph/engine.py::TransactionGraph`, minus the primitives
`backend/detection/graph/store.py`'s module docstring documents as not
carried forward, plus a new `get_ego_graph` (case-scoped ego-graph
extraction) ported from `infrastructure/database.py::SQLiteAdapter.
get_ego_graph`'s BFS shape but walking the in-memory graph/DataFrame instead
of issuing one SQL query per hop.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

import networkx as nx
import numpy as np
import pandas as pd

from detection.graph.store import GraphStore

logger = logging.getLogger(__name__)

# Matches the archived `SQLiteAdapter.get_ego_graph`'s `LIMIT 500` per-hop
# safety valve — without it a hub account entering the BFS frontier can
# balloon the ego-graph to tens of thousands of edges.
_EGO_GRAPH_PER_ACCOUNT_LIMIT = 500


class NetworkXGraphStore(GraphStore):
    """NetworkX `MultiDiGraph`-backed graph engine, built once from
    `accounts_df`/`transactions_df` pulled via the repository layer (not raw
    SQL — see class docstring in ROADMAP Phase 3's plan)."""

    def __init__(self, accounts_df: pd.DataFrame, transactions_df: pd.DataFrame):
        self.accounts_df = accounts_df
        self.transactions_df = transactions_df
        self._G = nx.MultiDiGraph()
        self._centrality_cache: dict[str, dict[str, float]] = {}
        self._simple_digraph_cache: nx.DiGraph | None = None
        self._build()

    @property
    def graph(self) -> nx.MultiDiGraph:
        return self._G

    # ── Construction ──────────────────────────────────────────────────

    def _build(self) -> None:
        """Build graph: nodes = accounts, edges = transactions (memory-safe).

        Edges store ONLY `amount` + `is_laundering` (minimal per-edge
        memory, matching the archive's own documented optimization) —
        detectors that need timestamp/channel read `transactions_df`
        directly instead (confirmed: none of the ported pattern detectors
        read timestamp/channel off graph edges)."""
        txns = self.transactions_df
        if len(txns) == 0:
            if len(self.accounts_df) > 0 and "account_id" in self.accounts_df.columns:
                self._G.add_nodes_from(self.accounts_df["account_id"].tolist())
            return

        all_src = txns["source_account"].values
        all_dst = txns["dest_account"].values
        all_accts = np.union1d(all_src, all_dst)
        self._G.add_nodes_from(all_accts.tolist())

        has_label = "is_laundering" in txns.columns
        src_col = txns["source_account"].values
        dst_col = txns["dest_account"].values
        amt_col = txns["amount"].values
        lbl_col = (
            txns["is_laundering"].values if has_label else np.zeros(len(src_col), dtype=np.int8)
        )

        BATCH = 200_000
        batch = []
        for i in range(len(src_col)):
            edge_attrs = {"amount": float(amt_col[i]), "is_laundering": int(lbl_col[i])}
            batch.append((src_col[i], dst_col[i], edge_attrs))
            if len(batch) == BATCH:
                self._G.add_edges_from(batch)
                batch.clear()
        if batch:
            self._G.add_edges_from(batch)

        logger.info(
            "Graph built: %d nodes, %d edges", self._G.number_of_nodes(), self._G.number_of_edges()
        )

    def _simple_digraph(self) -> nx.DiGraph:
        """Lightweight weighted DiGraph from `transactions_df` (avoids
        iterating every edge of the full MultiDiGraph).

        Cached the same way `compute_centrality` caches its own comparably
        expensive derivation from the same immutable `transactions_df` —
        `detect_cycles` (the only caller) never mutates the graph this
        returns (it works off `.subgraph(...).copy()`), so memoizing is
        safe. Without this, the Rule Engine instantiating a fresh
        `RoundTripDetector` per enabled Tier-1 "cycle" rule meant N enabled
        cycle-rules rebuilt this from scratch N times against the same
        `graph_store` instance."""
        if self._simple_digraph_cache is not None:
            return self._simple_digraph_cache
        if len(self.transactions_df) == 0:
            self._simple_digraph_cache = nx.DiGraph()
            return self._simple_digraph_cache
        agg = (
            self.transactions_df.groupby(["source_account", "dest_account"], sort=False)["amount"]
            .sum()
            .reset_index()
        )
        agg.columns = ["source", "dest", "weight"]
        simple = nx.from_pandas_edgelist(
            agg, source="source", target="dest", edge_attr="weight", create_using=nx.DiGraph()
        )
        self._simple_digraph_cache = simple
        return simple

    # ── Centrality (cached) ──────────────────────────────────────────

    def compute_centrality(self) -> dict[str, dict[str, float]]:
        """Fast pandas-based centrality approximations (ported as-is — see
        `store.py` module docstring for why this isn't "fixed" to real
        NetworkX pagerank/betweenness):

        PageRank approx  : normalised weighted in-flow per node.
        Betweenness approx: normalised product of in-degree x out-degree.
        """
        if self._centrality_cache:
            return self._centrality_cache

        txns = self.transactions_df
        if len(txns) == 0:
            self._centrality_cache = {"pagerank": {}, "betweenness": {}}
            return self._centrality_cache

        in_flow = txns.groupby("dest_account")["amount"].sum()
        total = float(in_flow.sum()) or 1.0
        pr = (in_flow / total).to_dict()

        in_deg = txns.groupby("dest_account")["source_account"].nunique().rename("in_d")
        out_deg = txns.groupby("source_account")["dest_account"].nunique().rename("out_d")
        both = pd.concat([in_deg, out_deg], axis=1).fillna(0)
        raw_bc = both["in_d"] * both["out_d"]
        max_bc = float(raw_bc.max()) or 1.0
        bc = (raw_bc / max_bc).to_dict()

        self._centrality_cache = {"pagerank": pr, "betweenness": bc}
        logger.info("Centrality computed (fast pandas approx): %d nodes", len(pr))
        return self._centrality_cache

    # ── Cycle detection (bounded) ────────────────────────────────────

    def detect_cycles(self, max_length: int = 12, max_cycles: int = 2000) -> list[list[str]]:
        """Bounded cycle detection, short cycles (2-3 nodes) first — ported
        as-is from `TransactionGraph.detect_cycles`."""
        sg = self._simple_digraph()
        if sg.number_of_nodes() == 0:
            return []
        MAX_SCC_SIZE = 500
        candidate_nodes: set[str] = set()
        for scc in nx.strongly_connected_components(sg):
            if 2 <= len(scc) <= MAX_SCC_SIZE:
                candidate_nodes.update(scc)
            if len(candidate_nodes) > 50000:
                break
        if not candidate_nodes:
            return []
        sg = sg.subgraph(candidate_nodes).copy()
        logger.info(
            "Cycle detection: %d candidate nodes in SCCs (max_length=%d)",
            sg.number_of_nodes(),
            max_length,
        )
        cycles: list[list[str]] = []
        seen_sets: set[frozenset] = set()
        try:
            for cycle in nx.simple_cycles(sg, length_bound=3):
                cs = frozenset(cycle)
                if cs not in seen_sets:
                    cycles.append(cycle)
                    seen_sets.add(cs)
                if len(cycles) >= max_cycles:
                    break
            if len(cycles) < max_cycles and max_length > 3:
                for cycle in nx.simple_cycles(sg, length_bound=max_length):
                    cs = frozenset(cycle)
                    if cs not in seen_sets:
                        cycles.append(cycle)
                        seen_sets.add(cs)
                    if len(cycles) >= max_cycles:
                        break
        except Exception:
            logger.warning("Cycle detection failed or timed out")
        logger.info("Cycle detection: found %d cycles", len(cycles))
        return cycles

    # ── Transaction chains ───────────────────────────────────────────

    def get_transaction_chains(
        self,
        min_hops: int = 3,
        time_window_minutes: int = 120,
        max_chains: int = 500,
        shuffle_starts: bool = False,
    ) -> list[list[dict[str, Any]]]:
        """Extract temporal transaction chains directly from
        `transactions_df` — ported as-is from `TransactionGraph.
        get_transaction_chains`."""
        df = self.transactions_df.copy()
        if "timestamp" not in df.columns or df.empty:
            return []

        df = df.sort_values("timestamp").reset_index(drop=True)

        outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
        needed_cols = ["source_account", "dest_account", "amount", "timestamp"]
        if "channel" in df.columns:
            needed_cols.append("channel")
        for rec in df[needed_cols].to_dict("records"):
            outgoing[rec["source_account"]].append(
                {
                    "from": rec["source_account"],
                    "to": rec["dest_account"],
                    "amount": float(rec["amount"]),
                    "timestamp": rec["timestamp"],
                    "channel": rec.get("channel", ""),
                }
            )

        chains: list[list[dict[str, Any]]] = []
        used_edges: set[tuple] = set()

        if shuffle_starts:
            import random

            start_candidates = list(outgoing.keys())
            random.Random(42).shuffle(start_candidates)
        else:
            start_candidates = sorted(outgoing.keys(), key=lambda n: len(outgoing[n]), reverse=True)

        for start_node in start_candidates:
            if len(chains) >= max_chains:
                break
            for start_txn in outgoing[start_node]:
                edge_key = (start_txn["from"], start_txn["to"], str(start_txn["timestamp"]))
                if edge_key in used_edges:
                    continue

                chain = [start_txn]
                current_node = start_txn["to"]
                current_time = start_txn["timestamp"]
                window_end = current_time + pd.Timedelta(minutes=time_window_minutes)
                visited_in_chain = {start_txn["from"], start_txn["to"]}

                for _ in range(20):
                    best_next = None
                    for txn in outgoing.get(current_node, []):
                        if txn["to"] in visited_in_chain:
                            continue
                        if current_time <= txn["timestamp"] <= window_end:
                            best_next = txn
                            break
                    if best_next is None:
                        break
                    chain.append(best_next)
                    visited_in_chain.add(best_next["to"])
                    current_node = best_next["to"]
                    current_time = best_next["timestamp"]

                if len(chain) >= min_hops:
                    chains.append(chain)
                    for step in chain:
                        used_edges.add((step["from"], step["to"], str(step["timestamp"])))

        logger.info(
            "Transaction chains: found %d chains (min_hops=%d, window=%d min, shuffle=%s)",
            len(chains),
            min_hops,
            time_window_minutes,
            shuffle_starts,
        )
        return chains

    # ── Case-scoped ego-graph extraction ─────────────────────────────

    def get_ego_graph(
        self,
        account_id: str,
        radius: int = 2,
        time_window: tuple[Any, Any] | None = None,
    ) -> dict[str, Any]:
        """BFS ego-graph of `account_id` out to `radius` hops.

        Ported from `SQLiteAdapter.get_ego_graph`'s BFS shape (one hop at a
        time, gathering all transactions touching each newly-visited
        account) but walking `transactions_df` in memory instead of issuing
        one SQL query per hop. `time_window=(start, end)` — new relative to
        the archive's SQL version — restricts both the walk and the
        returned edges to that window, for case-scoped time-windowed
        extraction (ROADMAP decision 5)."""
        if account_id not in self._G:
            return {"nodes": [], "edges": [], "center": account_id}

        df = self.transactions_df
        if time_window is not None:
            start, end = time_window
            df = df[(df["timestamp"] >= start) & (df["timestamp"] <= end)]

        visited: set[str] = set()
        frontier: set[str] = {account_id}
        edges: list[dict[str, Any]] = []
        edge_seen: set[tuple] = set()

        for _ in range(radius):
            if not frontier:
                break
            next_frontier: set[str] = set()
            for acc in frontier:
                if acc in visited:
                    continue
                visited.add(acc)
                # Per-account fan-out cap, matching the archived
                # `SQLiteAdapter.get_ego_graph`'s `LIMIT 500` (no ORDER BY —
                # the archive returns whichever 500 rows SQLite yields
                # first, i.e. rowid/insertion order, not most-recent).
                # `.head(500)` on `df` here preserves the same insertion
                # order transactions_df was built in, so this matches that
                # behavior rather than inventing a "most recent" policy.
                touching = df[
                    (df["source_account"] == acc) | (df["dest_account"] == acc)
                ].head(_EGO_GRAPH_PER_ACCOUNT_LIMIT)
                for rec in touching.to_dict("records"):
                    fallback_key = (
                        rec["source_account"],
                        rec["dest_account"],
                        str(rec.get("timestamp")),
                        rec["amount"],
                    )
                    key = rec.get("txn_id") or fallback_key
                    if key in edge_seen:
                        continue
                    edge_seen.add(key)
                    edges.append(rec)
                    if rec["source_account"] == acc:
                        neighbor = rec["dest_account"]
                    else:
                        neighbor = rec["source_account"]
                    if neighbor not in visited:
                        next_frontier.add(neighbor)
            frontier = next_frontier

        all_accounts = visited | frontier
        nodes = self._account_nodes(all_accounts)
        return {"nodes": nodes, "edges": edges, "center": account_id}

    def _account_nodes(self, account_ids: set[str]) -> list[dict[str, Any]]:
        """Per-account dicts for `get_ego_graph`'s `nodes` — the full
        `accounts_df` row when available, else a minimal placeholder
        (mirrors the archive's `SQLiteAdapter.get_ego_graph` fallback for
        an account_id with no matching `accounts` row)."""
        if len(self.accounts_df) == 0 or "account_id" not in self.accounts_df.columns:
            return [{"account_id": a} for a in account_ids]
        indexed = self.accounts_df.set_index("account_id", drop=False)
        nodes = []
        for acc in account_ids:
            if acc in indexed.index:
                row = indexed.loc[acc]
                if isinstance(row, pd.DataFrame):  # duplicate account_id rows, defensive
                    row = row.iloc[0]
                nodes.append(row.to_dict())
            else:
                nodes.append({"account_id": acc})
        return nodes

    # ── Stats (diagnostic use, e.g. tests/verification) ──────────────

    def get_stats(self) -> dict[str, Any]:
        return {
            "num_nodes": self._G.number_of_nodes(),
            "num_edges": self._G.number_of_edges(),
            "num_components": nx.number_weakly_connected_components(self._G),
        }
