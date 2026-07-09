"""
AI orchestration tables — `docs/DATA_SCHEMA.md` §3.4: `ai_interactions`,
`relationships`. Built on top of, not before, the investigation spine
(ROADMAP Phase 8+) but the schema exists from Phase 1 so later phases don't
need a migration just to add these tables.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from db.enums import AiAgent
from db.models.base import Base, sa_enum


class AiInteraction(Base):
    """Audit + grounding log for BOTH agents (Recommendation Engine,
    Copilot). This is what makes "not a stupid LLM call" provable: every
    recommendation persists its driving facts + rule anchors + which tools
    produced them, so a regulator can reconstruct *why* the system said
    what it said.
    """

    __tablename__ = "ai_interactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str | None] = mapped_column(
        ForeignKey("cases.case_id"), nullable=True, index=True
    )
    agent: Mapped[AiAgent] = mapped_column(sa_enum(AiAgent), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"), nullable=False)
    request_text: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # stored post-sanitization
    tools_called: Mapped[list | None] = mapped_column(JSON, nullable=True)
    facts: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    rule_anchors: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    response_text: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    model_provider: Mapped[str] = mapped_column(Text, nullable=False)
    redacted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    latency_ms: Mapped[int | None] = mapped_column(nullable=True)
    investigator_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Relationship(Base):
    """Relationship Explorer discovered edges — hidden links transactions
    can't reveal. `value_hash` is a one-way hash of the shared attribute
    value (doc: "hashed, not raw") so the graph can show "shared phone"
    without exposing the number; see `db/pii.py` for why this column is
    deliberately *not* in the PII redaction allow-map even though it's
    derived from PII.
    """

    __tablename__ = "relationships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_a: Mapped[str] = mapped_column(ForeignKey("customers.customer_id"), nullable=False)
    entity_b: Mapped[str] = mapped_column(ForeignKey("customers.customer_id"), nullable=False)
    shared_attribute: Mapped[str] = mapped_column(Text, nullable=False)
    value_hash: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
