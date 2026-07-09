"""
Repositories for `docs/DATA_SCHEMA.md` §3.4 AI orchestration tables:
`ai_interactions`, `relationships`. The tables exist from Phase 1 (schema
only) so Phase 8+ doesn't need a migration just to add them; the actual
gateway/tool-layer/guardrail logic that populates them is out of scope here.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_, select

from db.enums import ActorType, AiAgent
from db.models.base import utcnow
from db.models.orchestration import AiInteraction, Relationship
from db.repositories.base import BaseRepository


class AiInteractionRepository(BaseRepository[AiInteraction]):
    """Audit + grounding log for both AI agents. No `update()`: an
    interaction record is written once by the agent that produced it (only
    `investigator_feedback` is ever appended after the fact, exposed via
    `record_feedback` rather than a general-purpose update to keep the
    "this is a log, not a mutable row" intent explicit)."""

    model = AiInteraction
    entity_type = "ai_interaction"
    pk_attr = "id"

    def create(
        self,
        *,
        agent: AiAgent,
        user_id: str,
        response_text: str,
        model: str,
        model_provider: str,
        case_id: str | None = None,
        request_text: str | None = None,
        tools_called: list | None = None,
        facts: dict | None = None,
        rule_anchors: dict | None = None,
        redacted: bool = False,
        latency_ms: int | None = None,
        created_at: datetime | None = None,
        actor_type: ActorType,
        actor_id: str | None,
    ) -> AiInteraction:
        interaction = AiInteraction(
            case_id=case_id,
            agent=agent,
            user_id=user_id,
            request_text=request_text,
            tools_called=tools_called,
            facts=facts,
            rule_anchors=rule_anchors,
            response_text=response_text,
            model=model,
            model_provider=model_provider,
            redacted=redacted,
            latency_ms=latency_ms,
            created_at=created_at if created_at is not None else utcnow(),
        )
        return self._create(
            interaction,
            actor_type=actor_type,
            actor_id=actor_id,
            action="ai_interaction_created",
            case_id=case_id,
        )

    def record_feedback(
        self,
        id_: int,
        *,
        investigator_feedback: str,
        actor_type: ActorType,
        actor_id: str | None,
    ) -> AiInteraction:
        interaction = self.get(id_)
        if interaction is None:
            raise ValueError(f"ai_interaction {id_!r} does not exist")
        return self._update(
            interaction,
            {"investigator_feedback": investigator_feedback},
            actor_type=actor_type,
            actor_id=actor_id,
            action="ai_interaction_feedback_recorded",
            case_id=interaction.case_id,
        )

    def list_for_case(self, case_id: str) -> list[AiInteraction]:
        stmt = select(AiInteraction).where(AiInteraction.case_id == case_id)
        return list(self.session.scalars(stmt))

    def list_for_user(self, user_id: str, *, limit: int = 100) -> list[AiInteraction]:
        stmt = select(AiInteraction).where(AiInteraction.user_id == user_id).limit(limit)
        return list(self.session.scalars(stmt))


class RelationshipRepository(BaseRepository[Relationship]):
    """Relationship Explorer discovered edges. No `update()`: a discovered
    relationship is immutable once recorded (a changed match would be a new
    `discovered_at` row from a later Relationship Explorer run, not an edit
    of the old evidence)."""

    model = Relationship
    entity_type = "relationship"
    pk_attr = "id"

    def create(
        self,
        *,
        entity_a: str,
        entity_b: str,
        shared_attribute: str,
        value_hash: str,
        confidence: float,
        method: str,
        discovered_at: datetime | None = None,
        actor_type: ActorType,
        actor_id: str | None,
    ) -> Relationship:
        relationship = Relationship(
            entity_a=entity_a,
            entity_b=entity_b,
            shared_attribute=shared_attribute,
            value_hash=value_hash,
            confidence=confidence,
            method=method,
            discovered_at=discovered_at if discovered_at is not None else utcnow(),
        )
        return self._create(
            relationship,
            actor_type=actor_type,
            actor_id=actor_id,
            action="relationship_created",
        )

    def list_for_entity(self, customer_id: str) -> list[Relationship]:
        """Relationships where `customer_id` is either side of the pair."""
        stmt = select(Relationship).where(
            or_(Relationship.entity_a == customer_id, Relationship.entity_b == customer_id)
        )
        return list(self.session.scalars(stmt))
