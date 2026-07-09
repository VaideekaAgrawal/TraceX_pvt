"""
Shared audit hash-chain plumbing used by every repository write method.

`docs/DATA_SCHEMA.md` §0: "every write that a human or an AI agent causes
also appends a row to `audit_log` ... Repositories enforce this, not
callers." §3.5 `audit_log`: SHA-256 hash chain (`prev_hash`/`row_hash`),
append-only, tamper-evident.

`append_audit_log()` is the single choke point every repository's
create/update/soft-delete method calls (via `db.repositories.base.
BaseRepository._create`/`_update`) — callers of the repository layer never
call it directly, matching the doc's "repositories enforce this, not
callers" invariant.
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum as PyEnum
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.enums import ActorType
from db.models.base import utcnow
from db.models.platform import AuditLog


def to_jsonable(value: Any) -> Any:
    """Recursively convert a value that may contain the non-JSON-native
    types SQLAlchemy hands back for our column types (`Decimal` for
    `Numeric`/MONEY, `datetime` for TS, Python `Enum` members for ENUM
    columns) into plain JSON-serializable types.

    Used both to sanitize `details` before it is stored in the `details`
    JSON column (SQLite's JSON type calls `json.dumps` with no custom
    `default=`, so it would otherwise raise on a bare `Decimal`/`datetime`)
    and to build the canonical payload the row hash is computed over, so the
    exact same conversion is applied whether the value came from a
    just-built domain object or was re-read from the database.
    """
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return _canonical_ts(value)
    if isinstance(value, PyEnum):
        return value.value
    if isinstance(value, dict):
        return {k: to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    return value


def _canonical_ts(dt: datetime) -> str:
    """Normalize a timestamp to a naive-UTC ISO string before hashing.

    SQLite has no native timezone-aware storage: a tz-aware `datetime`
    written through `DateTime(timezone=True)` comes back naive (but still
    UTC-valued) on read (verified empirically — see this task's session
    notes). Every timestamp in this schema is UTC by convention (doc §0),
    so normalizing both the just-built (aware) and re-read-from-DB (naive)
    values to the same naive-UTC ISO string makes `row_hash` reproducible
    across a write and a later verification read, instead of spuriously
    "breaking the chain" on every single row purely because of a driver
    round-trip quirk.
    """
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC).replace(tzinfo=None)
    return dt.isoformat()


def _latest_row_hash(session: Session) -> str | None:
    stmt = select(AuditLog.row_hash).order_by(AuditLog.id.desc()).limit(1)
    return session.execute(stmt).scalars().first()


def compute_row_hash(
    *,
    prev_hash: str | None,
    actor_type: ActorType,
    actor_id: str | None,
    action: str,
    entity_type: str,
    entity_id: str | None,
    case_id: str | None,
    details: dict[str, Any] | None,
    created_at: datetime,
) -> str:
    """`row_hash = SHA256(this row + prev_hash)` (doc §3.5), computed over a
    canonical (sorted-key, separator-tight) JSON encoding of every other
    audit_log column so the chain breaks if any of them is later tampered
    with. `details` is expected to already be JSON-safe (via `to_jsonable`)
    — callers (`append_audit_log`, `verify_chain`) are responsible for that,
    since one calls it on a freshly-built dict and the other on a
    JSON-column value already decoded by SQLAlchemy.
    """
    payload = {
        "prev_hash": prev_hash,
        "actor_type": actor_type.value,
        "actor_id": actor_id,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "case_id": case_id,
        "details": details,
        "created_at": _canonical_ts(created_at),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def append_audit_log(
    session: Session,
    *,
    actor_type: ActorType,
    actor_id: str | None,
    action: str,
    entity_type: str,
    entity_id: str | None,
    case_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    """Append one row to the tamper-evident audit hash-chain in `session`,
    flushed (not committed) so it lands in the same DB transaction as the
    domain write it documents — the caller's Session commits both together,
    so the two can never be left out of sync by a crash between them.

    Flushes before reading the previous row's `row_hash` so a prior,
    not-yet-committed audit row appended earlier in the same Session (e.g. a
    second repository call in the same request) is visible to this lookup —
    the chain must stay gapless across multiple repository calls sharing one
    Session, not just across separate commits.
    """
    session.flush()
    prev_hash = _latest_row_hash(session)
    created_at = utcnow()
    jsonable_details = to_jsonable(details) if details is not None else None
    row_hash = compute_row_hash(
        prev_hash=prev_hash,
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        case_id=case_id,
        details=jsonable_details,
        created_at=created_at,
    )
    row = AuditLog(
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        case_id=case_id,
        details=jsonable_details,
        prev_hash=prev_hash,
        row_hash=row_hash,
        created_at=created_at,
    )
    session.add(row)
    session.flush()
    return row


def verify_chain(session: Session) -> bool:
    """Recompute every `audit_log` row's hash from its own stored columns
    plus the previous row's stored `row_hash`, in `id` order, and confirm it
    matches the stored `row_hash` — and that `prev_hash` correctly equals
    the prior row's `row_hash` (or `None` for the first row).

    This is a verification helper proving the chain is computable and
    correct (and that tampering with any stored column would break it), not
    a full tamper-detection service (no background scanning, no external
    anchor/notarization) — sufficient for the pilot per
    `docs/DATA_SCHEMA.md` §4 decision 3.
    """
    stmt = select(AuditLog).order_by(AuditLog.id.asc())
    rows = session.execute(stmt).scalars().all()
    expected_prev: str | None = None
    for row in rows:
        if row.prev_hash != expected_prev:
            return False
        recomputed = compute_row_hash(
            prev_hash=row.prev_hash,
            actor_type=row.actor_type,
            actor_id=row.actor_id,
            action=row.action,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            case_id=row.case_id,
            details=row.details,
            created_at=row.created_at,
        )
        if recomputed != row.row_hash:
            return False
        expected_prev = row.row_hash
    return True
