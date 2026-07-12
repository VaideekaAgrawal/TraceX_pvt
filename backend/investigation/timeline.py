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

from db.repositories.investigation import CaseAccountRepository
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
    `TransactionRepository.list_for_account_in_window` with
    `most_recent=True` (code-review finding, Phase 6: the default
    ascending-then-limit order silently kept the OLDEST transactions for an
    account exceeding `CASE_SCOPE_TRANSACTION_LIMIT`, so a caller assuming
    the returned window reaches "now" would be wrong; `most_recent=True`
    fetches the newest `limit` rows and reverses them back to ascending
    order, so no extra sort is applied here beyond that).

    Validates `account_id` is in `case_id`'s scope (defense-in-depth --
    the real boundary check is the route dependency, `foundation.auth.
    require_case_scoped_account`; this repeats it because this function is
    also directly unit-testable/callable without going through HTTP,
    matching `orchestration.pattern_explanation._assemble_facts`'s
    precedent) -- raises `ValueError` otherwise."""
    case_account_ids = set(CaseAccountRepository(session).list_account_ids_for_case(case_id))
    if account_id not in case_account_ids:
        raise ValueError(f"account {account_id!r} is not in case {case_id!r}'s scope")

    txns = TransactionRepository(session).list_for_account_in_window(
        account_id, start=start, end=end, limit=CASE_SCOPE_TRANSACTION_LIMIT, most_recent=True
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
