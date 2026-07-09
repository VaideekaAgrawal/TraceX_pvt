"""
Real ingest path for the two source CSVs Phase 1 seeds the pilot DB from
(`docs/DATA_SCHEMA.md` §3.1, §3.5, §5 build-order step 1; ROADMAP Phase 1
"Seed/ingest path for the synthetic dataset with upload validation"):

    data/HI-Small_accounts.csv    -> customers + accounts (KYC-ish registry)
    data/tracex_test_day1.csv     -> transactions (+ customer occupation/
                                      income enrichment where the account
                                      already has a linked customer)

No API/auth layer exists yet (Phase 2+), so the entry point here is a plain
callable + CLI (`python -m db.ingest`), not an HTTP endpoint. A later upload
endpoint wraps `ingest_accounts_csv`/`ingest_transactions_csv` directly, which
is why validation below treats these local files exactly as if they had
arrived via upload (`SYSTEM_DEVELOPMENT_PLAN.md` "Upload validation" /
`docs/cross_questions.md` Q21: file-size limit, extension/MIME check,
row-count sanity check) rather than trusting them because they're local.

Ordering judgment call (`docs/DATA_SCHEMA.md` §4 decision 2, `accounts.
customer_id` nullable): the accounts CSV is ingested first because it is the
authoritative KYC-ish source (customer_id set on every account it creates).
The transactions CSV is ingested second; any `source_account`/`dest_account`
it references that isn't already in `accounts` gets created as a minimal
account row with `customer_id=NULL` — exactly the case the schema doc's own
nullable-FK reasoning anticipates ("some txn accounts have no KYC record").
In the actual two files at repo root there is **zero account-id overlap**
between them (verified: `HI-Small_accounts.csv` is the full IBM HI-Small
account registry, `tracex_test_day1.csv` is a small hand-built demo/test
transaction set using different, txn-scenario-named account ids like
`PMFRAUD01`) — so on this real data every transaction account ends up
customer_id=NULL and the "enrich customers.occupation/declared_annual_income"
step (below) never finds a linked customer to enrich. The enrichment code
path is still implemented (and unit-tested with synthetic overlapping data)
for correctness against future/other data where the two id spaces do
overlap; it is a documented no-op on today's real files, not a bug.

Idempotency has two layers:
  - File-level: `ingestion_log.file_hash` (PK) — a file already logged with
    status "success" is not re-processed at all (`IngestOutcome.status ==
    "skipped"`, no second `ingestion_log` row: the primary key forbids one
    and the existing row already documents "already ingested", so a repeat
    call intentionally does not write a second row for the same hash).
  - Row-level: `transactions.txn_id` is a deterministic hash of a stable
    field tuple (see `make_txn_id`) and `customers`/`accounts` are upserted
    by business key (`get()` then conditional `create()`) — so re-ingesting
    a file that overlaps rows already present (e.g. a corrected re-upload)
    does not duplicate rows even outside the file-hash fast path.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import logging
import mimetypes
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from db.enums import ActorType, Channel, EntityType, RiskLevel
from db.repositories import (
    AccountRepository,
    CustomerRepository,
    IngestionLogRepository,
    TransactionRepository,
)
from db.session import SessionLocal

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ACCOUNTS_CSV = _REPO_ROOT / "data" / "HI-Small_accounts.csv"
DEFAULT_TRANSACTIONS_CSV = _REPO_ROOT / "data" / "tracex_test_day1.csv"

# ---------------------------------------------------------------------------
# Upload validation (SYSTEM_DEVELOPMENT_PLAN.md "Upload validation" /
# docs/cross_questions.md Q21: file-size limit, MIME/extension check,
# row-count sanity check). These are local files, not HTTP uploads, but a
# later API endpoint wraps this same ingest function directly, so validation
# is applied exactly as if the file arrived over the wire.
# ---------------------------------------------------------------------------
MAX_FILE_SIZE_BYTES = 200 * 1024 * 1024  # 200MB — comfortably above the real
# ~34MB accounts.csv while still bounding a pathological/malicious upload.
ALLOWED_EXTENSIONS = frozenset({".csv"})
# mimetypes has no magic-byte sniffing without an extra dependency; for a
# same-machine ingest of local files the extension is the reliable signal.
# The MIME check is best-effort defense-in-depth on top of it — `None` (no
# guess) and `text/plain` (a bare CSV commonly guesses as this on some
# platforms) are accepted alongside the canonical CSV MIME types so a
# legitimate file is never rejected purely because `mimetypes` guessed
# nothing or guessed conservatively.
ALLOWED_MIME_TYPES = frozenset({"text/csv", "application/vnd.ms-excel", "text/plain", None})
MAX_ROW_COUNT = 5_000_000  # sanity ceiling, not a real capacity limit
MIN_ROW_COUNT = 1

ACCOUNTS_REQUIRED_COLUMNS = frozenset(
    {"Bank Name", "Bank ID", "Account Number", "Entity ID", "Entity Name"}
)
TRANSACTIONS_REQUIRED_COLUMNS = frozenset(
    {
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
    }
)

# ---------------------------------------------------------------------------
# Payment Format -> Channel mapping (judgment call, documented per task
# instructions). `Channel` (db/enums.py) is an India-rail-flavoured enum
# (UPI/NEFT/RTGS/IMPS/net_banking/...); the source dataset's `Payment Format`
# values are the IBM AML HI-Small vocabulary (Wire/ACH/Cheque/Cash/Credit
# Card/Reinvestment/Bitcoin — only a subset of which appears in either real
# file here, but the map covers the full known vocabulary so it doesn't need
# revisiting when a fuller extract of the source dataset is ingested later):
#
#   Wire         -> RTGS          large-value, real-time gross settlement is
#                                  the closest Indian-rail analogue to a wire.
#   ACH          -> NEFT          batched/deferred-net-settlement interbank
#                                  transfer — NEFT's own settlement model.
#   Cheque       -> cheque        direct match.
#   Cash         -> branch_cash   direct match (not present in either real
#                                  file, included for vocabulary completeness).
#   Credit Card  -> unknown       no card-rail value exists in `Channel` at
#                                  all (closest neighbours — UPI/mobile_app —
#                                  are wallet/bank-transfer rails, not card
#                                  network rails); mapping it to one of those
#                                  would misrepresent the channel rather than
#                                  honestly flag it as unmapped.
#   Reinvestment -> unknown       not a funds-movement channel/rail at all
#                                  (internal reinvestment of proceeds), so no
#                                  `Channel` value is a correct fit.
#   Bitcoin      -> unknown       no crypto rail in `Channel`.
#
# `Credit Card` and `Reinvestment` both appear for real in
# `data/tracex_test_day1.csv` — they are the real, non-contrived "unmapped
# Payment Format falls back to Channel.unknown" edge case, not a synthetic
# one manufactured for the test suite.
PAYMENT_FORMAT_TO_CHANNEL: dict[str, Channel] = {
    "Wire": Channel.RTGS,
    "ACH": Channel.NEFT,
    "Cheque": Channel.cheque,
    "Cash": Channel.branch_cash,
}

# Currency-name -> ISO-4217-ish code normalization. `amount`/`currency` are
# populated from the *paid* side (doc §3.1: "CSV `Amount Paid` (use paid
# side)"), so `currency` tracks `Payment Currency`, not a hardcoded "INR" —
# the dataset has genuine fx rows (doc: "amount_received ... (fx cases)").
# Only the vocabulary actually observed across both real files is mapped;
# anything else falls back to the raw (stripped) source string so no data is
# silently dropped, with "INR" only as the true empty-value default (doc §0:
# "Currency: NUMERIC, INR default").
CURRENCY_NAME_TO_CODE: dict[str, str] = {
    "Indian Rupee": "INR",
    "US Dollar": "USD",
    "Euro": "EUR",
    "UK Pound": "GBP",
    "Bitcoin": "BTC",
}

STATUS_IN_PROGRESS = "in_progress"
STATUS_SUCCESS = "success"
STATUS_REJECTED = "rejected"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"  # IngestOutcome-only, never persisted as a second row
STATUS_ABORTED = "aborted"  # IngestOutcome-only: not attempted, a dependency failed first


@dataclass
class ValidationResult:
    """Upload-validation outcome, persisted verbatim into
    `ingestion_log.validation` (JSON) so a rejected file's reason is
    inspectable later (doc §3.5)."""

    ok: bool
    filename: str
    file_size_bytes: int
    extension: str
    mime_type: str | None
    row_count: int | None
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "filename": self.filename,
            "file_size_bytes": self.file_size_bytes,
            "extension": self.extension,
            "mime_type": self.mime_type,
            "row_count": self.row_count,
            "errors": self.errors,
        }


@dataclass
class IngestOutcome:
    file_hash: str
    filename: str
    status: str  # success | rejected | failed | skipped | aborted
    num_customers: int = 0
    num_accounts: int = 0
    num_transactions: int = 0
    num_rows_skipped: int = 0
    validation: dict[str, Any] | None = None
    errors: list[str] = field(default_factory=list)


def validate_upload(
    path: Path, *, required_columns: frozenset[str] | None = None
) -> ValidationResult:
    """File-size limit, extension/MIME sanity check, row-count sanity check
    (`SYSTEM_DEVELOPMENT_PLAN.md` "Upload validation" / Q21) plus a
    column-presence check (same spirit as Q21's `DataContractValidator`
    schema check) when `required_columns` is given.

    Cheap checks (extension, existence, size) run first and short-circuit
    before the file is ever opened for parsing, so an oversized/malicious
    file is rejected without reading its contents.
    """
    errors: list[str] = []
    ext = path.suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        allowed = sorted(ALLOWED_EXTENSIONS)
        errors.append(f"unsupported extension {ext!r}, expected one of {allowed}")

    if not path.exists() or not path.is_file():
        errors.append(f"file not found: {path}")
        return ValidationResult(
            ok=False,
            filename=path.name,
            file_size_bytes=0,
            extension=ext,
            mime_type=None,
            row_count=None,
            errors=errors,
        )

    size = path.stat().st_size
    if size == 0:
        errors.append("file is empty (0 bytes)")
    if size > MAX_FILE_SIZE_BYTES:
        errors.append(f"file too large: {size} bytes exceeds limit {MAX_FILE_SIZE_BYTES} bytes")

    mime_type, _ = mimetypes.guess_type(str(path))
    if mime_type not in ALLOWED_MIME_TYPES:
        errors.append(f"unexpected MIME type {mime_type!r}")

    row_count: int | None = None
    # Only open/parse the file if the size check passed — no reason to read
    # a file we've already decided to reject for being oversized.
    if 0 < size <= MAX_FILE_SIZE_BYTES:
        try:
            with path.open(newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                if header is None:
                    errors.append("file has no header row")
                elif required_columns is not None:
                    missing = required_columns - set(header)
                    if missing:
                        errors.append(f"missing required columns: {sorted(missing)}")
                row_count = sum(1 for _ in reader)
        except UnicodeDecodeError as exc:
            errors.append(f"file is not valid UTF-8 text: {exc}")

        if row_count is not None:
            if row_count < MIN_ROW_COUNT:
                errors.append(f"row count {row_count} is below the minimum {MIN_ROW_COUNT}")
            if row_count > MAX_ROW_COUNT:
                errors.append(f"row count {row_count} exceeds the sanity ceiling {MAX_ROW_COUNT}")

    return ValidationResult(
        ok=not errors,
        filename=path.name,
        file_size_bytes=size,
        extension=ext,
        mime_type=mime_type,
        row_count=row_count,
        errors=errors,
    )


def hash_file(path: Path) -> str:
    """SHA-256 over the file contents, streamed so a 34MB+ CSV doesn't get
    loaded into memory at once — the `ingestion_log.file_hash` PK / the
    file-level idempotency guard."""
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _txn_key(row: dict[str, str]) -> str:
    """The stable tuple of raw CSV string fields that together identify a
    transfer event, joined into one canonical string. Raw strings (not
    parsed floats/datetimes) so formatting is stable across runs/platforms —
    a float round-trip could otherwise change its `repr` and silently break
    the "re-ingest = idempotent" property `make_txn_id` exists for.
    """
    fields = (
        row.get("Timestamp", ""),
        row.get("From Bank", ""),
        row.get("Account", ""),
        row.get("To Bank", ""),
        row.get("Account.1", ""),
        row.get("Amount Received", ""),
        row.get("Receiving Currency", ""),
        row.get("Amount Paid", ""),
        row.get("Payment Currency", ""),
        row.get("Payment Format", ""),
    )
    return "|".join(fields)


def make_txn_id(row: dict[str, str], occurrence: int = 0) -> str:
    """Deterministic `txn_id` (doc §3.1: "deterministic hash if source lacks
    id" — this CSV has no id column).

    `occurrence` disambiguates genuinely distinct transactions that share an
    identical `_txn_key` — the CSV's `Timestamp` is minute-precision, so two
    separate legitimate transfers between the same account pair, for the
    same amount/currency/payment-format, in the same clock minute (exactly
    the repeated-small-transfer/structuring pattern this platform exists to
    detect) would otherwise hash to the same `txn_id` and the second would
    be silently dropped as a false "already ingested" duplicate. Callers
    track how many times a given `_txn_key` has already been seen *within
    this ingest run, in file order* and pass that count in — deterministic
    and stable across re-ingests of the same file (same rows, same order,
    same occurrence sequence), so idempotency is preserved.
    """
    canonical = f"{_txn_key(row)}|{occurrence}"
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"TXN-{digest[:32]}"


def parse_timestamp(raw: str) -> datetime:
    """`docs/DATA_SCHEMA.md` §3.1: CSV `Timestamp` is `YYYY/MM/DD HH:MM`."""
    return datetime.strptime(raw.strip(), "%Y/%m/%d %H:%M").replace(tzinfo=UTC)


def infer_entity_type(entity_name: str) -> EntityType:
    """`HI-Small_accounts.csv` has no explicit entity-type column; its
    `Entity Name` values are drawn from a small fixed vocabulary of prefixes
    (`Individual #NNNN`, `Corporation #NNNN`, `Partnership #NNNN`, `Sole
    Proprietorship #NNNN`, `Country #NNNN`, `Direct #NNNN` — verified against
    the real file). Judgment call: only the literal `Individual` prefix maps
    to `EntityType.INDIVIDUAL`; every other prefix (including the less
    obviously-corporate `Country`/`Direct`) maps to `EntityType.BUSINESS`,
    since none of them describes a natural person.
    """
    if entity_name.strip().startswith("Individual"):
        return EntityType.INDIVIDUAL
    return EntityType.BUSINESS


def map_channel(payment_format: str) -> Channel:
    """CSV `Payment Format` -> `Channel`, see `PAYMENT_FORMAT_TO_CHANNEL`
    above for the full mapping table + reasoning. Anything not in the table
    (including values outside the known IBM AML vocabulary) falls back to
    `Channel.unknown` rather than raising, since ingest must not crash on an
    unrecognized-but-legitimate channel string.
    """
    return PAYMENT_FORMAT_TO_CHANNEL.get(payment_format.strip(), Channel.unknown)


def normalize_currency(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return "INR"
    return CURRENCY_NAME_TO_CODE.get(raw, raw)


def _parse_money(raw: str) -> float | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _iter_rows(path: Path) -> Iterator[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        yield from csv.DictReader(f)


def _missing_fields(row: Mapping[str, str | None], required_columns: frozenset[str]) -> list[str]:
    """A ragged/short data row (fewer fields than the header) makes
    `csv.DictReader` fill the missing trailing key(s) with `None` (its
    `restval` default) rather than raising — `validate_upload` only checks
    the *header* has the required columns, never that every *data* row
    actually has a value for each of them. Detecting that here lets a
    single malformed row be skipped (logged, counted) instead of raising an
    unhandled `AttributeError` out of a bare `.strip()` call that would
    abort the rest of an otherwise-good file.
    """
    return [c for c in required_columns if row.get(c) is None]


def _upsert_ingestion_log(
    log_repo: IngestionLogRepository,
    *,
    file_hash: str,
    filename: str,
    status: str,
    existing_present: bool,
    actor_id: str | None,
    **fields: Any,
) -> None:
    if existing_present:
        log_repo.update(
            file_hash, status=status, actor_type=ActorType.SYSTEM, actor_id=actor_id, **fields
        )
    else:
        log_repo.create(
            file_hash=file_hash,
            filename=filename,
            status=status,
            actor_type=ActorType.SYSTEM,
            actor_id=actor_id,
            **fields,
        )


# ---------------------------------------------------------------------------
# Accounts CSV -> customers + accounts
# ---------------------------------------------------------------------------
def ingest_accounts_csv(
    session: Session,
    path: Path = DEFAULT_ACCOUNTS_CSV,
    *,
    actor_id: str | None = None,
    batch_size: int = 2000,
) -> IngestOutcome:
    file_hash = hash_file(path)
    log_repo = IngestionLogRepository(session)
    existing = log_repo.get(file_hash)

    if existing is not None and existing.status == STATUS_SUCCESS:
        return IngestOutcome(
            file_hash=file_hash,
            filename=path.name,
            status=STATUS_SKIPPED,
            num_customers=0,
            num_accounts=existing.num_accounts,
            validation=existing.validation,
        )

    validation = validate_upload(path, required_columns=ACCOUNTS_REQUIRED_COLUMNS)
    if not validation.ok:
        _upsert_ingestion_log(
            log_repo,
            file_hash=file_hash,
            filename=path.name,
            status=STATUS_REJECTED,
            existing_present=existing is not None,
            actor_id=actor_id,
            validation=validation.to_dict(),
        )
        session.commit()
        return IngestOutcome(
            file_hash=file_hash,
            filename=path.name,
            status=STATUS_REJECTED,
            validation=validation.to_dict(),
            errors=validation.errors,
        )

    _upsert_ingestion_log(
        log_repo,
        file_hash=file_hash,
        filename=path.name,
        status=STATUS_IN_PROGRESS,
        existing_present=existing is not None,
        actor_id=actor_id,
        validation=validation.to_dict(),
    )
    session.commit()

    customer_repo = CustomerRepository(session)
    account_repo = AccountRepository(session)
    seen_customers: set[str] = set()
    seen_accounts: set[str] = set()
    num_customers = 0
    num_accounts = 0
    num_rows_skipped = 0

    try:
        for i, row in enumerate(_iter_rows(path), start=1):
            missing = _missing_fields(row, ACCOUNTS_REQUIRED_COLUMNS)
            if missing:
                logger.warning("accounts ingest: skipping row %d, missing fields %s", i, missing)
                num_rows_skipped += 1
                continue

            customer_id = row["Entity ID"].strip()
            if customer_id and customer_id not in seen_customers:
                seen_customers.add(customer_id)
                if customer_repo.get(customer_id) is None:
                    customer_repo.create(
                        customer_id=customer_id,
                        name=row["Entity Name"].strip(),
                        entity_type=infer_entity_type(row["Entity Name"]),
                        risk_rating=RiskLevel.LOW,
                        actor_type=ActorType.SYSTEM,
                        actor_id=actor_id,
                    )
                    num_customers += 1

            account_id = row["Account Number"].strip()
            if account_id and account_id not in seen_accounts:
                seen_accounts.add(account_id)
                if account_repo.get(account_id) is None:
                    account_repo.create(
                        account_id=account_id,
                        customer_id=customer_id or None,
                        bank_name=row["Bank Name"].strip() or None,
                        bank_id=row["Bank ID"].strip() or None,
                        actor_type=ActorType.SYSTEM,
                        actor_id=actor_id,
                    )
                    num_accounts += 1

            if i % batch_size == 0:
                session.commit()
                logger.info("accounts ingest: %d rows processed", i)
    except Exception:
        session.rollback()
        _upsert_ingestion_log(
            log_repo,
            file_hash=file_hash,
            filename=path.name,
            status=STATUS_FAILED,
            existing_present=True,
            actor_id=actor_id,
        )
        session.commit()
        raise

    session.commit()
    _upsert_ingestion_log(
        log_repo,
        file_hash=file_hash,
        filename=path.name,
        status=STATUS_SUCCESS,
        existing_present=True,
        actor_id=actor_id,
        num_accounts=num_accounts,
        validation=validation.to_dict(),
    )
    session.commit()

    return IngestOutcome(
        file_hash=file_hash,
        filename=path.name,
        status=STATUS_SUCCESS,
        num_customers=num_customers,
        num_accounts=num_accounts,
        num_rows_skipped=num_rows_skipped,
        validation=validation.to_dict(),
    )


def _maybe_enrich_customer(
    customer_repo: CustomerRepository,
    account_repo: AccountRepository,
    account_id: str,
    occupation_raw: str,
    income_raw: str,
    *,
    actor_id: str | None,
    enriched: set[str],
) -> None:
    """Enrich `customers.occupation`/`declared_annual_income` for the
    customer linked to `account_id`, if any (doc §3.1: "populated (CSV
    Source/Dest_Occupation)"/"(CSV Declared_Income)").

    Judgment call (documented at module level and here): only enriches when
    the account already has a non-null `customer_id` — i.e. it came from the
    accounts CSV, the authoritative KYC source. An account minted fresh by
    the transactions ingest (decision #3: `customer_id=NULL`, "some txn
    accounts have no KYC record") has no customer row to enrich; inventing
    one here would contradict that explicit nullable-FK decision. On the two
    real files this is a no-op (zero account-id overlap between them, see
    module docstring) — exercised instead by a synthetic-overlap unit test.

    `enriched` is a per-ingest-run set of customer_ids already written by
    this function, shared across every row of the file by the caller. An
    account with many transactions would otherwise trigger one identical
    UPDATE (+ one audit_log row) per transaction row referencing it; once a
    customer has actually been enriched this run, later rows for the same
    customer are skipped instead of re-writing identical values.
    """
    account = account_repo.get(account_id)
    if account is None or account.customer_id is None or account.customer_id in enriched:
        return

    fields: dict[str, Any] = {}
    occupation = occupation_raw.strip()
    if occupation:
        fields["occupation"] = occupation
    income = _parse_money(income_raw)
    if income is not None:
        fields["declared_annual_income"] = income
    if not fields:
        return

    customer_repo.update(
        account.customer_id, actor_type=ActorType.SYSTEM, actor_id=actor_id, **fields
    )
    enriched.add(account.customer_id)


# ---------------------------------------------------------------------------
# Transactions CSV -> transactions (+ minimal accounts, + customer enrichment)
# ---------------------------------------------------------------------------
def ingest_transactions_csv(
    session: Session,
    path: Path = DEFAULT_TRANSACTIONS_CSV,
    *,
    actor_id: str | None = None,
    batch_size: int = 2000,
) -> IngestOutcome:
    file_hash = hash_file(path)
    log_repo = IngestionLogRepository(session)
    existing = log_repo.get(file_hash)

    if existing is not None and existing.status == STATUS_SUCCESS:
        return IngestOutcome(
            file_hash=file_hash,
            filename=path.name,
            status=STATUS_SKIPPED,
            num_transactions=existing.num_transactions,
            num_accounts=existing.num_accounts,
            validation=existing.validation,
        )

    validation = validate_upload(path, required_columns=TRANSACTIONS_REQUIRED_COLUMNS)
    if not validation.ok:
        _upsert_ingestion_log(
            log_repo,
            file_hash=file_hash,
            filename=path.name,
            status=STATUS_REJECTED,
            existing_present=existing is not None,
            actor_id=actor_id,
            validation=validation.to_dict(),
        )
        session.commit()
        return IngestOutcome(
            file_hash=file_hash,
            filename=path.name,
            status=STATUS_REJECTED,
            validation=validation.to_dict(),
            errors=validation.errors,
        )

    # The in-progress row must exist (and be committed) before any
    # transaction row is flushed: `transactions.source_file_hash` is a FK to
    # `ingestion_log.file_hash`.
    _upsert_ingestion_log(
        log_repo,
        file_hash=file_hash,
        filename=path.name,
        status=STATUS_IN_PROGRESS,
        existing_present=existing is not None,
        actor_id=actor_id,
        validation=validation.to_dict(),
    )
    session.commit()

    account_repo = AccountRepository(session)
    customer_repo = CustomerRepository(session)
    txn_repo = TransactionRepository(session)

    known_accounts: set[str] = set()
    enriched_customers: set[str] = set()
    txn_key_occurrences: dict[str, int] = {}
    num_new_accounts = 0
    num_txns = 0
    num_rows_skipped = 0
    earliest_ts: datetime | None = None

    try:
        for i, row in enumerate(_iter_rows(path), start=1):
            missing = _missing_fields(row, TRANSACTIONS_REQUIRED_COLUMNS)
            if missing:
                logger.warning(
                    "transactions ingest: skipping row %d, missing fields %s", i, missing
                )
                num_rows_skipped += 1
                continue

            source_account = row["Account"].strip()
            dest_account = row["Account.1"].strip()
            from_bank = row["From Bank"].strip() or None
            to_bank = row["To Bank"].strip() or None

            for acct_id, bank_name in ((source_account, from_bank), (dest_account, to_bank)):
                if acct_id in known_accounts:
                    continue
                known_accounts.add(acct_id)
                if account_repo.get(acct_id) is None:
                    # Decision #3: any txn account not already present (from
                    # the accounts CSV) is minted minimal, customer_id=NULL.
                    account_repo.create(
                        account_id=acct_id,
                        customer_id=None,
                        bank_name=bank_name,
                        actor_type=ActorType.SYSTEM,
                        actor_id=actor_id,
                    )
                    num_new_accounts += 1

            ts = parse_timestamp(row["Timestamp"])
            if earliest_ts is None or ts < earliest_ts:
                earliest_ts = ts

            txn_key = _txn_key(row)
            occurrence = txn_key_occurrences.get(txn_key, 0)
            txn_key_occurrences[txn_key] = occurrence + 1
            txn_id = make_txn_id(row, occurrence)
            if txn_repo.get(txn_id) is None:
                amount = _parse_money(row["Amount Paid"])
                amount_received = _parse_money(row["Amount Received"])
                if amount is None:
                    raise ValueError(f"row {i}: unparseable Amount Paid {row['Amount Paid']!r}")
                txn_repo.create(
                    txn_id=txn_id,
                    timestamp=ts,
                    source_account=source_account,
                    dest_account=dest_account,
                    amount=amount,
                    amount_received=amount_received,
                    currency=normalize_currency(row["Payment Currency"]),
                    channel=map_channel(row["Payment Format"]),
                    is_laundering=int(row["Is Laundering"].strip() or 0),
                    from_bank=from_bank,
                    to_bank=to_bank,
                    source_file_hash=file_hash,
                    ingested_at=datetime.now(UTC),
                    actor_type=ActorType.SYSTEM,
                    actor_id=actor_id,
                )
                num_txns += 1

            _maybe_enrich_customer(
                customer_repo,
                account_repo,
                source_account,
                row["Source_Occupation"],
                row["Source_Declared_Income"],
                actor_id=actor_id,
                enriched=enriched_customers,
            )
            _maybe_enrich_customer(
                customer_repo,
                account_repo,
                dest_account,
                row["Dest_Occupation"],
                row["Dest_Declared_Income"],
                actor_id=actor_id,
                enriched=enriched_customers,
            )

            if i % batch_size == 0:
                session.commit()
                logger.info("transactions ingest: %d rows processed", i)
    except Exception:
        session.rollback()
        _upsert_ingestion_log(
            log_repo,
            file_hash=file_hash,
            filename=path.name,
            status=STATUS_FAILED,
            existing_present=True,
            actor_id=actor_id,
        )
        session.commit()
        raise

    session.commit()
    _upsert_ingestion_log(
        log_repo,
        file_hash=file_hash,
        filename=path.name,
        status=STATUS_SUCCESS,
        existing_present=True,
        actor_id=actor_id,
        num_transactions=num_txns,
        num_accounts=num_new_accounts,
        business_date=earliest_ts,
        validation=validation.to_dict(),
    )
    session.commit()

    return IngestOutcome(
        file_hash=file_hash,
        filename=path.name,
        status=STATUS_SUCCESS,
        num_accounts=num_new_accounts,
        num_transactions=num_txns,
        num_rows_skipped=num_rows_skipped,
        validation=validation.to_dict(),
    )


# Statuses that mean "the accounts CSV is actually loaded" (or was already,
# from a prior run) — either is a safe precondition for ingesting
# transactions, which relies on the accounts table being the authoritative
# KYC source (doc §4 decision 2). REJECTED/FAILED mean it is not.
_ACCOUNTS_OK_STATUSES = frozenset({STATUS_SUCCESS, STATUS_SKIPPED})


def run_full_ingest(
    session: Session,
    *,
    accounts_path: Path = DEFAULT_ACCOUNTS_CSV,
    transactions_path: Path = DEFAULT_TRANSACTIONS_CSV,
    actor_id: str | None = "ingest-cli",
) -> tuple[IngestOutcome, IngestOutcome]:
    """Orchestrate the Phase-1 seed order (doc §4 decision 2 / module
    docstring): accounts (authoritative KYC source) before transactions.

    If the accounts ingest does not succeed (REJECTED/FAILED), transactions
    ingest is **not attempted** — proceeding anyway would silently mint every
    transaction account with `customer_id=NULL` (the "no KYC record"
    fallback) even though the real accounts data was never loaded, leaving a
    customer-less, KYC-orphaned DB that still reports overall success.
    """
    accounts_outcome = ingest_accounts_csv(session, accounts_path, actor_id=actor_id)
    logger.info("accounts ingest outcome: %s", accounts_outcome)

    if accounts_outcome.status not in _ACCOUNTS_OK_STATUSES:
        logger.error(
            "accounts ingest did not succeed (status=%s) — aborting transactions ingest "
            "rather than loading transactions against a missing/incomplete accounts table",
            accounts_outcome.status,
        )
        aborted_transactions_outcome = IngestOutcome(
            file_hash="",
            filename=transactions_path.name,
            status=STATUS_ABORTED,
            errors=["accounts ingest did not succeed; transactions ingest was not attempted"],
        )
        return accounts_outcome, aborted_transactions_outcome

    transactions_outcome = ingest_transactions_csv(session, transactions_path, actor_id=actor_id)
    logger.info("transactions ingest outcome: %s", transactions_outcome)
    return accounts_outcome, transactions_outcome


# Statuses (for either outcome) that mean the CLI should exit non-zero — a
# caller/automation relying on the process exit code must not see success
# when the seed data is missing/incomplete.
_FAILURE_STATUSES = frozenset({STATUS_REJECTED, STATUS_FAILED, STATUS_ABORTED})


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(
        description="Ingest the TraceX seed CSVs (data/HI-Small_accounts.csv, "
        "data/tracex_test_day1.csv) into the configured DB (foundation.config "
        "database_url)."
    )
    parser.add_argument("--accounts-csv", type=Path, default=DEFAULT_ACCOUNTS_CSV)
    parser.add_argument("--transactions-csv", type=Path, default=DEFAULT_TRANSACTIONS_CSV)
    parser.add_argument("--actor-id", default="ingest-cli")
    args = parser.parse_args()

    session = SessionLocal()
    try:
        accounts_outcome, transactions_outcome = run_full_ingest(
            session,
            accounts_path=args.accounts_csv,
            transactions_path=args.transactions_csv,
            actor_id=args.actor_id,
        )
        print(f"accounts:     {accounts_outcome}")
        print(f"transactions: {transactions_outcome}")
    finally:
        session.close()

    if (
        accounts_outcome.status in _FAILURE_STATUSES
        or transactions_outcome.status in _FAILURE_STATUSES
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
