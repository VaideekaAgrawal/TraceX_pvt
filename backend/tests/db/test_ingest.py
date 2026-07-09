"""
Tests for `db.ingest` — the Phase 1 ingest path for the two real seed CSVs
(`docs/DATA_SCHEMA.md` §3.1/§3.5/§5, ROADMAP Phase 1 "Seed/ingest path").

Covers: parser unit tests (including the real unmapped-`Payment Format`
edge case), a validation-rejection path that never touches the domain
tables, row/file-level idempotency, and an end-to-end run of the two real
files at `data/` against a temp SQLite DB with sane row-count assertions.
"""
from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from db import ingest as ing
from db.enums import Channel, EntityType
from db.repositories import (
    AccountRepository,
    CustomerRepository,
    IngestionLogRepository,
    TransactionRepository,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
REAL_ACCOUNTS_CSV = REPO_ROOT / "data" / "HI-Small_accounts.csv"
REAL_TRANSACTIONS_CSV = REPO_ROOT / "data" / "tracex_test_day1.csv"

ACCOUNTS_HEADER = ["Bank Name", "Bank ID", "Account Number", "Entity ID", "Entity Name"]
TXN_HEADER = [
    "Timestamp",
    "From Bank",
    "Account",
    "To Bank",
    "Account.1",
    "Amount Received",
    "Receiving Currency",
    "Amount Paid",
    "Payment Currency",
    "Payment Format",
    "Is Laundering",
    "Source_Occupation",
    "Source_Declared_Income",
    "Dest_Occupation",
    "Dest_Declared_Income",
]


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# Parser unit tests
# ---------------------------------------------------------------------------
def test_parse_timestamp() -> None:
    assert ing.parse_timestamp("2026/05/28 05:12") == datetime(2026, 5, 28, 5, 12, tzinfo=UTC)


@pytest.mark.parametrize(
    ("payment_format", "expected"),
    [
        ("Wire", Channel.RTGS),
        ("ACH", Channel.NEFT),
        ("Cheque", Channel.cheque),
        ("Cash", Channel.branch_cash),
    ],
)
def test_map_channel_known_formats(payment_format: str, expected: Channel) -> None:
    assert ing.map_channel(payment_format) == expected


@pytest.mark.parametrize(
    "payment_format", ["Credit Card", "Reinvestment", "Bitcoin", "Something Else"]
)
def test_map_channel_unmapped_format_falls_back_to_unknown(payment_format: str) -> None:
    """The real edge case: `data/tracex_test_day1.csv` genuinely contains
    both 'Credit Card' and 'Reinvestment' rows, neither of which has a
    sensible `Channel` equivalent (see `PAYMENT_FORMAT_TO_CHANNEL` doc
    comment in `db/ingest.py`)."""
    assert ing.map_channel(payment_format) == Channel.unknown


def test_infer_entity_type() -> None:
    assert ing.infer_entity_type("Individual #123") == EntityType.INDIVIDUAL
    assert ing.infer_entity_type("Corporation #4") == EntityType.BUSINESS
    assert ing.infer_entity_type("Sole Proprietorship #50438") == EntityType.BUSINESS
    assert ing.infer_entity_type("Partnership #35397") == EntityType.BUSINESS
    assert ing.infer_entity_type("Country #1") == EntityType.BUSINESS


def test_normalize_currency() -> None:
    assert ing.normalize_currency("Indian Rupee") == "INR"
    assert ing.normalize_currency("US Dollar") == "USD"
    assert ing.normalize_currency("Euro") == "EUR"
    assert ing.normalize_currency("UK Pound") == "GBP"
    assert ing.normalize_currency("Bitcoin") == "BTC"
    assert ing.normalize_currency("") == "INR"
    assert ing.normalize_currency("Some Unknown Currency") == "Some Unknown Currency"


def test_make_txn_id_deterministic_and_sensitive_to_fields() -> None:
    row = {
        "Timestamp": "2026/05/28 05:12",
        "From Bank": "KOTAK",
        "Account": "PMFRAUD01",
        "To Bank": "HDFC",
        "Account.1": "PMFRAUDDEST01",
        "Amount Received": "7500000.00",
        "Receiving Currency": "Indian Rupee",
        "Amount Paid": "7500000.00",
        "Payment Currency": "Indian Rupee",
        "Payment Format": "Wire",
    }
    id1 = ing.make_txn_id(row)
    id2 = ing.make_txn_id(dict(row))
    assert id1 == id2  # re-ingesting the same row is idempotent at the row level
    assert id1.startswith("TXN-")

    changed = dict(row, Amount_Paid="1.00")
    changed["Amount Paid"] = "1.00"
    assert ing.make_txn_id(changed) != id1


def test_make_txn_id_occurrence_disambiguates_same_minute_duplicates() -> None:
    """Regression: two distinct legitimate transactions with identical
    (timestamp-minute, accounts, amount, currency, payment format) must NOT
    collide onto the same txn_id and silently drop the second one — exactly
    the repeated-small-transfer/structuring pattern this platform exists to
    detect."""
    row = {
        "Timestamp": "2026/05/28 05:12",
        "From Bank": "KOTAK",
        "Account": "PMFRAUD01",
        "To Bank": "HDFC",
        "Account.1": "PMFRAUDDEST01",
        "Amount Received": "1000.00",
        "Receiving Currency": "Indian Rupee",
        "Amount Paid": "1000.00",
        "Payment Currency": "Indian Rupee",
        "Payment Format": "Wire",
    }
    id_occurrence_0 = ing.make_txn_id(row, 0)
    id_occurrence_1 = ing.make_txn_id(row, 1)
    assert id_occurrence_0 != id_occurrence_1

    # Deterministic: re-hashing the same (row, occurrence) pair reproduces
    # the same id, so re-ingesting the same file (same rows in the same
    # order) is still idempotent.
    assert ing.make_txn_id(dict(row), 1) == id_occurrence_1


# ---------------------------------------------------------------------------
# Validation rejection — must reject before touching the DB
# ---------------------------------------------------------------------------
def test_validate_upload_rejects_wrong_extension(tmp_path: Path) -> None:
    bad = tmp_path / "accounts.txt"
    bad.write_text("Bank Name,Bank ID,Account Number,Entity ID,Entity Name\n")
    result = ing.validate_upload(bad, required_columns=ing.ACCOUNTS_REQUIRED_COLUMNS)
    assert not result.ok
    assert any("extension" in e for e in result.errors)


def test_validate_upload_rejects_empty_file(tmp_path: Path) -> None:
    empty = tmp_path / "empty.csv"
    empty.write_text("")
    result = ing.validate_upload(empty, required_columns=ing.ACCOUNTS_REQUIRED_COLUMNS)
    assert not result.ok
    assert any("empty" in e for e in result.errors)


def test_validate_upload_rejects_missing_columns(tmp_path: Path) -> None:
    malformed = tmp_path / "accounts.csv"
    _write_csv(malformed, ["Bank Name", "Account Number"], [["Bank", "A1"]])
    result = ing.validate_upload(malformed, required_columns=ing.ACCOUNTS_REQUIRED_COLUMNS)
    assert not result.ok
    assert any("missing required columns" in e for e in result.errors)


def test_validate_upload_rejects_oversized_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ing, "MAX_FILE_SIZE_BYTES", 10)
    oversized = tmp_path / "accounts.csv"
    _write_csv(oversized, ACCOUNTS_HEADER, [["Bank", "1", "A1", "C1", "Individual #1"]])
    result = ing.validate_upload(oversized, required_columns=ing.ACCOUNTS_REQUIRED_COLUMNS)
    assert not result.ok
    assert any("too large" in e for e in result.errors)


def test_ingest_rejects_malformed_file_without_touching_db(
    session: Session, tmp_path: Path
) -> None:
    malformed = tmp_path / "accounts.csv"
    _write_csv(malformed, ["Bank Name", "Account Number"], [["Bank", "A1"]])

    outcome = ing.ingest_accounts_csv(session, malformed)
    session.commit()

    assert outcome.status == ing.STATUS_REJECTED
    assert outcome.errors

    assert CustomerRepository(session).list(limit=10) == []
    assert AccountRepository(session).list(limit=10) == []
    log = IngestionLogRepository(session).get(outcome.file_hash)
    assert log is not None
    assert log.status == ing.STATUS_REJECTED


def test_ingest_rejects_oversized_transactions_file(
    session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ing, "MAX_FILE_SIZE_BYTES", 10)
    txns = tmp_path / "txns.csv"
    _write_csv(
        txns,
        TXN_HEADER,
        [
            [
                "2026/05/28 05:12",
                "KOTAK",
                "A1",
                "HDFC",
                "A2",
                "100.00",
                "Indian Rupee",
                "100.00",
                "Indian Rupee",
                "Wire",
                "0",
                "Salaried",
                "10000",
                "Salaried",
                "10000",
            ]
        ],
    )
    outcome = ing.ingest_transactions_csv(session, txns)
    session.commit()

    assert outcome.status == ing.STATUS_REJECTED
    assert TransactionRepository(session).list(limit=10) == []
    assert AccountRepository(session).list(limit=10) == []


def test_ingest_transactions_csv_skips_ragged_row_without_aborting(
    session: Session, tmp_path: Path
) -> None:
    """A short/ragged data row (fewer fields than the header) makes
    `csv.DictReader` fill the missing trailing column(s) with `None` — this
    must be skipped (logged, counted), not crash the whole file with an
    unhandled `AttributeError` from `.strip()` on `None`."""
    txns = tmp_path / "txns.csv"
    good_row = [
        "2026/05/28 05:12",
        "KOTAK",
        "A1",
        "HDFC",
        "A2",
        "100.00",
        "Indian Rupee",
        "100.00",
        "Indian Rupee",
        "Wire",
        "0",
        "Salaried",
        "10000",
        "Salaried",
        "10000",
    ]
    # Ragged row: missing the trailing Dest_Occupation/Dest_Declared_Income
    # fields entirely (short row -> DictReader fills them with None).
    ragged_row = ["2026/05/28 05:13", "KOTAK", "A3", "HDFC", "A4"]
    _write_csv(txns, TXN_HEADER, [good_row, ragged_row])

    outcome = ing.ingest_transactions_csv(session, txns)
    session.commit()

    assert outcome.status == ing.STATUS_SUCCESS
    assert outcome.num_transactions == 1
    assert outcome.num_rows_skipped == 1
    # The malformed row's accounts were never created.
    assert AccountRepository(session).get("A3") is None
    assert AccountRepository(session).get("A4") is None


def test_ingest_accounts_csv_skips_ragged_row_without_aborting(
    session: Session, tmp_path: Path
) -> None:
    accounts = tmp_path / "accounts.csv"
    good_row = ["KOTAK", "1", "A1", "C1", "Individual #1"]
    ragged_row = ["HDFC", "2"]  # missing Account Number/Entity ID/Entity Name
    _write_csv(accounts, ACCOUNTS_HEADER, [good_row, ragged_row])

    outcome = ing.ingest_accounts_csv(session, accounts)
    session.commit()

    assert outcome.status == ing.STATUS_SUCCESS
    assert outcome.num_accounts == 1
    assert outcome.num_rows_skipped == 1


def test_run_full_ingest_aborts_transactions_when_accounts_rejected(
    session: Session, tmp_path: Path
) -> None:
    """If the accounts CSV is rejected, transactions must not be ingested
    against a missing/incomplete accounts table — regression test for a bug
    where `run_full_ingest` proceeded unconditionally and `main()` reported
    success (exit 0) even though no customers/accounts were ever loaded."""
    bad_accounts = tmp_path / "accounts.txt"  # wrong extension -> rejected
    bad_accounts.write_text("Bank Name,Bank ID,Account Number,Entity ID,Entity Name\n")

    txns = tmp_path / "txns.csv"
    _write_csv(
        txns,
        TXN_HEADER,
        [
            [
                "2026/05/28 05:12",
                "KOTAK",
                "A1",
                "HDFC",
                "A2",
                "100.00",
                "Indian Rupee",
                "100.00",
                "Indian Rupee",
                "Wire",
                "0",
                "Salaried",
                "10000",
                "Salaried",
                "10000",
            ]
        ],
    )

    accounts_outcome, transactions_outcome = ing.run_full_ingest(
        session, accounts_path=bad_accounts, transactions_path=txns
    )
    session.commit()

    assert accounts_outcome.status == ing.STATUS_REJECTED
    assert transactions_outcome.status == ing.STATUS_ABORTED
    assert TransactionRepository(session).list(limit=10) == []
    assert AccountRepository(session).list(limit=10) == []


def test_main_exits_nonzero_when_accounts_ingest_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad_accounts = tmp_path / "accounts.txt"
    bad_accounts.write_text("Bank Name,Bank ID,Account Number,Entity ID,Entity Name\n")
    txns = tmp_path / "txns.csv"
    _write_csv(txns, TXN_HEADER, [])

    monkeypatch.setattr(
        "sys.argv",
        ["ingest", "--accounts-csv", str(bad_accounts), "--transactions-csv", str(txns)],
    )
    with pytest.raises(SystemExit) as exc_info:
        ing.main()
    assert exc_info.value.code == 1


def test_transactions_enrichment_writes_once_per_customer_not_once_per_row(
    session: Session, tmp_path: Path
) -> None:
    """Regression: an account referenced by many transaction rows must only
    trigger one enrichment UPDATE (+ one audit_log row) for its linked
    customer, not one per row."""
    accounts = tmp_path / "accounts.csv"
    _write_csv(accounts, ACCOUNTS_HEADER, [["KOTAK", "1", "A1", "C1", "Individual #1"]])
    ing.ingest_accounts_csv(session, accounts)
    session.commit()

    def row(minute: int) -> list[str]:
        return [
            f"2026/05/28 05:{minute:02d}",
            "KOTAK",
            "A1",
            "HDFC",
            "A2",
            "100.00",
            "Indian Rupee",
            "100.00",
            "Indian Rupee",
            "Wire",
            "0",
            "Salaried",
            "500000",
            "Retired",
            "200000",
        ]

    txns = tmp_path / "txns.csv"
    _write_csv(txns, TXN_HEADER, [row(12), row(13), row(14)])

    from db.repositories._audit import verify_chain
    from db.repositories.platform import AuditLogRepository

    audit_repo = AuditLogRepository(session)
    before = len(audit_repo.list(limit=10_000))

    ing.ingest_transactions_csv(session, txns)
    session.commit()

    after = len(audit_repo.list(limit=10_000))
    # 2 ingestion_log writes (create IN_PROGRESS, update SUCCESS) + 3
    # transactions + 1 new account (A2, minted once then reused across all 3
    # rows via known_accounts) + exactly 1 customer-enrichment update for C1
    # (not 3 — that's the bug this test guards against).
    assert after - before == 2 + 3 + 1 + 1
    assert verify_chain(session)


# ---------------------------------------------------------------------------
# Idempotency — file-level (ingestion_log) and row-level (upsert / txn hash)
# ---------------------------------------------------------------------------
def test_ingest_accounts_csv_is_idempotent(session: Session, tmp_path: Path) -> None:
    accounts = tmp_path / "accounts.csv"
    _write_csv(
        accounts,
        ACCOUNTS_HEADER,
        [
            ["KOTAK", "1", "A1", "C1", "Individual #1"],
            ["HDFC", "2", "A2", "C1", "Individual #1"],  # same entity, 2nd account
            ["SBI", "3", "A3", "C2", "Corporation #1"],
        ],
    )

    first = ing.ingest_accounts_csv(session, accounts)
    session.commit()
    assert first.status == ing.STATUS_SUCCESS
    assert first.num_customers == 2
    assert first.num_accounts == 3
    assert len(CustomerRepository(session).list(limit=100)) == 2
    assert len(AccountRepository(session).list(limit=100)) == 3

    second = ing.ingest_accounts_csv(session, accounts)
    session.commit()
    assert second.status == ing.STATUS_SKIPPED
    # no duplicate rows created
    assert len(CustomerRepository(session).list(limit=100)) == 2
    assert len(AccountRepository(session).list(limit=100)) == 3
    assert len(IngestionLogRepository(session).list(limit=10)) == 1


def test_ingest_transactions_csv_is_idempotent(session: Session, tmp_path: Path) -> None:
    txns = tmp_path / "txns.csv"
    row = [
        "2026/05/28 05:12",
        "KOTAK",
        "A1",
        "HDFC",
        "A2",
        "100.00",
        "Indian Rupee",
        "100.00",
        "Indian Rupee",
        "Wire",
        "0",
        "Salaried",
        "10000",
        "Salaried",
        "10000",
    ]
    _write_csv(txns, TXN_HEADER, [row])

    first = ing.ingest_transactions_csv(session, txns)
    session.commit()
    assert first.status == ing.STATUS_SUCCESS
    assert first.num_transactions == 1
    assert len(TransactionRepository(session).list(limit=10)) == 1

    second = ing.ingest_transactions_csv(session, txns)
    session.commit()
    assert second.status == ing.STATUS_SKIPPED
    assert len(TransactionRepository(session).list(limit=10)) == 1
    assert len(IngestionLogRepository(session).list(limit=10)) == 1


def test_transactions_enrich_customer_when_account_already_linked(
    session: Session, tmp_path: Path
) -> None:
    """Synthetic-overlap test for `_maybe_enrich_customer`: on the two real
    files there is zero account-id overlap (documented in `db/ingest.py`),
    so this path is otherwise unexercised by the end-to-end test below."""
    accounts = tmp_path / "accounts.csv"
    _write_csv(accounts, ACCOUNTS_HEADER, [["KOTAK", "1", "A1", "C1", "Individual #1"]])
    ing.ingest_accounts_csv(session, accounts)
    session.commit()

    txns = tmp_path / "txns.csv"
    _write_csv(
        txns,
        TXN_HEADER,
        [
            [
                "2026/05/28 05:12",
                "KOTAK",
                "A1",
                "HDFC",
                "A2",
                "100.00",
                "Indian Rupee",
                "100.00",
                "Indian Rupee",
                "Wire",
                "0",
                "Salaried",
                "500000",
                "Retired",
                "200000",
            ]
        ],
    )
    ing.ingest_transactions_csv(session, txns)
    session.commit()

    customer = CustomerRepository(session).get("C1")
    assert customer is not None
    assert customer.occupation == "Salaried"
    assert customer.declared_annual_income is not None
    assert float(customer.declared_annual_income) == 500000.0

    # A2 was minted fresh by the transactions ingest -> customer_id NULL ->
    # nothing to enrich.
    a2 = AccountRepository(session).get("A2")
    assert a2 is not None
    assert a2.customer_id is None


# ---------------------------------------------------------------------------
# End-to-end: the two real CSVs, full path, temp SQLite DB
# ---------------------------------------------------------------------------
@pytest.mark.skipif(
    not (REAL_ACCOUNTS_CSV.exists() and REAL_TRANSACTIONS_CSV.exists()),
    reason="real seed CSVs not present at data/",
)
def test_end_to_end_ingest_real_csvs(session: Session) -> None:
    accounts_outcome, txns_outcome = ing.run_full_ingest(
        session,
        accounts_path=REAL_ACCOUNTS_CSV,
        transactions_path=REAL_TRANSACTIONS_CSV,
        actor_id="test-e2e",
    )

    assert accounts_outcome.status == ing.STATUS_SUCCESS
    assert txns_outcome.status == ing.STATUS_SUCCESS

    # Real HI-Small_accounts.csv: 518581 rows, 166207 unique entities,
    # 518573 unique account numbers (verified against the actual file).
    assert accounts_outcome.num_customers == 166207
    assert accounts_outcome.num_accounts == 518573

    # Real tracex_test_day1.csv: 8002 data rows, all with distinct
    # deterministic txn_ids, 316 unique accounts referenced.
    assert txns_outcome.num_transactions == 8002
    assert txns_outcome.num_accounts == 316  # zero overlap with accounts.csv

    session.commit()
    assert len(CustomerRepository(session).list(limit=1000)) > 0
    assert len(IngestionLogRepository(session).list(limit=10)) == 2

    # Re-running is a no-op (file-level idempotency for both files).
    accounts_again, txns_again = ing.run_full_ingest(
        session,
        accounts_path=REAL_ACCOUNTS_CSV,
        transactions_path=REAL_TRANSACTIONS_CSV,
    )
    assert accounts_again.status == ing.STATUS_SKIPPED
    assert txns_again.status == ing.STATUS_SKIPPED
    assert len(IngestionLogRepository(session).list(limit=10)) == 2
