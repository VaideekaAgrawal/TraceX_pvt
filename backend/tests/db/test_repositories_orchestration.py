"""
Round-trip tests for `db.repositories.orchestration`: AiInteractionRepository,
RelationshipRepository.
"""
from __future__ import annotations

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
