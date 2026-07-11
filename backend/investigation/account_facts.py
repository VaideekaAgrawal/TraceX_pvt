"""
Shared transaction-stat assembly for one account -- ROADMAP Phase 5.

Ports the archive's inline stat block (`archive/fund-flow-tracker/api/
server.py:740-762`, the `/api/explain/account/{account_id}` handler) into a
standalone, DB-agnostic helper. Two real callers need the exact same numbers
now: the L1 "Transaction Summary" route (`api/routes/cases.py`) and
`orchestration.account_explanation`'s fact assembly for the AI explanation
prompt -- the archive left this as inline code in one handler, which is
exactly the kind of duplication this port avoids the second time a caller
shows up.

Pure function, no DB access: takes the already-loaded `list[Transaction]`
for one account (however the caller chose to window/limit it) and reduces it
to summary stats. Keeping this pure (no `Session` parameter) matches every
other `investigation/` module's read functions that operate on already-
fetched rows rather than re-querying.
"""
from __future__ import annotations

from typing import Any

from db.models.reference import Transaction


def transaction_stats(txns: list[Transaction], account_id: str) -> dict[str, Any]:
    """Reduce `txns` (assumed to already be the set touching `account_id`,
    e.g. from `TransactionRepository.list_for_account_in_window`) to:

      - `total_in`/`total_out`: sum of amounts where `account_id` is
        dest/source respectively,
      - `txn_count`: `len(txns)`,
      - `counterparty_count`: number of distinct accounts on the other side,
      - `channel_breakdown`: per-channel transaction counts.

    A transaction where `account_id` is both source and dest (a same-account
    "transfer", if the data ever contains one) contributes to neither
    `total_in` nor `total_out`'s counterparty set for that row's other side
    since there isn't one -- but it is still counted in `txn_count` and
    `channel_breakdown`, matching "every row in `txns` happened" rather than
    silently dropping a degenerate row.
    """
    total_in = 0.0
    total_out = 0.0
    counterparties: set[str] = set()
    channel_breakdown: dict[str, int] = {}

    for txn in txns:
        if txn.dest_account == account_id:
            total_in += float(txn.amount)
        if txn.source_account == account_id:
            total_out += float(txn.amount)

        if txn.source_account == account_id and txn.dest_account != account_id:
            counterparties.add(txn.dest_account)
        elif txn.dest_account == account_id and txn.source_account != account_id:
            counterparties.add(txn.source_account)

        channel = str(txn.channel)
        channel_breakdown[channel] = channel_breakdown.get(channel, 0) + 1

    return {
        "total_in": total_in,
        "total_out": total_out,
        "txn_count": len(txns),
        "counterparty_count": len(counterparties),
        "channel_breakdown": channel_breakdown,
    }
