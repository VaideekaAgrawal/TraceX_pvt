"""
Case-scoped graph assembly (ROADMAP Phase 5, decision 5: "case-scoped
ego-graphs, never the global graph"). Builds a `NetworkXGraphStore` from
exactly the accounts a case has linked (`case_accounts` -- the security
boundary, `db/repositories/investigation.py`), reusing `detection.data`'s
`load_accounts_df` and mirroring `load_transactions_df`'s column shape
rather than loading the whole `transactions`/`accounts` tables the way
`scripts/train_detection_model.py` does for a full pipeline run.

Also holds `shape_money_flow`, which reduces a raw ego-graph (as returned by
`NetworkXGraphStore.get_ego_graph`) to the L1 "10-second visual read":
aggregated (grouped-by-counterparty, summed) sources and beneficiaries
around one center account -- deliberately not a raw transaction dump (that's
`GET /transaction-summary`/`GET /transaction-purpose`'s job) and deliberately
not the N-hop analyst graph (`SYSTEM_DEVELOPMENT_PLAN.md` §4.1 vs §4.2 /
ROADMAP Phase 6).
"""
from __future__ import annotations

from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from db.repositories.reference import TransactionRepository
from detection.data import load_accounts_df
from detection.graph.networkx_store import NetworkXGraphStore

#: Column order mirrors `detection.data.load_transactions_df` exactly, so a
#: case-scoped `NetworkXGraphStore` built here behaves identically to the
#: full-DB one that module builds -- same detector/graph-primitive code path,
#: just scoped to fewer rows.
_TRANSACTION_COLUMNS = [
    "txn_id", "source_account", "dest_account", "amount", "timestamp",
    "channel", "is_laundering", "from_bank", "to_bank",
]

#: `TransactionRepository.list_for_account_in_window`'s own default
#: (`limit=500`, oldest-first) is tuned for a *general* caller with no
#: context on how many rows are reasonable -- but it silently keeps the
#: OLDEST 500 transactions and drops the most recent activity for any
#: account with more than that (code-review finding, Phase 5: every L1
#: triage caller that reads an account's transactions within a case --
#: `build_case_graph_store` below, the geo-risk/transaction-summary/
#: transaction-purpose routes, and the AI explanation's fact assembly --
#: inherited that default unintentionally). These callers are all
#: case-scoped (a case links a small, bounded number of accounts, not the
#: whole customer base -- `case_accounts` is the security boundary), so a
#: much higher cap than the general default is safe and cheap; import this
#: constant instead of leaving each call site to inherit `list_for_account_
#: in_window`'s bare default.
CASE_SCOPE_TRANSACTION_LIMIT = 10_000


def build_case_graph_store(session: Session, account_ids: list[str]) -> NetworkXGraphStore:
    """Compose every transaction touching any of `account_ids` (deduped by
    `txn_id` -- a transaction between two case-linked accounts would
    otherwise be pulled twice, once per side) into the `accounts_df`/
    `transactions_df` shape `NetworkXGraphStore` expects, then build it.

    Uses `TransactionRepository.list_for_account_in_window` with no window
    bound (every transaction the account has, up to `CASE_SCOPE_TRANSACTION_
    LIMIT` -- see that constant's docstring for why the repository's own
    default cap is wrong for this caller) -- this is a case-scoped graph,
    not a time-scoped one; callers that need a time window (e.g. a future
    timeline feature) apply it on top of the returned store's own
    `transactions_df`, not here.
    """
    txn_repo = TransactionRepository(session)
    seen_txn_ids: set[str] = set()
    records: list[dict[str, Any]] = []

    for account_id in account_ids:
        for txn in txn_repo.list_for_account_in_window(
            account_id, limit=CASE_SCOPE_TRANSACTION_LIMIT
        ):
            if txn.txn_id in seen_txn_ids:
                continue
            seen_txn_ids.add(txn.txn_id)
            records.append(
                {
                    "txn_id": txn.txn_id,
                    "source_account": txn.source_account,
                    "dest_account": txn.dest_account,
                    "amount": float(txn.amount),
                    "timestamp": txn.timestamp,
                    "channel": str(txn.channel),
                    "is_laundering": int(txn.is_laundering),
                    "from_bank": txn.from_bank,
                    "to_bank": txn.to_bank,
                }
            )

    transactions_df = pd.DataFrame(records, columns=_TRANSACTION_COLUMNS)
    if not transactions_df.empty:
        transactions_df["timestamp"] = pd.to_datetime(transactions_df["timestamp"])

    accounts_df = load_accounts_df(session, account_ids)
    return NetworkXGraphStore(accounts_df, transactions_df)


def shape_money_flow(ego: dict[str, Any], center: str) -> dict[str, Any]:
    """Split `ego["edges"]` (raw transaction-row dicts, as returned by
    `NetworkXGraphStore.get_ego_graph`) by direction relative to `center`,
    grouping by counterparty and summing amount/count per counterparty --
    "source X sent Rs.Y across N transactions", not N individual rows.

    A self-loop (`source_account == dest_account == center`) contributes to
    neither bucket -- it isn't money flowing to or from anyone else.
    Sorted descending by `total_amount` so the largest flows are first,
    matching a triage screen's "what matters most" reading order.
    """
    sources: dict[str, dict[str, Any]] = {}
    beneficiaries: dict[str, dict[str, Any]] = {}

    for edge in ego.get("edges", []):
        src = edge["source_account"]
        dst = edge["dest_account"]
        amount = float(edge["amount"])

        if src == dst:
            continue
        if dst == center:
            bucket = sources.setdefault(
                src, {"account_id": src, "total_amount": 0.0, "txn_count": 0}
            )
            bucket["total_amount"] += amount
            bucket["txn_count"] += 1
        elif src == center:
            bucket = beneficiaries.setdefault(
                dst, {"account_id": dst, "total_amount": 0.0, "txn_count": 0}
            )
            bucket["total_amount"] += amount
            bucket["txn_count"] += 1

    return {
        "center": center,
        "sources": sorted(sources.values(), key=lambda x: x["total_amount"], reverse=True),
        "beneficiaries": sorted(
            beneficiaries.values(), key=lambda x: x["total_amount"], reverse=True
        ),
    }
