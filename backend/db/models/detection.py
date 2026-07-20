"""
Detection & governance tables — `docs/DATA_SCHEMA.md` §3.2: `alerts`,
`model_runs`, `rule_definitions`, `rl_arm_state`, `detection_feedback`.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from db.enums import CaseResolution, DetectionType, Priority, ReviewStatus, RiskLevel
from db.models.base import Base, CreatedAtMixin, UpdatedAtMixin, sa_enum


class Alert(Base):
    """Detector output for investigator review.

    `model_run_id` ties every alert to the exact model version/metrics that
    produced it (ML governance). Deterministic `alert_id` (accounts + type +
    date, see the existing `make_deterministic_alert_id` pattern) prevents
    duplicate rows on re-detection — `last_seen_at` is refreshed instead.
    No separate `updated_at`: the doc's own column list for this table names
    `last_seen_at` as the mutation timestamp, so it is not duplicated here.
    """

    __tablename__ = "alerts"

    alert_id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str | None] = mapped_column(
        ForeignKey("cases.case_id"), nullable=True, index=True
    )
    detection_type: Mapped[DetectionType] = mapped_column(
        sa_enum(DetectionType), nullable=False, index=True
    )
    primary_account_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.account_id"), nullable=False
    )
    account_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    score: Mapped[float] = mapped_column(nullable=False)
    risk_score: Mapped[float] = mapped_column(nullable=False, index=True)
    severity: Mapped[RiskLevel] = mapped_column(sa_enum(RiskLevel), nullable=False)
    priority: Mapped[Priority] = mapped_column(sa_enum(Priority), nullable=False)
    confidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)  # open/assigned/closed
    rule_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    model_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("model_runs.run_id"), nullable=True
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)  # pipeline/realtime
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ModelRun(Base):
    """ML model governance/lineage. Persisted so the ensemble is trained
    once and never retrained on boot (landmine fix, ROADMAP Phase 3)."""

    __tablename__ = "model_runs"

    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    model_type: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(Text, nullable=False)
    trained_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    dataset_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    metrics: Mapped[dict] = mapped_column(JSON, nullable=False)
    feature_importance: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    artifact_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False)


class RuleDefinition(Base, CreatedAtMixin, UpdatedAtMixin):
    """Rule Engine DSL (11 primitives, Tier-2 composition) + feedback-loop
    confidence."""

    __tablename__ = "rule_definitions"

    rule_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    dsl: Mapped[dict] = mapped_column(JSON, nullable=False)
    tier: Mapped[int] = mapped_column(nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.user_id"), nullable=True)


class RuleProposal(Base, CreatedAtMixin, UpdatedAtMixin):
    """A proposed detection rule awaiting Admin/Compliance review — the
    human-in-the-loop half of the Phase 12 feedback loop. An investigator (or
    the system, from an unexplained edge case) proposes a rule DSL + rationale;
    an admin reviews it and either APPROVES (minting an enabled
    `RuleDefinition`, whose id is recorded in `created_rule_id`) or REJECTS it
    with a note. The proposal row is the audit trail of that decision — it is
    never deleted, only transitioned."""

    __tablename__ = "rule_proposals"

    proposal_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    dsl: Mapped[dict] = mapped_column(JSON, nullable=False)
    tier: Mapped[int] = mapped_column(nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ReviewStatus] = mapped_column(sa_enum(ReviewStatus), nullable=False)
    proposed_by: Mapped[str] = mapped_column(ForeignKey("users.user_id"), nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.user_id"), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_rule_id: Mapped[str | None] = mapped_column(
        ForeignKey("rule_definitions.rule_id"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RlArmState(Base):
    """LinUCB bandit persistence — no reset on boot.

    The bandit's A/b matrices are all that's needed to resume learning;
    persisting them fixes the "RL state lost on restart" landmine.
    """

    __tablename__ = "rl_arm_state"

    arm_id: Mapped[str] = mapped_column(String, primary_key=True)
    a_matrix: Mapped[list] = mapped_column(JSON, nullable=False)
    b_vector: Mapped[list] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DetectionFeedback(Base):
    """Investigator verdict -> RL reward + rule confidence adjustment."""

    __tablename__ = "detection_feedback"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.case_id"), nullable=False)
    alert_id: Mapped[str | None] = mapped_column(ForeignKey("alerts.alert_id"), nullable=True)
    verdict: Mapped[CaseResolution] = mapped_column(sa_enum(CaseResolution), nullable=False)
    reward: Mapped[float] = mapped_column(nullable=False)
    rule_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.user_id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
