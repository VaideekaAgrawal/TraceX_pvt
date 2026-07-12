"""
`investigation.similar_cases` -- cosine similarity over the RL 16-dim
`case_feature_vector` corpus. Builds real closed cases via `close_case`
(the only writer of a real case's `case_feature_vector` row, ROADMAP
Phase 7) rather than hand-inserting `CaseFeatureVector` rows directly, so
these tests exercise the actual corpus-population path, not just the
retrieval math in isolation.
"""
from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from db.enums import (
    ActorType,
    CaseResolution,
    CaseStatus,
    DetectionType,
    Priority,
    RiskLevel,
    UserRole,
)
from db.repositories.detection import AlertRepository
from db.repositories.investigation import CaseFeatureVectorRepository, CaseRepository
from db.repositories.platform import UserRepository
from db.repositories.reference import AccountRepository
from detection.rl.bandit import LinUCBAgent
from investigation.cases import case_rl_features, close_case, create_case_from_alert
from investigation.fsm import transition_case
from investigation.similar_cases import _cosine_similarity, compute_query_vector, find_similar_cases


def _seed_accounts(session: Session, *account_ids: str) -> None:
    repo = AccountRepository(session)
    for account_id in account_ids:
        repo.create(account_id=account_id, actor_type=ActorType.SYSTEM, actor_id=None)


def _ensure_investigator(session: Session, user_id: str = "U1") -> None:
    """Idempotent -- `_seed_and_close_case` may be called several times in
    one test/session, but `auto_assign` only needs one active investigator
    to exist at all."""
    if UserRepository(session).get(user_id) is None:
        UserRepository(session).create(
            user_id=user_id,
            username=user_id.lower(),
            email=f"{user_id.lower()}@example.com",
            password_hash="x",
            role=UserRole.INVESTIGATOR,
            full_name=user_id,
            actor_type=ActorType.SYSTEM,
            actor_id=None,
        )


def _seed_and_close_case(
    session: Session,
    *,
    case_id_seed: str,
    account_id: str,
    detection_type: DetectionType,
    risk_score: float,
    resolution: CaseResolution,
) -> str:
    """Create a case from a fresh alert, walk it to a legal pre-close
    status, and close it with `resolution` -- returns the case_id."""
    _ensure_investigator(session)
    _seed_accounts(session, account_id)
    alert = AlertRepository(session).create(
        alert_id=f"AL_{case_id_seed}",
        detection_type=detection_type,
        primary_account_id=account_id,
        account_ids=[account_id],
        score=0.9,
        risk_score=risk_score,
        severity=RiskLevel.HIGH,
        priority=Priority.P1,
        status="open",
        source="pipeline",
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    session.commit()

    case = create_case_from_alert(session, alert, actor_type=ActorType.SYSTEM, actor_id=None)
    session.commit()

    if resolution is CaseResolution.FALSE_POSITIVE:
        transition_case(
            session, case.case_id, CaseStatus.IN_PROGRESS,
            actor_type=ActorType.INVESTIGATOR, actor_id="U1",
        )
    else:
        transition_case(
            session, case.case_id, CaseStatus.IN_PROGRESS,
            actor_type=ActorType.INVESTIGATOR, actor_id="U1",
        )
        transition_case(
            session, case.case_id, CaseStatus.AWAITING_REVIEW,
            actor_type=ActorType.INVESTIGATOR, actor_id="U1",
        )
    session.commit()

    close_case(
        session, case.case_id, resolution,
        actor_type=ActorType.INVESTIGATOR, actor_id="U1",
    )
    session.commit()
    return case.case_id


def test_close_case_persists_case_feature_vector_for_a_real_case(session: Session) -> None:
    case_id = _seed_and_close_case(
        session,
        case_id_seed="A",
        account_id="ACC_A",
        detection_type=DetectionType.layering,
        risk_score=80.0,
        resolution=CaseResolution.TRUE_POSITIVE_SAR,
    )

    row = CaseFeatureVectorRepository(session).get(case_id)
    assert row is not None
    assert row.outcome == CaseResolution.TRUE_POSITIVE_SAR
    assert row.typology == "layering"
    assert len(row.vector) == 16


def test_compute_query_vector_matches_case_rl_features_build_context(session: Session) -> None:
    case_id = _seed_and_close_case(
        session,
        case_id_seed="B",
        account_id="ACC_B",
        detection_type=DetectionType.round_trip,
        risk_score=55.0,
        resolution=CaseResolution.FALSE_POSITIVE,
    )
    case = CaseRepository(session).get(case_id)
    assert case is not None

    query_vector = compute_query_vector(
        session, case, actor_type=ActorType.SYSTEM, actor_id=None
    )
    agent = LinUCBAgent(session)
    expected = agent.build_context(case_rl_features(case)).tolist()
    assert query_vector == expected


def test_cosine_similarity_zero_vector_returns_zero() -> None:
    zeros = [0.0] * 16
    other = [1.0] * 16
    assert _cosine_similarity(zeros, other) == 0.0
    assert _cosine_similarity(other, zeros) == 0.0
    assert _cosine_similarity(zeros, zeros) == 0.0


def test_cosine_similarity_identical_vectors_is_one() -> None:
    v = [0.2, 0.4, 0.6, 1.0] + [0.0] * 12
    assert _cosine_similarity(v, v) == pytest.approx(1.0)


def test_find_similar_cases_ranks_closer_case_higher_and_excludes_self(
    session: Session,
) -> None:
    close_match = _seed_and_close_case(
        session,
        case_id_seed="CLOSE",
        account_id="ACC_CLOSE",
        detection_type=DetectionType.layering,
        risk_score=82.0,
        resolution=CaseResolution.TRUE_POSITIVE_SAR,
    )
    far_match = _seed_and_close_case(
        session,
        case_id_seed="FAR",
        account_id="ACC_FAR",
        detection_type=DetectionType.dormancy,
        risk_score=18.0,
        resolution=CaseResolution.FALSE_POSITIVE,
    )

    # Query case: same typology/risk-score neighborhood as `close_match`.
    query_case_id = _seed_and_close_case(
        session,
        case_id_seed="QUERY",
        account_id="ACC_QUERY",
        detection_type=DetectionType.layering,
        risk_score=80.0,
        resolution=CaseResolution.TRUE_POSITIVE_SAR,
    )

    results = find_similar_cases(
        session, query_case_id, top_k=5, actor_type=ActorType.SYSTEM, actor_id=None
    )

    result_ids = [r.case_id for r in results]
    assert query_case_id not in result_ids  # never matches against itself
    assert close_match in result_ids
    assert far_match in result_ids
    # Not all similarity scores are identical/pinned -- real variance.
    assert len({r.similarity for r in results}) > 1
    assert result_ids.index(close_match) < result_ids.index(far_match)


def test_find_similar_cases_raises_on_unknown_case(session: Session) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        find_similar_cases(
            session, "NOPE", actor_type=ActorType.SYSTEM, actor_id=None
        )


def test_find_similar_cases_clamps_top_k(session: Session) -> None:
    query_case_id = _seed_and_close_case(
        session,
        case_id_seed="Q2",
        account_id="ACC_Q2",
        detection_type=DetectionType.structuring,
        risk_score=70.0,
        resolution=CaseResolution.ENHANCED_MONITORING,
    )
    for i in range(3):
        _seed_and_close_case(
            session,
            case_id_seed=f"C2_{i}",
            account_id=f"ACC_C2_{i}",
            detection_type=DetectionType.structuring,
            risk_score=60.0 + i,
            resolution=CaseResolution.TRUE_POSITIVE_SAR,
        )

    results_over = find_similar_cases(
        session, query_case_id, top_k=999, actor_type=ActorType.SYSTEM, actor_id=None
    )
    assert len(results_over) <= 20
    assert len(results_over) == 3  # clamp doesn't invent corpus rows

    results_under = find_similar_cases(
        session, query_case_id, top_k=0, actor_type=ActorType.SYSTEM, actor_id=None
    )
    assert len(results_under) == 1  # clamped to _MIN_TOP_K
