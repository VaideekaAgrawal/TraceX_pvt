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
from db.repositories._audit import append_audit_log
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

    def list_for_case_and_agent(
        self, case_id: str, agent: AiAgent, *, limit: int = 500
    ) -> list[AiInteraction]:
        """Narrower than `list_for_case` -- also filters by `agent`.

        ROADMAP Phase 5's account-explanation cache (`orchestration.
        account_explanation`) is the first caller; ROADMAP Phase 6's
        pattern-explanation cache (`orchestration.pattern_explanation`) is
        the second, writing into the SAME `case_id`+`AiAgent.RECOMMENDATION`
        namespace on a disjoint key (`facts["account_id"]` vs.
        `facts["alert_id"]`). Both need THEIR OWN prior interactions for
        this case, but `facts[key] == value` isn't a portable SQL predicate
        (SQLite's JSON1 extension and Postgres's `jsonb` operators diverge),
        so that last narrowing step is each caller's job (`orchestration.
        llm_client.find_cached_interaction`), not this method's.

        Ordered by `created_at` descending *before* `.limit()` (code-review
        finding, Phase 5: without this, once a case passed the limit the
        kept rows were an arbitrary slice -- not necessarily the most
        recent -- so a cache lookup's `max(..., key=created_at)` over that
        slice could silently miss a fresher row, e.g. one just written by a
        `force=True` call).

        `limit=500` (raised from Phase 5's original `50`, code-review
        finding, Phase 6: with a second heavy writer now sharing this
        namespace and no upsert -- every cache-miss or `force=True` call
        inserts a NEW row, never replacing an old one -- a case combining
        several accounts' explanations and several alerts' pattern
        explanations across a deep-investigation session, plus repeated
        `force=True` re-explains, could realistically exceed 50 combined
        rows, at which point `LIMIT 50` would silently exclude an
        older-but-still-valid cached row and cause a spurious cache miss +
        LLM re-call. 500 is a documented judgment call, not derived from a
        formula -- same posture as `investigation.network_risk`'s weights --
        chosen to comfortably cover realistic combined volume for one case
        without being unbounded."""
        stmt = (
            select(AiInteraction)
            .where(AiInteraction.case_id == case_id, AiInteraction.agent == agent)
            .order_by(AiInteraction.created_at.desc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt))

    def list_for_user(self, user_id: str, *, limit: int = 100) -> list[AiInteraction]:
        stmt = select(AiInteraction).where(AiInteraction.user_id == user_id).limit(limit)
        return list(self.session.scalars(stmt))


class RelationshipRepository(BaseRepository[Relationship]):
    """Relationship Explorer discovered edges. No `update()`: a discovered
    relationship is immutable once recorded (a changed match would be a new
    `discovered_at` row from a later Relationship Explorer run, not an edit
    of the old evidence).

    `entity_a`/`entity_b` are always stored/queried in canonical
    (lexicographically sorted) order -- `create()`/`find_existing()` both
    sort the pair themselves rather than trusting the caller to have already
    done so (code-review finding, Phase 7: this was previously a documented
    caller-convention only, enforced solely by `investigation.
    relationship_discovery`'s own `_canonical_pair` helper with no check
    here -- a future second writer that didn't replicate that exact sort
    could insert a pair in reversed order and silently defeat `find_
    existing`'s dedup)."""

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
        entity_a, entity_b = sorted((entity_a, entity_b))
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

    def find_existing(
        self, entity_a: str, entity_b: str, shared_attribute: str
    ) -> Relationship | None:
        """Idempotency check for `investigation.relationship_discovery`
        (ROADMAP Phase 7): a rerun of the discovery job must not create a
        duplicate row for a pair/attribute-type combination it already
        found. Canonicalizes `entity_a`/`entity_b` itself (see class
        docstring) -- callers may pass either ordering."""
        entity_a, entity_b = sorted((entity_a, entity_b))
        stmt = select(Relationship).where(
            Relationship.entity_a == entity_a,
            Relationship.entity_b == entity_b,
            Relationship.shared_attribute == shared_attribute,
        )
        return self.session.scalars(stmt).first()

    def list_for_entities(self, customer_ids: list[str]) -> list[Relationship]:
        """Batched sibling of `list_for_entity` -- avoids a per-customer
        round trip when a caller (e.g. `investigation.relationship_graph.
        build_case_relationship_graph`) already has a small, bounded list
        of customer ids to resolve relationships for at once (same idiom as
        `AlertRepository.list_for_primary_accounts`)."""
        if not customer_ids:
            return []
        stmt = select(Relationship).where(
            or_(
                Relationship.entity_a.in_(customer_ids),
                Relationship.entity_b.in_(customer_ids),
            )
        )
        return list(self.session.scalars(stmt))

    def clear_all(self, *, actor_type: ActorType, actor_id: str | None) -> int:
        """NOT a general delete -- `Relationship` rows are immutable-once-
        recorded by design (see class docstring). Exists solely for the
        one-time ROADMAP Phase 8 HMAC-reconciliation script
        (`scripts/reconcile_relationship_hashes.py`), which must clear
        every row hashed under the old unsalted `value_hash` scheme before
        rerunning discovery under the new HMAC one. Not called from any
        other code path. Returns the number of rows deleted."""
        count = self.session.query(Relationship).delete()
        self.session.flush()
        append_audit_log(
            self.session,
            actor_type=actor_type,
            actor_id=actor_id,
            action="relationships_cleared_for_hmac_reconciliation",
            entity_type=self.entity_type,
            entity_id=None,
            details={"rows_deleted": count},
        )
        return count
