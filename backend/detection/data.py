"""
DB -> pandas DataFrame loaders for the detection layer.

Not part of the archive port (the archive read CSVs directly into
DataFrames at pipeline-run time) — new plumbing this phase needs to bridge
Phase 1's repository/DB layer to the `accounts_df`/`transactions_df` shape
every detector, `FeatureExtractor`, and `GraphStore` implementation expects.
Used by `scripts/train_detection_model.py` and the Phase 3 verification
pass; a later phase's real detection-pipeline orchestration (Phase 4) will
call these too rather than re-deriving its own loader.
"""
from __future__ import annotations

from collections.abc import Iterable

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models.reference import Account, Customer, Transaction

_SQLITE_IN_CLAUSE_CHUNK = 500  # stays well under SQLite's default host-parameter ceiling.


def _chunked(items: list[str], size: int) -> Iterable[list[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def load_transactions_df(session: Session) -> pd.DataFrame:
    """Every `transactions` row as a flat DataFrame with the column names
    every detector/GraphStore/FeatureExtractor expects (`source_account`,
    `dest_account`, `amount`, `timestamp`, `channel`, `is_laundering`,
    `from_bank`, `to_bank`)."""
    columns = [
        "txn_id", "source_account", "dest_account", "amount", "timestamp",
        "channel", "is_laundering", "from_bank", "to_bank",
    ]
    rows = session.scalars(select(Transaction)).all()
    records = [
        {
            "txn_id": t.txn_id,
            "source_account": t.source_account,
            "dest_account": t.dest_account,
            "amount": float(t.amount),
            "timestamp": t.timestamp,
            "channel": str(t.channel),
            "is_laundering": int(t.is_laundering),
            "from_bank": t.from_bank,
            "to_bank": t.to_bank,
        }
        for t in rows
    ]
    df = pd.DataFrame(records, columns=columns)
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


def load_accounts_df(session: Session, account_ids: Iterable[str] | None = None) -> pd.DataFrame:
    """`accounts` left-joined to `customers` (for `declared_annual_income`/
    `occupation`/`income_bracket`), flattened to one row per account_id —
    the shape `ProfileMismatchDetector`/`FeatureExtractor` expect.

    `account_ids=None` loads every account (fine for a small/demo DB, not
    recommended against the full pilot dataset); pass the set of account
    ids actually touched by `transactions_df` to scope the query instead
    (chunked to stay under SQLite's IN-clause host-parameter ceiling).
    """
    columns = [
        "account_id", "branch_city", "declared_annual_income", "occupation", "income_bracket",
    ]
    stmt = select(Account, Customer).outerjoin(
        Customer, Account.customer_id == Customer.customer_id
    )

    if account_ids is None:
        rows = session.execute(stmt).all()
    else:
        ids = sorted(set(account_ids))
        rows = []
        for chunk in _chunked(ids, _SQLITE_IN_CLAUSE_CHUNK):
            chunk_stmt = stmt.where(Account.account_id.in_(chunk))
            rows.extend(session.execute(chunk_stmt).all())

    records = []
    for account, customer in rows:
        income = None
        if customer is not None and customer.declared_annual_income is not None:
            income = float(customer.declared_annual_income)
        records.append({
            "account_id": account.account_id,
            "branch_city": account.branch_city,
            "declared_annual_income": income,
            "occupation": customer.occupation if customer is not None else None,
            "income_bracket": customer.income_bracket if customer is not None else None,
        })
    return pd.DataFrame(records, columns=columns)


def accounts_touched_by(transactions_df: pd.DataFrame) -> set[str]:
    """Every account_id appearing as a source or dest in `transactions_df`
    — the natural scoping set for `load_accounts_df`."""
    if transactions_df.empty:
        return set()
    return set(transactions_df["source_account"]) | set(transactions_df["dest_account"])
