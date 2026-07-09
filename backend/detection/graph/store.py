"""
`GraphStore` — the abstract graph-engine interface pattern detectors, the
Rule Engine, feature extraction, and role classification consume.

Scope (ROADMAP Phase 3, decision 5 — "case-scoped ego-graphs, never the
global graph, is the only way graphs are built"): this interface carries
only what those consumers actually need —

  - `get_ego_graph`      — case-scoped ego-graph extraction (N-hop,
                            time-windowable). BFS shape ported from
                            `archive/fund-flow-tracker/infrastructure/
                            database.py::SQLiteAdapter.get_ego_graph`,
                            reworked to walk an in-memory graph instead of
                            issuing one SQL query per hop.
  - `compute_centrality` — the pandas-approximation pagerank/betweenness
                            (`archive ...services/graph/engine.py`), ported
                            as-is — not "fixed" to real NetworkX algorithms,
                            since that would silently change every
                            detector/ensemble score that reads it with no
                            re-evaluation.
  - `detect_cycles`      — feeds the round-trip detector + the Rule Engine's
                            `cycle` primitive.
  - `get_transaction_chains` — feeds the layering detector + the Rule
                            Engine's `chain` primitive.

Explicitly NOT ported (see `archive/SALVAGE.md` / ROADMAP Phase 3 plan):
`temporal_bfs`/`get_fund_trail` (relies on edge attributes `_build()` never
actually sets in the archive — a latent bug, and case-scoped ego-graph
extraction replaces its role), `random_walk_with_restart`,
`get_validation_subgraph`/`get_renderable_subgraph` (old-frontend-dialog-
specific, not detector inputs), `rank_suspicious_paths` (old-frontend-only).

`graph` property: not one of the four primitives above, but required by two
internal detection-layer consumers that sit alongside this interface rather
than behind it — `FeatureExtractor` (28-dim feature vector; needs raw
in/out-degree per node) and `RoleClassifier` (needs raw in/out-edge amount
sums per node). Re-deriving that from the four primitives above would mean
either adding narrow one-off methods that just re-expose what NetworkX
already gives for free in-process, or looping per-account queries — neither
is better than exposing the graph itself to these two same-layer callers.
Judgment call, documented here: a future Neo4j-backed `GraphStore` would
need to materialize this (e.g. into a throwaway NetworkX graph) to satisfy
it — acceptable since decision 5 keeps this phase strictly NetworkX-backed
(Neo4j is interface-only, not implemented).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import networkx as nx


class GraphStore(ABC):
    @property
    @abstractmethod
    def graph(self) -> nx.MultiDiGraph:
        """The underlying graph — see module docstring for why this is
        exposed alongside (not instead of) the four primitives below."""

    @abstractmethod
    def get_ego_graph(
        self,
        account_id: str,
        radius: int = 2,
        time_window: tuple[Any, Any] | None = None,
    ) -> dict[str, Any]:
        """BFS ego-graph of `account_id` out to `radius` hops.

        Returns `{"nodes": [...], "edges": [...], "center": account_id}`
        (the shape `SQLiteAdapter.get_ego_graph` already proved out) — nodes
        are per-account dicts (account_id plus whatever columns the backing
        `accounts_df` carries), edges are transaction-row dicts. Optional
        `time_window=(start, end)` restricts which transactions are walked/
        returned, for case-scoped time-windowed extraction.
        """

    @abstractmethod
    def compute_centrality(self) -> dict[str, dict[str, float]]:
        """`{"pagerank": {account_id: score}, "betweenness": {account_id: score}}`."""

    @abstractmethod
    def detect_cycles(self, max_length: int = 12, max_cycles: int = 2000) -> list[list[str]]:
        """Bounded cycle detection — each cycle is a list of account_ids."""

    @abstractmethod
    def get_transaction_chains(
        self,
        min_hops: int = 3,
        time_window_minutes: int = 120,
        max_chains: int = 500,
        shuffle_starts: bool = False,
    ) -> list[list[dict[str, Any]]]:
        """Temporal transaction chains — each chain is a list of hop dicts
        (`from`, `to`, `amount`, `timestamp`, `channel`)."""
