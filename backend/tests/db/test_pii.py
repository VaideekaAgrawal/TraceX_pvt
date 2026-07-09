"""
Every `(table, column)` pair in `db.pii.PII_COLUMNS` must actually exist in
the live ORM schema — this is the redaction allow-map Phase 8 will consume,
so a stale/typo'd entry here would silently under- or over-redact later.
"""
from __future__ import annotations

from db.models import Base
from db.pii import PII_COLUMN_PAIRS, PII_COLUMNS, columns_for_table


def test_every_pii_column_exists_in_the_schema() -> None:
    for entry in PII_COLUMNS:
        assert entry.table in Base.metadata.tables, f"unknown table: {entry.table}"
        table = Base.metadata.tables[entry.table]
        assert entry.column in table.columns, f"{entry.table}.{entry.column} does not exist"


def test_no_duplicate_entries() -> None:
    assert len(PII_COLUMNS) == len(PII_COLUMN_PAIRS)


def test_customers_core_identity_columns_are_registered() -> None:
    for column in ("name", "pan", "aadhaar", "phone", "email", "address", "employer"):
        assert ("customers", column) in PII_COLUMN_PAIRS


def test_transactions_narration_is_registered() -> None:
    assert ("transactions", "narration") in PII_COLUMN_PAIRS


def test_columns_for_table_filters_correctly() -> None:
    customer_cols = {c.column for c in columns_for_table("customers")}
    assert customer_cols == {"name", "pan", "aadhaar", "phone", "email", "address", "employer"}
    assert columns_for_table("model_runs") == ()
