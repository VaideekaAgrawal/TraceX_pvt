"""
Coverage for `demo_data.seed.run_demo_data_studio`: idempotency (a second
run against the same DB is a true no-op), the `DEMO-` prefix invariant
across every id this package creates, that `case_feature_vector` rows are
exactly 16-length (the RL context vector's dimensionality, `detection.rl.
bandit.LinUCBAgent.FEATURE_NAMES`), and (ROADMAP Phase 7) that the
`relationship_discovery` stage genuinely rediscovers Phase 1B's seeded
shared-attribute clusters into real `relationships` rows.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db.enums import ActorType
from db.models.detection import DetectionFeedback, RlArmState
from db.models.investigation import CaseFeatureVector, CaseStatusHistory
from db.models.orchestration import Relationship
from db.models.platform import AuditLog, IngestionLog, Watchlist
from db.models.reference import Account, Customer, Transaction
from demo_data.config import DEMO_PREFIX
from demo_data.seed import run_demo_data_studio

_ACTOR_ID = "test-demo-data-studio"

#: Phase 8 (decision 9): the relationship-discovery stage's `value_hash` is now a
#: keyed HMAC. Any non-empty key works here — these tests assert seeding, not the
#: hash itself (that's `tests/investigation/test_value_hash_hmac.py`). An EMPTY key
#: is deliberately refused rather than degraded to an unkeyed digest.
_TEST_HMAC_KEY = "test-pii-hmac-key"


def _row_counts(session: Session) -> dict[str, int]:
    """Row counts for every table this package writes to (directly or via
    `case_status_history`/`detection_feedback`/`rl_arm_state`/
    `relationships`) -- used to prove a second run inserts zero new rows
    anywhere it touches."""
    tables = {
        "customers": Customer,
        "accounts": Account,
        "transactions": Transaction,
        "case_status_history": CaseStatusHistory,
        "case_feature_vector": CaseFeatureVector,
        "detection_feedback": DetectionFeedback,
        "rl_arm_state": RlArmState,
        "relationships": Relationship,
        "watchlist": Watchlist,
        "ingestion_log": IngestionLog,
        "audit_log": AuditLog,
    }
    counts: dict[str, int] = {}
    for name, model in tables.items():
        result = session.scalar(select(func.count()).select_from(model))
        counts[name] = result if result is not None else 0
    return counts


def test_run_demo_data_studio_second_run_is_true_noop(session: Session) -> None:
    first_summary = run_demo_data_studio(
        session, actor_type=ActorType.SYSTEM, actor_id=_ACTOR_ID, hmac_key=_TEST_HMAC_KEY
    )
    session.commit()

    assert first_summary.kyc_customers_created > 0
    assert first_summary.relationship_clusters_created > 0
    assert first_summary.relationships_discovered > 0
    assert first_summary.historical_cases_created > 0
    assert first_summary.golden_scenarios_created == 7
    assert first_summary.already_seeded == []

    counts_after_first = _row_counts(session)

    second_summary = run_demo_data_studio(
        session, actor_type=ActorType.SYSTEM, actor_id=_ACTOR_ID, hmac_key=_TEST_HMAC_KEY
    )
    session.commit()

    assert second_summary.kyc_customers_created == 0
    assert second_summary.planted_scenarios_created == 0
    assert second_summary.relationship_clusters_created == 0
    assert second_summary.relationships_discovered == 0
    assert second_summary.historical_cases_created == 0
    assert second_summary.golden_scenarios_created == 0
    assert set(second_summary.already_seeded) == {
        "kyc_customers", "pilot_transactions", "relationships", "relationship_discovery",
        "historical_cases", "golden_scenarios",
    }

    counts_after_second = _row_counts(session)
    assert counts_after_second == counts_after_first


def test_relationship_discovery_rediscovers_seeded_clusters(session: Session) -> None:
    """PAN collisions across the ~200-strong KYC pool are effectively
    impossible outside a deliberately-seeded Phase 1B cluster (5 random
    uppercase letters + index + checksum letter, per `demo_data.
    kyc_customers._synthetic_pan`) -- so any discovered `shared_attribute
    ="pan"` relationship IS evidence a seeded cluster was genuinely
    rediscovered, not a coincidental collision. Only `pan` and `name` are
    rediscoverable: `income_bracket`/`branch` were removed as demographic noise
    (owner review), and `phone`/`email`/`address`/`employer` were never in
    Relationship Explorer v1's locked scope (`docs/DATA_SCHEMA.md`)."""
    run_demo_data_studio(
        session, actor_type=ActorType.SYSTEM, actor_id=_ACTOR_ID, hmac_key=_TEST_HMAC_KEY
    )
    session.commit()

    by_attribute: dict[str, list[Relationship]] = {}
    for rel in session.scalars(select(Relationship)):
        by_attribute.setdefault(rel.shared_attribute, []).append(rel)

    # Only real coordination signals — a shared income bracket / branch city is
    # not a relationship any more.
    assert set(by_attribute) <= {"pan", "name"}
    assert len(by_attribute.get("pan", [])) > 0
    assert "income_bracket" not in by_attribute
    assert "branch" not in by_attribute
    for rel in by_attribute["pan"]:
        assert rel.confidence == 0.95
        assert rel.method == "shared_attribute_v1"


def test_every_created_id_is_demo_prefixed(session: Session) -> None:
    run_demo_data_studio(
        session, actor_type=ActorType.SYSTEM, actor_id=_ACTOR_ID, hmac_key=_TEST_HMAC_KEY
    )
    session.commit()

    for customer in session.scalars(select(Customer)):
        assert customer.customer_id.startswith(DEMO_PREFIX), customer.customer_id
    for account in session.scalars(select(Account)):
        assert account.account_id.startswith(DEMO_PREFIX), account.account_id
    for txn in session.scalars(select(Transaction)):
        assert txn.txn_id.startswith(DEMO_PREFIX), txn.txn_id
        assert txn.source_account.startswith(DEMO_PREFIX)
        assert txn.dest_account.startswith(DEMO_PREFIX)
    for case in session.scalars(select(CaseFeatureVector)):
        assert case.case_id.startswith(DEMO_PREFIX), case.case_id
    for watchlist_entry in session.scalars(select(Watchlist)):
        assert watchlist_entry.entry_id.startswith(DEMO_PREFIX), watchlist_entry.entry_id
    for log_row in session.scalars(select(IngestionLog)):
        assert log_row.file_hash.startswith("demo-seed:"), log_row.file_hash


def test_case_feature_vectors_are_16_dimensional(session: Session) -> None:
    run_demo_data_studio(
        session, actor_type=ActorType.SYSTEM, actor_id=_ACTOR_ID, hmac_key=_TEST_HMAC_KEY
    )
    session.commit()

    vectors = list(session.scalars(select(CaseFeatureVector)))
    assert len(vectors) > 0
    for row in vectors:
        assert len(row.vector) == 16, (row.case_id, len(row.vector))
        assert all(isinstance(v, int | float) for v in row.vector)


def test_rl_arm_state_actually_trained_by_historical_corpus(session: Session) -> None:
    """`rl_arm_state`'s persisted `a_matrix`/`b_vector` must differ from
    identity/zero after seeding -- proves `LinUCBAgent.receive_feedback` was
    genuinely called per historical case, not just labeled via
    `detection_feedback` rows for show."""
    import numpy as np

    from db.repositories.detection import RlArmStateRepository
    from detection.rl.bandit import GLOBAL_ARM_ID

    repo = RlArmStateRepository(session)
    assert repo.get(GLOBAL_ARM_ID) is None  # nothing trained yet

    run_demo_data_studio(
        session, actor_type=ActorType.SYSTEM, actor_id=_ACTOR_ID, hmac_key=_TEST_HMAC_KEY
    )
    session.commit()

    state = repo.get(GLOBAL_ARM_ID)
    assert state is not None
    assert not np.array_equal(np.array(state.a_matrix), np.identity(16))
    assert not np.array_equal(np.array(state.b_vector), np.zeros(16))
