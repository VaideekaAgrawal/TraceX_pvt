"""
Round-trip tests for `db.repositories.investigation`: CaseRepository,
CaseAccountRepository, CaseStatusHistoryRepository, EvidenceRepository,
NoteRepository, ReportRepository, CaseFeatureVectorRepository.
"""
from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from db.enums import (
    AccountRole,
    ActorType,
    CaseLevel,
    CaseStatus,
    EvidenceType,
    NoteSource,
    Priority,
    ReportStatus,
    ReportType,
    UserRole,
)
from db.repositories.investigation import (
    CaseAccountRepository,
    CaseFeatureVectorRepository,
    CaseRepository,
    CaseStatusHistoryRepository,
    EvidenceRepository,
    NoteRepository,
    ReportRepository,
)
from db.repositories.platform import UserRepository
from db.repositories.reference import AccountRepository


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
    session.commit()


def test_case_repository_round_trip_and_list_by_assignee(session: Session) -> None:
    _seed(session)
    repo = CaseRepository(session)
    repo.create(
        case_id="CASE1",
        primary_account_id="A1",
        status=CaseStatus.NEW,
        level=CaseLevel.L1,
        priority=Priority.P2,
        assigned_to="U1",
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    session.commit()

    assert repo.get("CASE1") is not None
    assert [c.case_id for c in repo.list_by_assignee("U1")] == ["CASE1"]
    assert repo.list_by_assignee("U1", statuses=[CaseStatus.CLOSED_FP]) == []

    updated = repo.update(
        "CASE1",
        assigned_to=None,
        actor_type=ActorType.INVESTIGATOR,
        actor_id="U1",
    )
    session.commit()
    assert updated.assigned_to is None
    assert repo.list_by_assignee("U1") == []

    # Status can only change via `set_status_for_transition` (code-review
    # finding, Phase 4: `update()` no longer accepts a `status` kwarg at
    # all -- see `test_case_repository_update_rejects_status_kwarg`).
    updated = repo.set_status_for_transition(
        "CASE1",
        status=CaseStatus.IN_PROGRESS,
        action="case_status_changed",
        actor_type=ActorType.INVESTIGATOR,
        actor_id="U1",
    )
    session.commit()
    assert updated.status == CaseStatus.IN_PROGRESS
    assert [c.case_id for c in repo.list_by_status(CaseStatus.IN_PROGRESS)] == ["CASE1"]


def test_case_account_repository_round_trip(session: Session) -> None:
    _seed(session)
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

    repo = CaseAccountRepository(session)
    case_account = repo.add_account(
        case_id="CASE1",
        account_id="A1",
        role=AccountRole.SOURCE,
        hop_distance=0,
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    session.commit()

    assert repo.get(case_account.id) is not None
    assert [ca.account_id for ca in repo.list_for_case("CASE1")] == ["A1"]

    updated = repo.update(
        case_account.id, role=AccountRole.MULE, actor_type=ActorType.SYSTEM, actor_id=None
    )
    session.commit()
    assert updated.role == AccountRole.MULE


def test_case_status_history_repository_record_and_list(session: Session) -> None:
    _seed(session)
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

    repo = CaseStatusHistoryRepository(session)
    repo.record_transition(
        case_id="CASE1",
        from_status=None,
        to_status=CaseStatus.NEW,
        changed_by="U1",
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    repo.record_transition(
        case_id="CASE1",
        from_status=CaseStatus.NEW,
        to_status=CaseStatus.ASSIGNED,
        changed_by="U1",
        actor_type=ActorType.INVESTIGATOR,
        actor_id="U1",
    )
    session.commit()

    history = repo.list_for_case("CASE1")
    assert [h.to_status for h in history] == [CaseStatus.NEW, CaseStatus.ASSIGNED]


def test_case_repository_update_action_override(session: Session) -> None:
    from db.repositories.platform import AuditLogRepository

    _seed(session)
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

    repo = CaseRepository(session)
    repo.update(
        "CASE1",
        priority=Priority.P1,
        action="escalated",
        actor_type=ActorType.INVESTIGATOR,
        actor_id="U1",
    )
    session.commit()

    actions = [r.action for r in AuditLogRepository(session).list_for_case("CASE1")]
    assert "escalated" in actions
    assert "case_updated" not in actions


def test_case_repository_update_rejects_status_kwarg(session: Session) -> None:
    """Code-review finding, Phase 4: `Case.status` can only change via
    `set_status_for_transition` -- `update()` must not accept `status` at
    all (structural, not just conventional, lockout)."""
    _seed(session)
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

    with pytest.raises(TypeError):
        CaseRepository(session).update(
            "CASE1",
            status=CaseStatus.ASSIGNED,  # type: ignore[call-arg]
            actor_type=ActorType.SYSTEM,
            actor_id=None,
        )


def test_case_repository_set_status_for_transition_bundles_extra_fields(
    session: Session,
) -> None:
    from db.repositories.platform import AuditLogRepository

    _seed(session)
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

    repo = CaseRepository(session)
    updated = repo.set_status_for_transition(
        "CASE1",
        status=CaseStatus.ASSIGNED,
        action="case_assigned",
        assigned_to="U1",
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    session.commit()

    assert updated.status == CaseStatus.ASSIGNED
    assert updated.assigned_to == "U1"

    # Exactly one audit row for this bundled write, not two.
    rows = AuditLogRepository(session).list_for_case("CASE1")
    assigned_rows = [r for r in rows if r.action == "case_assigned"]
    assert len(assigned_rows) == 1


def test_evidence_repository_pin(session: Session) -> None:
    _seed(session)
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

    repo = EvidenceRepository(session)
    repo.create(
        evidence_id="EV1",
        case_id="CASE1",
        type=EvidenceType.ACCOUNT,
        added_by="U1",
        pinned=False,
        actor_type=ActorType.INVESTIGATOR,
        actor_id="U1",
    )
    session.commit()

    from db.repositories.platform import AuditLogRepository

    pinned = repo.pin("EV1", actor_type=ActorType.INVESTIGATOR, actor_id="U1")
    session.commit()
    assert pinned.pinned is True
    assert [e.evidence_id for e in repo.list_pinned_for_case("CASE1")] == ["EV1"]

    actions = [r.action for r in AuditLogRepository(session).list_for_entity("evidence", "EV1")]
    assert "evidence_pinned" in actions


def test_evidence_repository_round_trip(session: Session) -> None:
    _seed(session)
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

    repo = EvidenceRepository(session)
    repo.create(
        evidence_id="EV1",
        case_id="CASE1",
        type=EvidenceType.ACCOUNT,
        added_by="U1",
        actor_type=ActorType.INVESTIGATOR,
        actor_id="U1",
    )
    session.commit()

    assert repo.get("EV1") is not None
    assert repo.list_pinned_for_case("CASE1") == []

    updated = repo.update("EV1", pinned=True, actor_type=ActorType.INVESTIGATOR, actor_id="U1")
    session.commit()
    assert updated.pinned is True
    assert [e.evidence_id for e in repo.list_pinned_for_case("CASE1")] == ["EV1"]
    assert [e.evidence_id for e in repo.list_for_case("CASE1")] == ["EV1"]


def test_note_repository_round_trip(session: Session) -> None:
    _seed(session)
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

    repo = NoteRepository(session)
    repo.create(
        note_id="N1",
        case_id="CASE1",
        author_id="U1",
        source=NoteSource.INVESTIGATOR,
        body="Initial read.",
        actor_type=ActorType.INVESTIGATOR,
        actor_id="U1",
    )
    session.commit()

    assert repo.get("N1") is not None
    updated = repo.update(
        "N1", body="Revised read.", actor_type=ActorType.INVESTIGATOR, actor_id="U1"
    )
    session.commit()
    assert updated.body == "Revised read."
    assert [n.note_id for n in repo.list_for_case("CASE1")] == ["N1"]


def test_report_repository_round_trip(session: Session) -> None:
    _seed(session)
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

    repo = ReportRepository(session)
    repo.create(
        report_id="REP1",
        case_id="CASE1",
        type=ReportType.SAR,
        status=ReportStatus.DRAFT,
        generated_by="U1",
        actor_type=ActorType.INVESTIGATOR,
        actor_id="U1",
    )
    session.commit()

    assert repo.get("REP1") is not None
    updated = repo.update(
        "REP1",
        status=ReportStatus.FINALIZED,
        actor_type=ActorType.ADMIN,
        actor_id="U1",
    )
    session.commit()
    assert updated.status == ReportStatus.FINALIZED
    assert [r.report_id for r in repo.list_for_case("CASE1")] == ["REP1"]


def test_case_feature_vector_repository_upsert_round_trip(session: Session) -> None:
    _seed(session)
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

    repo = CaseFeatureVectorRepository(session)
    repo.upsert(
        case_id="CASE1",
        vector=[0.0] * 16,
        typology="layering",
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    session.commit()

    fetched = repo.get("CASE1")
    assert fetched is not None
    assert fetched.vector == [0.0] * 16

    updated = repo.upsert(
        case_id="CASE1",
        vector=[1.0] * 16,
        typology="layering",
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    session.commit()
    assert updated.vector == [1.0] * 16
