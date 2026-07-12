"""
Complete Transaction Analysis (ROADMAP Phase 6; `SYSTEM_DEVELOPMENT_PLAN.md`
§4.2: "searchable, filterable, exportable transaction table (date, amount,
channel, branch, product, account, direction, type)"). Thin assembly layer
over `TransactionRepository.search_for_accounts`/`count_for_accounts` -- the
actual filtering lives in that repository method; this module's job is
enforcing the security invariant below and resolving branch/product
(account_type) metadata for the result page.

**Hard security invariant**: the `account_ids` passed to
`TransactionRepository.search_for_accounts`/`count_for_accounts` is ALWAYS
`CaseAccountRepository.list_account_ids_for_case(case_id)` (optionally
narrowed to `[account_id]`, and only if `account_id` is actually in that
set) -- never a caller-supplied free list. There is structurally no path
from this module's public `search()` to the repository with an unbounded
id set (see `tests/investigation/test_transaction_search.py`'s explicit
out-of-scope-account test).

**"Exportable"**: this JSON result set itself is the exportable artifact --
there is no server-side file/CSV generation endpoint here. No
upload/download infrastructure exists anywhere in this codebase to build a
CSV export on top of (confirmed via grep), so this is flagged as a real
gap, not silently built as an afterthought.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from sqlalchemy.orm import Session

from db.enums import Channel
from db.repositories.investigation import CaseAccountRepository
from db.repositories.reference import AccountRepository, TransactionRepository


def search(
    session: Session,
    case_id: str,
    *,
    account_id: str | None = None,
    case_account_ids: list[str] | None = None,
    min_amount: float | None = None,
    max_amount: float | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    channels: list[Channel] | None = None,
    direction: Literal["in", "out"] | None = None,
    txn_type: str | None = None,
    limit: int = 200,
    offset: int = 0,
    sort: str = "timestamp_desc",
) -> dict[str, Any]:
    """Filtered, paginated transaction search scoped to `case_id`'s linked
    accounts (or just `account_id`, if given and it's actually one of them
    -- callers are expected to have already 404'd an out-of-scope
    `account_id` via `foundation.auth.require_case_scoped_account`, but this
    function narrows to it defensively either way rather than trusting the
    caller silently). Returns `{"items", "total_count", "limit", "offset"}`.

    `case_account_ids`, if given, is trusted as `case_id`'s already-computed
    scoped account-id set -- e.g. from `foundation.auth.require_case_scoped_
    account_with_ids`, which an account-scoped caller already ran to
    validate `account_id` -- avoiding a second identical `CaseAccountRepository.
    list_account_ids_for_case` query in the same request (code-review
    finding, Phase 6). When omitted (the whole-case search route has no
    account dependency to reuse), computed here as before -- the defensive
    `account_id in case_account_ids` narrowing below still applies either
    way, so a caller passing a stale/wrong id list can't widen scope.
    """
    if case_account_ids is None:
        case_account_ids = CaseAccountRepository(session).list_account_ids_for_case(case_id)
    scoped_ids = set(case_account_ids)
    if account_id is not None:
        scope = [account_id] if account_id in scoped_ids else []
    else:
        scope = list(scoped_ids)

    txn_repo = TransactionRepository(session)
    matched = txn_repo.search_for_accounts(
        scope,
        min_amount=min_amount,
        max_amount=max_amount,
        start=start,
        end=end,
        channels=channels,
        direction=direction,
        txn_type=txn_type,
        limit=limit,
        offset=offset,
        sort=sort,
    )
    total_count = txn_repo.count_for_accounts(
        scope,
        min_amount=min_amount,
        max_amount=max_amount,
        start=start,
        end=end,
        channels=channels,
        direction=direction,
        txn_type=txn_type,
    )

    # Batched branch/product (account_type) resolution over the result
    # page's distinct accounts only -- not the whole scope.
    touched_ids = sorted({t.source_account for t in matched} | {t.dest_account for t in matched})
    accounts_by_id = {a.account_id: a for a in AccountRepository(session).list_by_ids(touched_ids)}

    items: list[dict[str, Any]] = []
    for txn in matched:
        source = accounts_by_id.get(txn.source_account)
        dest = accounts_by_id.get(txn.dest_account)
        items.append(
            {
                "txn_id": txn.txn_id,
                "timestamp": txn.timestamp,
                "amount": float(txn.amount),
                "channel": str(txn.channel),
                "txn_type": txn.txn_type,
                "source_account": txn.source_account,
                "dest_account": txn.dest_account,
                "source_branch_city": source.branch_city if source is not None else None,
                "dest_branch_city": dest.branch_city if dest is not None else None,
                "source_account_type": source.account_type if source is not None else None,
                "dest_account_type": dest.account_type if dest is not None else None,
                # Only meaningful relative to a single reference account --
                # `None` for a whole-case (multi-account) search, matching
                # `investigation.graph_filters`'s own "direction is only
                # well-defined relative to a center" reasoning.
                "direction": (
                    ("out" if txn.source_account == account_id else "in")
                    if account_id is not None
                    else None
                ),
                "is_laundering": bool(txn.is_laundering),
            }
        )

    return {"items": items, "total_count": total_count, "limit": limit, "offset": offset}
