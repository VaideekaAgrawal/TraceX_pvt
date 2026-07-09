"""
Investigation spine tables — `docs/DATA_SCHEMA.md` §3.3: `cases`,
`case_accounts`, `case_status_history`, `evidence`, `notes`, `reports`,
`case_feature_vector`. `cases` is the single source of truth that kills the
two-case-store landmine (`CLAUDE.md`) — everything case-centric foreign-keys
here.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from db.enums import (
    AccountRole,
    CaseLevel,
    CaseResolution,
    CaseStatus,
    EvidenceType,
    NoteSource,
    Priority,
    ReportStatus,
    ReportType,
)
from db.models.base import Base, CreatedAtMixin, UpdatedAtMixin, sa_enum


class Case(Base, CreatedAtMixin, UpdatedAtMixin):
    """One row per case, one `assigned_to`, one status — everything
    case-centric (evidence, notes, SLA, audit, AI) foreign-keys here.
    `network_risk_score`/`_reasons` are stored (not recomputed each view) so
    L1 stays fast and the reason is auditable.
    """

    __tablename__ = "cases"

    case_id: Mapped[str] = mapped_column(String, primary_key=True)
    primary_account_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.account_id"), nullable=False
    )
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[CaseStatus] = mapped_column(sa_enum(CaseStatus), nullable=False, index=True)
    level: Mapped[CaseLevel] = mapped_column(sa_enum(CaseLevel), nullable=False)
    priority: Mapped[Priority] = mapped_column(sa_enum(Priority), nullable=False, index=True)
    typology: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_score: Mapped[float | None] = mapped_column(nullable=True)
    network_risk_score: Mapped[float | None] = mapped_column(nullable=True)
    network_risk_reasons: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    assigned_to: Mapped[str | None] = mapped_column(
        ForeignKey("users.user_id"), nullable=True, index=True
    )
    sla_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution: Mapped[CaseResolution | None] = mapped_column(
        sa_enum(CaseResolution), nullable=True
    )
    resolution_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_hash: Mapped[str | None] = mapped_column(Text, nullable=True)


class CaseAccount(Base):
    """Accounts in a case's scope (M:N). Defines exactly which accounts the
    case-scoping invariant permits AI/graph tools to touch — this table *is*
    the security boundary for a case."""

    __tablename__ = "case_accounts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.case_id"), nullable=False, index=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"), nullable=False)
    role: Mapped[AccountRole | None] = mapped_column(sa_enum(AccountRole), nullable=True)
    hop_distance: Mapped[int | None] = mapped_column(nullable=True)


class CaseStatusHistory(Base):
    """FSM transition log — explicit (not derived) so SLA/escalation
    reporting and "who moved this case when" are first-class; complements
    `audit_log` with typed workflow semantics.

    Judgment calls (doc §3.3 gives this table in compact/inline form without
    per-column null/idx annotations):
      - `case_id` indexed: it is the natural query pattern for this table
        (per-case transition history) even though the doc's compact row
        doesn't spell out `idx` the way the fuller table specs do.
      - `from_status` nullable: a case's very first history row (creation)
        has no prior status.
      - `changed_by` nullable: system-driven transitions (e.g. an
        SLA-timeout auto-escalation) may not have a human actor; `audit_log`
        still records `actor_type=SYSTEM` for those.
    """

    __tablename__ = "case_status_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.case_id"), nullable=False, index=True)
    from_status: Mapped[CaseStatus | None] = mapped_column(sa_enum(CaseStatus), nullable=True)
    to_status: Mapped[CaseStatus] = mapped_column(sa_enum(CaseStatus), nullable=False)
    changed_by: Mapped[str | None] = mapped_column(ForeignKey("users.user_id"), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Evidence(Base):
    """Evidence pack items."""

    __tablename__ = "evidence"

    evidence_id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.case_id"), nullable=False, index=True)
    type: Mapped[EvidenceType] = mapped_column(sa_enum(EvidenceType), nullable=False)
    ref_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    label: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    added_by: Mapped[str] = mapped_column(ForeignKey("users.user_id"), nullable=False)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Note(Base, UpdatedAtMixin):
    """Case notes (investigator OR copilot). `source` distinguishes
    copilot-written notes from human ones while keeping one notes store.

    Judgment call: `author_id` is nullable because a copilot-authored note
    (`source=COPILOT`) is not written by a human `users` row; the acting
    investigator's context (whose session the copilot ran in) still lives on
    the parent case's `assigned_to` / the triggering `ai_interactions` row,
    not duplicated here.
    """

    __tablename__ = "notes"

    note_id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.case_id"), nullable=False, index=True)
    author_id: Mapped[str | None] = mapped_column(ForeignKey("users.user_id"), nullable=True)
    source: Mapped[NoteSource] = mapped_column(sa_enum(NoteSource), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)  # may contain PII
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Report(Base):
    """SAR/STR generation (FIU-IND)."""

    __tablename__ = "reports"

    report_id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.case_id"), nullable=False)
    type: Mapped[ReportType] = mapped_column(sa_enum(ReportType), nullable=False)
    status: Mapped[ReportStatus] = mapped_column(sa_enum(ReportStatus), nullable=False)
    narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
    json_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    json_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    pdf_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    fiu_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_by: Mapped[str] = mapped_column(ForeignKey("users.user_id"), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CaseFeatureVector(Base):
    """For Similar Historical Cases: cosine similarity over this vector,
    reusing the RL 16-dim feature space instead of a new pipeline."""

    __tablename__ = "case_feature_vector"

    case_id: Mapped[str] = mapped_column(ForeignKey("cases.case_id"), primary_key=True)
    vector: Mapped[list] = mapped_column(JSON, nullable=False)
    typology: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome: Mapped[CaseResolution | None] = mapped_column(sa_enum(CaseResolution), nullable=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
