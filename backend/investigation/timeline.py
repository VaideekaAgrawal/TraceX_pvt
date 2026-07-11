"""
Timeline reconstruction + timeline<->graph sync contract (ROADMAP Phase 6;
`SYSTEM_DEVELOPMENT_PLAN.md` §4.2: "Both data sources already exist
independently; the bidirectional UI sync is the missing piece"). Built
fresh from `TransactionRepository.list_for_account_in_window` -- NOT
adapted from the archive's `temporal_bfs`, which is documented-buggy
(BUG-001, relies on edge attributes the archive's own graph builder never
actually sets) and is explicitly not ported anywhere this phase.

**Sync contract**: every event's `txn_id` is the exact same key
`NetworkXGraphStore.get_ego_graph`'s edges (and therefore
`investigation.graph_filters.get_filtered_ego_graph`'s `edges` response)
carry as `edge["txn_id"]`. A frontend correlates a timeline entry with its
graph edge purely by that shared key -- no new join table, no synthetic
correlation id. (See `tests/investigation/test_timeline.py`'s explicit
overlap assertion against a graph-filters edge set built from the same
underlying seed data.)
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from db.repositories.reference import TransactionRepository
from investigation.case_graph import CASE_SCOPE_TRANSACTION_LIMIT


def build_timeline(
    session: Session,
    case_id: str,
    account_id: str,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict[str, Any]:
    """Chronological (ascending by `timestamp`) reconstruction of every
    transaction touching `account_id`, optionally windowed. Reuses
    `TransactionRepository.list_for_account_in_window` verbatim -- its
    `ORDER BY timestamp ASC` is exactly the composite-index-backed read
    pattern (`db/models/reference.py::Transaction`'s `(source_account,
    timestamp)`/`(dest_account, timestamp)` indexes) this needs, so no
    extra sort is applied here. `case_id` is accepted for signature
    consistency with this module's L2 siblings (`investigation.
    customer_profile.build_customer_profile`, `investigation.
    behavior_analysis.analyze`) even though this function's own computation
    is single-account and doesn't need case scope."""
    txns = TransactionRepository(session).list_for_account_in_window(
        account_id, start=start, end=end, limit=CASE_SCOPE_TRANSACTION_LIMIT
    )
    events = []
    for txn in txns:
        direction = "out" if txn.source_account == account_id else "in"
        counterparty = txn.dest_account if direction == "out" else txn.source_account
        events.append(
            {
                "txn_id": txn.txn_id,
                "timestamp": txn.timestamp,
                "direction": direction,
                "counterparty_account_id": counterparty,
                "amount": float(txn.amount),
                "channel": str(txn.channel),
                "is_laundering": bool(txn.is_laundering),
            }
        )
    return {"account_id": account_id, "events": events}
