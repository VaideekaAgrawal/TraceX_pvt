"""
`investigation.relationship_discovery.discover_relationships` -- the
Relationship Explorer v1 batch discovery job (ROADMAP Phase 7). Exercises
the confidence scheme (pan/name/income_bracket/branch), the candidate-pool
gate, idempotent reruns, the `MAX_CANDIDATE_POOL_SIZE` safety valve, and
(ROADMAP Phase 8) the HMAC-keyed `value_hash` fix.
"""
from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from db.enums import ActorType, EntityType, RiskLevel
from db.repositories.orchestration import RelationshipRepository
from db.repositories.reference import AccountRepository, CustomerRepository
from investigation import relationship_discovery as rd

_SECRET = "test-secret"


def _discover(session: Session, *, secret: str = _SECRET) -> rd.DiscoveryStats:
    return rd.discover_relationships(
        session, actor_type=ActorType.SYSTEM, actor_id=None, secret=secret
    )


def _make_customer(
    session: Session,
    customer_id: str,
    *,
    name: str = "Generic Name",
    pan: str | None = None,
    income_bracket: str | None = None,
) -> None:
    CustomerRepository(session).create(
        customer_id=customer_id,
        name=name,
        entity_type=EntityType.INDIVIDUAL,
        risk_rating=RiskLevel.MEDIUM,
        pan=pan,
        income_bracket=income_bracket,
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )


def _make_account(
    session: Session, account_id: str, customer_id: str, branch_city: str | None = None
) -> None:
    AccountRepository(session).create(
        account_id=account_id,
        customer_id=customer_id,
        branch_city=branch_city,
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )


def test_exact_pan_match_creates_high_confidence_relationship(session: Session) -> None:
    _make_customer(session, "C1", name="Amit Verma", pan=" abc1234z ")
    # normalizes (strip/upper) to the same PAN; dissimilar name so this
    # test isolates the pan match (no incidental "name" row too).
    _make_customer(session, "C2", name="Priya Nair", pan="ABC1234Z")
    session.commit()

    stats = _discover(session)
    session.commit()

    assert stats.candidate_pool_size == 2
    assert stats.relationships_created == 1

    rels = RelationshipRepository(session).list_for_entity("C1")
    assert len(rels) == 1
    assert rels[0].shared_attribute == "pan"
    assert rels[0].confidence == 0.95
    assert rels[0].method == "shared_attribute_v1"


def test_fuzzy_name_match_uses_ratio_as_confidence(session: Session) -> None:
    _make_customer(session, "C1", name="Rajesh Kumar Sharma", income_bracket="10L-25L")
    _make_customer(session, "C2", name="Rajesh Kumar Sharrma", income_bracket="10L-25L")
    session.commit()

    _discover(session)
    session.commit()

    rels = {r.shared_attribute: r for r in RelationshipRepository(session).list_for_entity("C1")}
    assert "name" in rels
    assert 0.85 <= rels["name"].confidence <= 1.0
    assert "income_bracket" in rels
    assert rels["income_bracket"].confidence == 0.35


def test_dissimilar_names_do_not_match(session: Session) -> None:
    _make_customer(session, "C1", name="Amit Verma", pan="AAAAA0001A")
    _make_customer(session, "C2", name="Priya Nair", pan="BBBBB0002B")
    session.commit()

    stats = _discover(session)
    session.commit()

    assert stats.relationships_created == 0


def test_shared_branch_city_creates_weak_confidence_relationship(session: Session) -> None:
    _make_customer(session, "C1", name="Alpha One", income_bracket="<2L")
    _make_customer(session, "C2", name="Beta Two", income_bracket="2L-5L")
    _make_account(session, "A1", "C1", branch_city="Mumbai")
    _make_account(session, "A2", "C2", branch_city="Mumbai")
    session.commit()

    _discover(session)
    session.commit()

    rels = {r.shared_attribute: r for r in RelationshipRepository(session).list_for_entity("C1")}
    assert "branch" in rels
    assert rels["branch"].confidence == 0.25


def test_candidate_pool_excludes_customers_with_neither_pan_nor_income_bracket(
    session: Session,
) -> None:
    _make_customer(session, "C1", pan="AAAAA0001A")
    _make_customer(session, "C2", pan="AAAAA0001A")
    _make_customer(session, "C_NO_SIGNAL", name="No KYC Signal")  # neither pan nor income_bracket
    session.commit()

    stats = _discover(session)
    session.commit()

    assert stats.candidate_pool_size == 2  # C_NO_SIGNAL gated out
    assert stats.pairs_compared == 1


def test_rerun_is_idempotent(session: Session) -> None:
    _make_customer(session, "C1", name="Amit Verma", pan="AAAAA0001A")
    _make_customer(session, "C2", name="Priya Nair", pan="AAAAA0001A")
    session.commit()

    first = _discover(session)
    session.commit()
    assert first.relationships_created == 1

    second = _discover(session)
    session.commit()
    assert second.relationships_created == 0
    assert second.relationships_skipped_existing == 1

    assert len(RelationshipRepository(session).list_for_entity("C1")) == 1


def test_candidate_pool_exceeding_safety_valve_raises(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rd, "MAX_CANDIDATE_POOL_SIZE", 2)
    _make_customer(session, "C1", pan="AAAAA0001A")
    _make_customer(session, "C2", pan="AAAAA0002A")
    _make_customer(session, "C3", pan="AAAAA0003A")
    session.commit()

    with pytest.raises(ValueError, match="exceeds MAX_CANDIDATE_POOL_SIZE"):
        _discover(session)


def test_value_hash_is_keyed_by_secret_not_a_bare_hash(session: Session) -> None:
    # ROADMAP Phase 8 regression test: the same shared PAN under two
    # different secrets must produce two different value_hash values --
    # proving this is an HMAC (secret-dependent), not the old unsalted
    # hashlib.sha256(value) (secret-independent, brute-forceable for
    # low-entropy PII).
    _make_customer(session, "C1", name="Amit Verma", pan="AAAAA0001A")
    _make_customer(session, "C2", name="Priya Nair", pan="AAAAA0001A")
    session.commit()

    _discover(session, secret="secret-one")
    session.commit()
    first_hash = RelationshipRepository(session).list_for_entity("C1")[0].value_hash

    RelationshipRepository(session).clear_all(actor_type=ActorType.SYSTEM, actor_id=None)
    session.commit()

    _discover(session, secret="secret-two")
    session.commit()
    second_hash = RelationshipRepository(session).list_for_entity("C1")[0].value_hash

    assert first_hash != second_hash


def test_discover_relationships_requires_a_secret_argument(session: Session) -> None:
    with pytest.raises(TypeError):
        rd.discover_relationships(  # type: ignore[call-arg]
            session, actor_type=ActorType.SYSTEM, actor_id=None
        )
