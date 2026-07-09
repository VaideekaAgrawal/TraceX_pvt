"""
Platform tables — `docs/DATA_SCHEMA.md` §3.5: `users`, `audit_log`,
`watchlist`, `ingestion_log`.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from db.enums import ActorType, UserRole, WatchEntityType
from db.models.base import Base, CreatedAtMixin, sa_enum


class User(Base, CreatedAtMixin):
    """Two roles only (RBAC decision). `last_login_at` powers the Copilot
    "what changed since last login" digest. Workload for auto-assignment is
    derived (COUNT open cases WHERE assigned_to=?), not stored here.
    """

    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    username: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    email: Mapped[str] = mapped_column(Text, nullable=False)  # PII
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[UserRole] = mapped_column(sa_enum(UserRole), nullable=False)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)  # PII
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    """Append-only, tamper-evident, every action. One unified queryable log
    (fixes the "partial/implicit audit" landmine). The `prev_hash`/`row_hash`
    chain gives tamper-evidence cheaply, reusing the SHA-256 pattern already
    used by `EvidencePack`. Append-only: no updates/deletes ever — enforced
    by the repository layer (Phase 1 follow-up), not by this model.
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_type: Mapped[ActorType] = mapped_column(sa_enum(ActorType), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    action: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    case_id: Mapped[str | None] = mapped_column(
        ForeignKey("cases.case_id"), nullable=True, index=True
    )
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    prev_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    row_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class Watchlist(Base, CreatedAtMixin):
    """Alerts touching a watchlisted entity get auto-priority (Phase 11);
    maps to FATF R.10 ongoing due diligence."""

    __tablename__ = "watchlist"

    entry_id: Mapped[str] = mapped_column(String, primary_key=True)
    entity_type: Mapped[WatchEntityType] = mapped_column(sa_enum(WatchEntityType), nullable=False)
    entity_value: Mapped[str] = mapped_column(Text, nullable=False)  # PII if entity is a person
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    added_by: Mapped[str] = mapped_column(ForeignKey("users.user_id"), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IngestionLog(Base):
    """Idempotent CSV ingest. Prevents double-ingesting the same file;
    `validation` records upload-safety checks (size/MIME/row-count) so a
    rejected file's reason is inspectable."""

    __tablename__ = "ingestion_log"

    file_hash: Mapped[str] = mapped_column(String, primary_key=True)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    business_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    num_transactions: Mapped[int] = mapped_column(nullable=False, default=0)
    num_accounts: Mapped[int] = mapped_column(nullable=False, default=0)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    validation: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
