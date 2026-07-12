"""
Round-trip tests for `db.repositories.orchestration`: AiInteractionRepository,
RelationshipRepository.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from db.enums import (
    ActorType,
    AiAgent,
    CaseLevel,
    CaseStatus,
    EntityType,
    Priority,
    RiskLevel,
    UserRole,
)
from db.repositories.investigation import CaseRepository
from db.repositories.orchestration import AiInteractionRepository, RelationshipRepository
from db.repositories.platform import UserRepository
from db.repositories.reference import AccountRepository, CustomerRepository


def _seed(session: Session) -> None:
    AccountRepository(session).create(account_id="A1", actor_type=ActorType.SYSTEM, actor_id=None)
    UserRepository(session).create(
        user_id="U1",
        username="inv1",
        email="inv1@example.com",
        password_hash="x",
        role=UserRole.INVESTIGATOR,
        full_name="Investigator One",
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    CaseRepository(session).create(
        case_id="CASE1",
        primary_account_id="A1",
        status=CaseStatus.NEW,
        level=CaseLevel.L1,
        priority=Priority.P2,
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    session.commit()


def test_ai_interaction_repository_round_trip(session: Session) -> None:
    _seed(session)
    repo = AiInteractionRepository(session)
    interaction = repo.create(
        case_id="CASE1",
        agent=AiAgent.RECOMMENDATION,
        user_id="U1",
        response_text="Escalate — layering pattern detected.",
        model="claude-opus-4.8",
        model_provider="openrouter",
        actor_type=ActorType.AI,
        actor_id="RECOMMENDATION",
    )
    session.commit()

    assert repo.get(interaction.id) is not None
    assert [i.id for i in repo.list_for_case("CASE1")] == [interaction.id]
    assert [i.id for i in repo.list_for_user("U1")] == [interaction.id]

    updated = repo.record_feedback(
        interaction.id,
        investigator_feedback="accepted",
        actor_type=ActorType.INVESTIGATOR,
        actor_id="U1",
    )
    session.commit()
    assert updated.investigator_feedback == "accepted"


def test_ai_interaction_repository_list_for_case_and_agent_filters_by_agent(
    session: Session,
) -> None:
    _seed(session)
    repo = AiInteractionRepository(session)
    rec = repo.create(
        case_id="CASE1",
        agent=AiAgent.RECOMMENDATION,
        user_id="U1",
        response_text="Explanation for A1.",
        model="claude-opus-4.8",
        model_provider="openrouter",
        facts={"account_id": "A1"},
        actor_type=ActorType.AI,
        actor_id="RECOMMENDATION",
    )
    repo.create(
        case_id="CASE1",
        agent=AiAgent.COPILOT,
        user_id="U1",
        response_text="Copilot answer.",
        model="claude-opus-4.8",
        model_provider="openrouter",
        actor_type=ActorType.AI,
        actor_id="COPILOT",
    )
    session.commit()

    recommendation_only = repo.list_for_case_and_agent("CASE1", AiAgent.RECOMMENDATION)
    assert [i.id for i in recommendation_only] == [rec.id]
    assert repo.list_for_case_and_agent("CASE1", AiAgent.COPILOT)[0].agent == AiAgent.COPILOT
    assert repo.list_for_case_and_agent("NOPE", AiAgent.RECOMMENDATION) == []


def test_ai_interaction_repository_list_for_case_and_agent_orders_most_recent_first(
    session: Session,
) -> None:
    # Regression test (code-review finding, Phase 5): without an ORDER BY
    # before LIMIT, a case with more interactions than `limit` could have
    # its kept rows be an arbitrary slice rather than the most recent ones.
    _seed(session)
    repo = AiInteractionRepository(session)
    older = repo.create(
        case_id="CASE1",
        agent=AiAgent.RECOMMENDATION,
        user_id="U1",
        response_text="Older explanation.",
        model="claude-opus-4.8",
        model_provider="openrouter",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        actor_type=ActorType.AI,
        actor_id="RECOMMENDATION",
    )
    newer = repo.create(
        case_id="CASE1",
        agent=AiAgent.RECOMMENDATION,
        user_id="U1",
        response_text="Newer explanation (e.g. from a force=True call).",
        model="claude-opus-4.8",
        model_provider="openrouter",
        created_at=datetime(2026, 6, 1, tzinfo=UTC),
        actor_type=ActorType.AI,
        actor_id="RECOMMENDATION",
    )
    session.commit()

    results = repo.list_for_case_and_agent("CASE1", AiAgent.RECOMMENDATION)
    assert [i.id for i in results] == [newer.id, older.id]


def test_ai_interaction_repository_list_for_case_and_agent_default_limit_covers_combined_volume(
    session: Session,
) -> None:
    """Regression test (code-review finding, Phase 6): once
    `orchestration.pattern_explanation` started writing into the same
    `case_id`+`AiAgent.RECOMMENDATION` namespace `orchestration.
    account_explanation` already used, the old `limit=50` default could
    silently truncate a case's combined interaction history and cause a
    spurious cache miss. Pinned here (60 > the old 50) so a future change
    can't silently shrink the default back down without a test noticing."""
    _seed(session)
    repo = AiInteractionRepository(session)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for i in range(60):
        repo.create(
            case_id="CASE1", agent=AiAgent.RECOMMENDATION, user_id="U1",
            response_text=f"Explanation {i}.", model="claude-opus-4.8",
            model_provider="openrouter", created_at=base + timedelta(hours=i),
            actor_type=ActorType.AI, actor_id="RECOMMENDATION",
        )
    session.commit()

    results = repo.list_for_case_and_agent("CASE1", AiAgent.RECOMMENDATION)
    assert len(results) == 60  # would have been truncated to 50 under the old default


def test_relationship_repository_round_trip(session: Session) -> None:
    CustomerRepository(session).create(
        customer_id="C1",
        name="Alice",
        entity_type=EntityType.INDIVIDUAL,
        risk_rating=RiskLevel.LOW,
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    CustomerRepository(session).create(
        customer_id="C2",
        name="Bob",
        entity_type=EntityType.INDIVIDUAL,
        risk_rating=RiskLevel.LOW,
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    session.commit()

    repo = RelationshipRepository(session)
    relationship = repo.create(
        entity_a="C1",
        entity_b="C2",
        shared_attribute="phone",
        value_hash="deadbeef",
        confidence=0.9,
        method="fuzzy_match",
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    session.commit()

    assert repo.get(relationship.id) is not None
    assert {r.id for r in repo.list_for_entity("C1")} == {relationship.id}
    assert {r.id for r in repo.list_for_entity("C2")} == {relationship.id}
    assert repo.list_for_entity("C3") == []
