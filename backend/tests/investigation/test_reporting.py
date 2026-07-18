"""STR/SAR report generation + lifecycle — ROADMAP Phase 11. The narrative
(the LLM call) is monkeypatched, so these never bill; they exercise the
JSON+SHA-256 record, the PDF artifact, and the DRAFT->FINALIZED->SUBMITTED
state machine."""
from __future__ import annotations

import hashlib
import os
from typing import Any

import pytest
from sqlalchemy.orm import Session

from db.enums import (
    ActorType,
    CaseLevel,
    CaseStatus,
    DetectionType,
    Priority,
    ReportStatus,
    ReportType,
    RiskLevel,
)
from db.repositories.detection import AlertRepository
from db.repositories.investigation import CaseAccountRepository, CaseRepository
from db.repositories.reference import AccountRepository
from foundation.config import Settings
from investigation import reporting
from orchestration.report_narrative import NarrativeResult

CASE = "CASE-RPT-1"
ACC = "ACC-RPT-1"
_SYS: dict[str, Any] = {"actor_type": ActorType.SYSTEM, "actor_id": None}


@pytest.fixture
def case_with_alert(session: Session) -> Session:
    AccountRepository(session).create(account_id=ACC, branch_city="Mumbai", **_SYS)
    CaseRepository(session).create(
        case_id=CASE, primary_account_id=ACC, status=CaseStatus.IN_PROGRESS,
        level=CaseLevel.L2, priority=Priority.P1, risk_score=80.0, network_risk_score=42.0,
        assigned_to="U1", **_SYS,
    )
    CaseAccountRepository(session).add_account(case_id=CASE, account_id=ACC, **_SYS)
    AlertRepository(session).create(
        alert_id="AL-RPT-1", detection_type=DetectionType.layering, primary_account_id=ACC,
        account_ids=[ACC], score=0.8, risk_score=80.0, severity=RiskLevel.HIGH,
        priority=Priority.P1, status="open", source="pipeline", case_id=CASE, **_SYS,
    )
    session.commit()
    return session


def _mock_narrative(text: str = "Account ACC-RPT-1 moved 500000 through a 3-hop chain."):
    return lambda *a, **k: NarrativeResult(
        narrative=text, grounded=True, facts={"x": 1}, tools_called=[], rejected_reasons=[],
    )


def _gen(session: Session, monkeypatch: pytest.MonkeyPatch, **kw):
    monkeypatch.setattr(reporting, "generate_case_narrative", _mock_narrative(**kw))
    report, _ = reporting.generate_report(
        session, CASE, ReportType.STR, settings=Settings(),
        actor_type=ActorType.INVESTIGATOR, actor_id="U1",
    )
    session.commit()
    return report


def test_generate_produces_draft_with_hash_and_pdf(
    case_with_alert: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = _gen(case_with_alert, monkeypatch)
    assert report.status == ReportStatus.DRAFT
    assert report.type == ReportType.STR
    assert "500000" in report.narrative
    # the hash is a real SHA-256 of the canonical payload (tamper-evident)
    assert report.json_hash == hashlib.sha256(report.json_payload.encode()).hexdigest()
    # the PDF artifact exists on disk
    assert report.pdf_path and os.path.exists(report.pdf_path)
    with open(report.pdf_path, "rb") as fh:
        assert fh.read(4) == b"%PDF"


def test_editing_a_draft_rehashes(
    case_with_alert: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = _gen(case_with_alert, monkeypatch)
    old_hash = report.json_hash
    edited = reporting.edit_narrative(
        case_with_alert, report.report_id, "Corrected narrative with 250000 total.",
        actor_type=ActorType.INVESTIGATOR, actor_id="U1",
    )
    case_with_alert.commit()
    assert edited.narrative is not None and edited.json_payload is not None
    assert "250000" in edited.narrative
    assert edited.json_hash != old_hash
    assert edited.json_hash == hashlib.sha256(edited.json_payload.encode()).hexdigest()


def test_lifecycle_draft_finalize_submit(
    case_with_alert: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = _gen(case_with_alert, monkeypatch)
    rid = report.report_id
    finalized = reporting.finalize_report(
        case_with_alert, rid, actor_type=ActorType.INVESTIGATOR, actor_id="U1"
    )
    assert finalized.status == ReportStatus.FINALIZED
    submitted = reporting.submit_report(
        case_with_alert, rid, "FIU-2026-00042", actor_type=ActorType.INVESTIGATOR, actor_id="U1"
    )
    assert submitted.status == ReportStatus.SUBMITTED
    assert submitted.fiu_reference == "FIU-2026-00042"
    assert submitted.submitted_at is not None


def test_cannot_edit_a_finalized_report(
    case_with_alert: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = _gen(case_with_alert, monkeypatch)
    reporting.finalize_report(
        case_with_alert, report.report_id, actor_type=ActorType.INVESTIGATOR, actor_id="U1"
    )
    with pytest.raises(reporting.ReportStateError):
        reporting.edit_narrative(
            case_with_alert, report.report_id, "too late",
            actor_type=ActorType.INVESTIGATOR, actor_id="U1",
        )


def test_cannot_submit_a_draft(
    case_with_alert: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = _gen(case_with_alert, monkeypatch)
    with pytest.raises(reporting.ReportStateError):
        reporting.submit_report(
            case_with_alert, report.report_id, "FIU-X",
            actor_type=ActorType.INVESTIGATOR, actor_id="U1",
        )
