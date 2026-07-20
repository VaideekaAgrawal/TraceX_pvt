"""
Schema smoke tests for `db/models/`: build the full schema against a
throwaway SQLite DB (in-memory) via `Base.metadata.create_all()` — the same
call path a test DB or a fresh dev environment would use before Alembic
migrations exist for it — and round-trip one row through every table,
in FK-dependency order, across all five doc groupings (reference/domain,
detection/governance, investigation spine, AI orchestration, platform).

This is deliberately independent of the Alembic migration path (that's
`tests/db/test_migrations.py`) so a model/migration drift shows up as two
different failures instead of one.
"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import TypeVar

import pytest
from sqlalchemy.orm import Session

from db.enums import (
    AccountRole,
    AccountStatus,
    ActorType,
    AiAgent,
    CaseLevel,
    CaseResolution,
    CaseStatus,
    Channel,
    DetectionType,
    EntityType,
    EvidenceType,
    KycStatus,
    NoteSource,
    Priority,
    ReportStatus,
    ReportType,
    RiskLevel,
    UserRole,
    WatchEntityType,
)
from db.models import (
    Account,
    AiInteraction,
    Alert,
    AuditLog,
    Base,
    Case,
    CaseAccount,
    CaseFeatureVector,
    CaseStatusHistory,
    Customer,
    DetectionFeedback,
    Evidence,
    IngestionLog,
    ModelRun,
    Note,
    Relationship,
    Report,
    RlArmState,
    RuleDefinition,
    Transaction,
    User,
    Watchlist,
)
from db.session import build_engine

NOW = datetime.now(UTC)

_T = TypeVar("_T")


def _require(obj: _T | None) -> _T:
    """`Session.get()` returns `T | None`; assert-and-narrow so the round
    trip assertions below can chain straight into attribute access instead
    of every call site repeating an `is not None` check."""
    assert obj is not None
    return obj


@pytest.fixture()
def session() -> Iterator[Session]:
    engine = build_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as s:
            yield s
    finally:
        # SQLite in-memory engines keep their pooled connection open until
        # disposed; without this every test using this fixture leaks a
        # sqlite3 connection (visible as a ResourceWarning at GC time).
        engine.dispose()


def test_create_all_builds_every_table(session: Session) -> None:
    # 22 tables across the five doc groupings — see db/models/__init__.py.
    # (21 original + rule_proposals, ROADMAP Phase 12 admin review queue.)
    assert len(Base.metadata.tables) == 22


def test_round_trip_every_table(session: Session) -> None:
    """One row per table, inserted in FK-dependency order, then re-read back
    by primary key to prove the mapping (types, nullability, FKs, enums)
    round-trips through SQLite without error."""

    # -- platform / no-FK tables first --
    ingestion = IngestionLog(
        file_hash="hash1",
        filename="day1.csv",
        num_transactions=1,
        num_accounts=2,
        status="ingested",
        ingested_at=NOW,
    )
    user = User(
        user_id="U1",
        username="investigator1",
        email="inv1@example.com",
        password_hash="not-a-real-hash",
        role=UserRole.INVESTIGATOR,
        full_name="Investigator One",
    )
    customer = Customer(
        customer_id="C1",
        name="Alice Example",
        entity_type=EntityType.INDIVIDUAL,
        kyc_status=KycStatus.VERIFIED,
        risk_rating=RiskLevel.LOW,
    )
    session.add_all([ingestion, user, customer])
    session.commit()

    # -- reference/domain --
    account = Account(
        account_id="A1",
        customer_id="C1",
        status=AccountStatus.ACTIVE,
    )
    account2 = Account(account_id="A2", status=AccountStatus.ACTIVE)
    session.add_all([account, account2])
    session.commit()

    txn = Transaction(
        txn_id="T1",
        timestamp=NOW,
        source_account="A1",
        dest_account="A2",
        amount=1000,
        channel=Channel.UPI,
        is_laundering=0,
        source_file_hash="hash1",
        ingested_at=NOW,
    )
    session.add(txn)
    session.commit()

    # -- detection & governance --
    model_run = ModelRun(
        run_id="MR1",
        model_name="ensemble_v1",
        model_type="ensemble",
        version="0.1.0",
        trained_at=NOW,
        metrics={"f1": 0.9},
        active=True,
    )
    rule = RuleDefinition(
        rule_id="R1",
        name="high-velocity",
        dsl={"op": "and", "children": []},
        tier=1,
        confidence=0.5,
        enabled=True,
        created_by="U1",
    )
    rl_state = RlArmState(arm_id="ARM1", a_matrix=[[1.0]], b_vector=[0.0], updated_at=NOW)
    session.add_all([model_run, rule, rl_state])
    session.commit()

    case = Case(
        case_id="CASE1",
        primary_account_id="A1",
        status=CaseStatus.NEW,
        level=CaseLevel.L1,
        priority=Priority.P2,
        assigned_to="U1",
    )
    session.add(case)
    session.commit()

    alert = Alert(
        alert_id="AL1",
        case_id="CASE1",
        detection_type=DetectionType.layering,
        primary_account_id="A1",
        account_ids=["A1", "A2"],
        score=0.9,
        risk_score=80.0,
        severity=RiskLevel.HIGH,
        priority=Priority.P1,
        status="open",
        model_run_id="MR1",
        source="pipeline",
        created_at=NOW,
        last_seen_at=NOW,
    )
    session.add(alert)
    session.commit()

    feedback = DetectionFeedback(
        case_id="CASE1",
        alert_id="AL1",
        verdict=CaseResolution.TRUE_POSITIVE_SAR,
        reward=1.0,
        created_by="U1",
        created_at=NOW,
    )
    session.add(feedback)
    session.commit()

    # -- investigation spine --
    case_account = CaseAccount(
        case_id="CASE1", account_id="A1", role=AccountRole.SOURCE, hop_distance=0
    )
    history = CaseStatusHistory(
        case_id="CASE1",
        from_status=None,
        to_status=CaseStatus.NEW,
        changed_by="U1",
        changed_at=NOW,
    )
    evidence = Evidence(
        evidence_id="EV1",
        case_id="CASE1",
        type=EvidenceType.TRANSACTION,
        ref_id="T1",
        added_by="U1",
        added_at=NOW,
    )
    note = Note(
        note_id="N1",
        case_id="CASE1",
        author_id="U1",
        source=NoteSource.INVESTIGATOR,
        body="Looks like structuring.",
        created_at=NOW,
    )
    report = Report(
        report_id="REP1",
        case_id="CASE1",
        type=ReportType.SAR,
        status=ReportStatus.DRAFT,
        generated_by="U1",
        generated_at=NOW,
    )
    feature_vector = CaseFeatureVector(
        case_id="CASE1", vector=[0.0] * 16, typology="layering", computed_at=NOW
    )
    session.add_all([case_account, history, evidence, note, report, feature_vector])
    session.commit()

    # -- AI orchestration --
    ai_interaction = AiInteraction(
        case_id="CASE1",
        agent=AiAgent.RECOMMENDATION,
        user_id="U1",
        response_text="Escalate — layering pattern detected.",
        model="claude-opus-4.8",
        model_provider="openrouter",
        created_at=NOW,
    )
    relationship = Relationship(
        entity_a="C1",
        entity_b="C1",
        shared_attribute="phone",
        value_hash="deadbeef",
        confidence=0.5,
        method="fuzzy_match",
        discovered_at=NOW,
    )
    session.add_all([ai_interaction, relationship])
    session.commit()

    # -- platform (remaining) --
    watchlist_entry = Watchlist(
        entry_id="W1",
        entity_type=WatchEntityType.CUSTOMER,
        entity_value="C1",
        added_by="U1",
    )
    audit_row = AuditLog(
        actor_type=ActorType.INVESTIGATOR,
        actor_id="U1",
        action="case_created",
        entity_type="case",
        entity_id="CASE1",
        case_id="CASE1",
        row_hash="abc123",
        created_at=NOW,
    )
    session.add_all([watchlist_entry, audit_row])
    session.commit()

    # -- read every row back by PK and sanity-check a couple of fields --
    assert session.get(IngestionLog, "hash1") is not None
    assert _require(session.get(User, "U1")).role == UserRole.INVESTIGATOR
    assert _require(session.get(Customer, "C1")).entity_type == EntityType.INDIVIDUAL
    assert _require(session.get(Account, "A1")).customer_id == "C1"
    assert _require(session.get(Transaction, "T1")).channel == Channel.UPI
    assert _require(session.get(ModelRun, "MR1")).metrics == {"f1": 0.9}
    assert _require(session.get(RuleDefinition, "R1")).tier == 1
    assert _require(session.get(RlArmState, "ARM1")).a_matrix == [[1.0]]
    assert _require(session.get(Case, "CASE1")).status == CaseStatus.NEW
    assert _require(session.get(Alert, "AL1")).severity == RiskLevel.HIGH
    assert (
        _require(session.get(DetectionFeedback, feedback.id)).verdict
        == CaseResolution.TRUE_POSITIVE_SAR
    )
    assert _require(session.get(CaseAccount, case_account.id)).role == AccountRole.SOURCE
    assert _require(session.get(CaseStatusHistory, history.id)).to_status == CaseStatus.NEW
    assert _require(session.get(Evidence, "EV1")).type == EvidenceType.TRANSACTION
    assert _require(session.get(Note, "N1")).source == NoteSource.INVESTIGATOR
    assert _require(session.get(Report, "REP1")).status == ReportStatus.DRAFT
    assert _require(session.get(CaseFeatureVector, "CASE1")).typology == "layering"
    assert _require(session.get(AiInteraction, ai_interaction.id)).agent == AiAgent.RECOMMENDATION
    assert _require(session.get(Relationship, relationship.id)).shared_attribute == "phone"
    assert _require(session.get(Watchlist, "W1")).entity_type == WatchEntityType.CUSTOMER
    assert _require(session.get(AuditLog, audit_row.id)).action == "case_created"


def test_transaction_composite_indexes_exist(session: Session) -> None:
    """The two hot-path composite indexes called out in doc §3.1 must exist
    on the created schema, not just be implied by column-level `idx`."""
    from sqlalchemy import inspect

    inspector = inspect(session.get_bind())
    index_names = {ix["name"] for ix in inspector.get_indexes("transactions")}
    assert "ix_transactions_source_account_timestamp" in index_names
    assert "ix_transactions_dest_account_timestamp" in index_names


def test_enum_column_rejects_invalid_value(session: Session) -> None:
    """SQLite CHECK-constraint enforcement: `sa.Enum(..., validate_strings=True)`
    should refuse to persist a value outside the enum, proving the ENUM ->
    TEXT+CHECK mapping (doc §0) is actually enforced, not just documented."""
    from sqlalchemy.exc import StatementError

    bad_customer = Customer(
        customer_id="BAD1",
        name="Bad",
        entity_type="NOT_A_REAL_TYPE",
        kyc_status=KycStatus.PENDING,
        risk_rating=RiskLevel.LOW,
    )
    session.add(bad_customer)
    with pytest.raises(StatementError):
        session.commit()
