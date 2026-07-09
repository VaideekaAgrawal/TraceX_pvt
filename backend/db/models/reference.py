"""
Reference/domain tables — `docs/DATA_SCHEMA.md` §3.1: `customers`, `accounts`,
`transactions`. The core entity graph every other layer (detection,
investigation, AI) reads from.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from db.enums import AccountStatus, Channel, EddStatus, EntityType, KycStatus, RiskLevel
from db.models.base import Base, CreatedAtMixin, UpdatedAtMixin, sa_enum


class Customer(Base, CreatedAtMixin, UpdatedAtMixin):
    """The legal entity (CSV `Entity ID` / `Entity Name`).

    One customer -> many accounts (HI-Small structure). KYC/PEP/sanction and
    every identity field are schema-complete now even though the synthetic
    dataset doesn't fill them all, so L1 Customer Snapshot and the
    Relationship Explorer have their target shape from day one.
    """

    __tablename__ = "customers"

    customer_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)  # PII
    entity_type: Mapped[EntityType] = mapped_column(sa_enum(EntityType), nullable=False)
    pan: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)  # PII
    aadhaar: Mapped[str | None] = mapped_column(Text, nullable=True)  # PII
    phone: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)  # PII
    email: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)  # PII
    address: Mapped[str | None] = mapped_column(Text, nullable=True)  # PII
    occupation: Mapped[str | None] = mapped_column(Text, nullable=True)
    declared_annual_income: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    income_bracket: Mapped[str | None] = mapped_column(Text, nullable=True)
    employer: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)  # PII
    kyc_status: Mapped[KycStatus] = mapped_column(
        sa_enum(KycStatus), nullable=False, default=KycStatus.PENDING
    )
    edd_status: Mapped[EddStatus] = mapped_column(
        sa_enum(EddStatus), nullable=False, default=EddStatus.NOT_REQUIRED
    )
    pep_status: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sanction_status: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    risk_rating: Mapped[RiskLevel] = mapped_column(sa_enum(RiskLevel), nullable=False)


class Account(Base, CreatedAtMixin, UpdatedAtMixin):
    """A bank account (CSV `Account Number`).

    `current_risk_score` is a denormalized cache of the latest detection
    output so L1 triage doesn't recompute; source of truth is the detection
    pipeline, refreshed on each run.
    """

    __tablename__ = "accounts"

    account_id: Mapped[str] = mapped_column(String, primary_key=True)
    customer_id: Mapped[str | None] = mapped_column(
        ForeignKey("customers.customer_id"), nullable=True
    )
    account_type: Mapped[str] = mapped_column(Text, nullable=False, default="savings")
    bank_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    bank_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    branch_city: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    status: Mapped[AccountStatus] = mapped_column(
        sa_enum(AccountStatus), nullable=False, default=AccountStatus.ACTIVE
    )
    kyc_tier: Mapped[str | None] = mapped_column(Text, nullable=True)
    opening_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expected_monthly_volume: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    current_risk_score: Mapped[float | None] = mapped_column(nullable=True)


class Transaction(Base):
    """The atomic unit (CSV rows).

    Immutable ledger row: no `updated_at` — `docs/DATA_SCHEMA.md` §3.1 lists
    `ingested_at` (not `created_at`/`updated_at`) as this table's single
    timestamp, since a transaction is written once at ingest and never
    mutated afterwards. Judgment call: followed the doc's explicit column
    list literally rather than mechanically applying the general "every
    table has created_at" rule from §0, since this table's own spec already
    names the append-timestamp column.

    Composite indexes `(source_account, timestamp)` and
    `(dest_account, timestamp)` are the two hot paths for ego-graph
    extraction and timeline reconstruction (doc §3.1).
    """

    __tablename__ = "transactions"
    __table_args__ = (
        Index("ix_transactions_source_account_timestamp", "source_account", "timestamp"),
        Index("ix_transactions_dest_account_timestamp", "dest_account", "timestamp"),
    )

    txn_id: Mapped[str] = mapped_column(String, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    # No standalone `index=True` here: the composite indexes above already
    # cover single-column lookups on `source_account`/`dest_account` via
    # their leftmost prefix, so a separate single-column index would be pure
    # write/storage overhead with zero read-query benefit on this table.
    source_account: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"), nullable=False)
    dest_account: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    amount_received: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    currency: Mapped[str] = mapped_column(Text, nullable=False, default="INR")
    channel: Mapped[Channel] = mapped_column(sa_enum(Channel), nullable=False)
    txn_type: Mapped[str] = mapped_column(Text, nullable=False, default="transfer")
    narration: Mapped[str | None] = mapped_column(Text, nullable=True)  # PII, attacker-controllable
    purpose: Mapped[str | None] = mapped_column(Text, nullable=True)  # PII, attacker-controllable
    merchant_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_laundering: Mapped[int] = mapped_column(nullable=False)
    from_bank: Mapped[str | None] = mapped_column(Text, nullable=True)
    to_bank: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_file_hash: Mapped[str | None] = mapped_column(
        ForeignKey("ingestion_log.file_hash"), nullable=True
    )
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
