"""
Graph Service — owns the transaction graph lifecycle.

Responsibilities:
- Build graph from normalised transactions
- Provide traversal, centrality, and subgraph APIs
- Track graph parity (CP-04)
"""
import logging
from typing import Any, Dict, List, Optional

import pandas as pd

from infrastructure.event_bus import bus, Topics
from infrastructure.health import health
from services.graph.engine import TransactionGraph

logger = logging.getLogger(__name__)

_SERVICE = "graph"


class GraphService:
    """Manages the TransactionGraph lifecycle and exposes query APIs."""

    def __init__(self):
        self._graph: Optional[TransactionGraph] = None
        health.register_service(_SERVICE)

    @property
    def graph(self) -> TransactionGraph:
        if self._graph is None:
            raise RuntimeError("Graph not built — call build() first")
        return self._graph

    @property
    def is_ready(self) -> bool:
        return self._graph is not None

    def build(self, accounts_df: pd.DataFrame, transactions_df: pd.DataFrame):
        """Build the transaction graph and update health counters."""
        self._graph = TransactionGraph(accounts_df, transactions_df)

        stats = self._graph.get_stats()
        health.set_counter("graph_nodes", stats["num_nodes"])
        health.set_counter("graph_edges", stats["num_edges"])
        health.heartbeat(_SERVICE, "healthy")

        # CP-04: graph parity
        expected_accounts = len(
            set(transactions_df["source_account"]) | set(transactions_df["dest_account"])
        )
        health.cp04_graph_parity(
            expected_nodes=expected_accounts,
            actual_nodes=stats["num_nodes"],
            expected_edges=len(transactions_df),
            actual_edges=stats["num_edges"],
        )

        bus.publish(Topics.GRAPH_UPDATED, stats, source_service=_SERVICE)
        logger.info("Graph built: %s", stats)

    def get_fund_trail(self, account_id: str, direction: str = "both",
                       max_depth: int = 5) -> Dict[str, Any]:
        return self.graph.get_fund_trail(account_id, direction, max_depth)

    def get_ego_subgraph(self, account_id: str, radius: int = 2):
        return self.graph.get_ego_subgraph(account_id, radius)

    def get_renderable_subgraph(self, risk_scores: Dict[str, float], max_nodes: int = 100):
        return self.graph.get_renderable_subgraph(risk_scores, max_nodes)

    def detect_cycles(self, max_length: int = 5, max_cycles: int = 200) -> List[List[str]]:
        return self.graph.detect_cycles(max_length, max_cycles)

    def get_transaction_chains(self, min_hops: int = 3, time_window_minutes: int = 30):
        return self.graph.get_transaction_chains(min_hops, time_window_minutes)

    def random_walk(self, start: str, restart_prob: float = 0.15, num_steps: int = 5000):
        return self.graph.random_walk_with_restart(start, restart_prob, num_steps)

    def compute_centrality(self):
        return self.graph.compute_centrality()

    def get_stats(self) -> Dict[str, Any]:
        return self.graph.get_stats()

    def rank_suspicious_paths(self, risk_scores: Dict[str, float], top_n: int = 10):
        return self.graph.rank_suspicious_paths(risk_scores, top_n)
