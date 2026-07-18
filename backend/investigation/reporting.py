"""STR/SAR report generation — ROADMAP Phase 11.

Turns a case into a defensible, filable artifact:

    grounded narrative (orchestration.report_narrative)
      + structured case facts (alerts, accounts, evidence, network risk)
      -> a canonical JSON payload
      -> a SHA-256 hash of that payload   (tamper-evident record)
      -> a PDF                            (human-readable artifact)
      -> a Report row, status DRAFT

The JSON payload + its SHA-256 is the load-bearing part: it is the exact,
reproducible record of what the report asserted, so any later tampering with the
narrative or the PDF is detectable by re-hashing. The status machine
(DRAFT -> FINALIZED -> SUBMITTED) mirrors real filing: an investigator edits the
DRAFT narrative, FINALIZES it (locking the content), then records SUBMITTED once
filed with FIU-IND. Editing is only allowed while DRAFT; finalizing re-hashes so
the hash always matches the frozen content.

⚠️ PROTOTYPE: the JSON shape and PDF layout are illustrative, not the actual
FIU-IND STR schema — flagged for compliance review before any real filing.
Regulatory e-filing integration is explicitly out of scope (roadmap).
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
from sqlalchemy.orm import Session

from db.enums import ActorType, ReportStatus, ReportType
from db.models.base import utcnow
from db.models.investigation import Report
from db.repositories.detection import AlertRepository
from db.repositories.investigation import (
    CaseAccountRepository,
    CaseRepository,
    EvidenceRepository,
    ReportRepository,
)
from foundation.config import Settings
from orchestration.report_narrative import generate_case_narrative

logger = logging.getLogger(__name__)

_REPORTS_DIR = Path(__file__).resolve().parents[2] / "data" / "reports"


class ReportStateError(Exception):
    """A report lifecycle action was attempted from an illegal status (e.g.
    editing a FINALIZED report, or submitting a DRAFT)."""


def _canonical_json(payload: dict[str, Any]) -> str:
    """Deterministic JSON so the SHA-256 is reproducible: sorted keys, no
    whitespace jitter. Re-serialising the same payload always yields the same
    bytes, which is what makes the hash a tamper check rather than decoration."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _build_payload(
    session: Session, case_id: str, report_type: ReportType, narrative: str
) -> dict[str, Any]:
    """The structured, hashable record behind the report. No customer names —
    the narrative and payload speak in customer_id (decision 9)."""
    case = CaseRepository(session).get(case_id)
    if case is None:
        raise ValueError(f"case {case_id!r} does not exist")
    account_ids = CaseAccountRepository(session).list_account_ids_for_case(case_id)
    alerts = AlertRepository(session).list_for_case(case_id)
    evidence = EvidenceRepository(session).list_for_case(case_id)

    return {
        "report_type": str(report_type),
        "case_id": case_id,
        "case": {
            "status": str(case.status),
            "level": str(case.level),
            "priority": str(case.priority),
            "risk_score": case.risk_score,
            "network_risk_score": case.network_risk_score,
            "primary_account_id": case.primary_account_id,
            "account_ids": account_ids,
        },
        "alerts": [
            {
                "alert_id": a.alert_id,
                "detection_type": str(a.detection_type),
                "score": a.score,
                "severity": str(a.severity),
                "account_ids": a.account_ids,
            }
            for a in alerts
        ],
        "evidence": [
            {
                "evidence_id": e.evidence_id,
                "type": str(e.type),
                "ref_id": e.ref_id,
                "label": e.label,
                "pinned": e.pinned,
            }
            for e in evidence
        ],
        "narrative": narrative,
    }


def _render_pdf(report_id: str, report_type: ReportType, payload: dict[str, Any]) -> str:
    """Render the human-readable STR/SAR PDF; returns its path. Content is driven
    entirely by `payload`, so the PDF and the hashed JSON never diverge."""
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = _REPORTS_DIR / f"{report_id}.pdf"
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(path), pagesize=A4, title=f"{report_type} {report_id}")
    flow: list[Any] = [
        Paragraph(f"Suspicious Transaction Report ({report_type})", styles["Title"]),
        Paragraph(f"Report ID: {report_id}", styles["Normal"]),
        Paragraph(f"Case: {payload['case_id']}", styles["Normal"]),
        Spacer(1, 12),
        Paragraph("Case Summary", styles["Heading2"]),
        Paragraph(
            f"Priority {payload['case']['priority']}, risk {payload['case']['risk_score']}, "
            f"network risk {payload['case']['network_risk_score']}, "
            f"{len(payload['alerts'])} alert(s), {len(payload['case']['account_ids'])} account(s).",
            styles["Normal"],
        ),
        Spacer(1, 12),
        Paragraph("Narrative", styles["Heading2"]),
    ]
    for sentence in (payload["narrative"] or "No narrative generated.").split(". "):
        if sentence.strip():
            flow.append(Paragraph(sentence.strip().rstrip(".") + ".", styles["Normal"]))
            flow.append(Spacer(1, 4))
    flow.append(Spacer(1, 12))
    flow.append(
        Paragraph(
            "PROTOTYPE — illustrative layout, not the FIU-IND STR schema. "
            "For compliance review before any real filing.",
            styles["Italic"],
        )
    )
    doc.build(flow)
    return str(path)


def generate_report(
    session: Session,
    case_id: str,
    report_type: ReportType,
    *,
    settings: Settings,
    actor_type: ActorType,
    actor_id: str,
) -> tuple[Report, list[str]]:
    """Generate a DRAFT STR/SAR: grounded narrative -> JSON payload -> SHA-256 ->
    PDF -> Report row. Returns (report, ungrounded_sentence_reasons). Does NOT
    commit (caller owns the transaction). Raises `ExplanationUnavailableError` /
    `AgentLoopError` on an LLM failure."""
    narr = generate_case_narrative(
        session, case_id, settings=settings, actor_type=actor_type, actor_id=actor_id
    )
    if narr.rejected_reasons:
        # The grounding validator dropped ungrounded sentences from the narrative.
        # The DRAFT is still useful (the investigator edits before filing), but a
        # shortened narrative shouldn't pass silently — record why.
        logger.warning(
            "case %s narrative: %d ungrounded sentence(s) dropped: %s",
            case_id, len(narr.rejected_reasons), "; ".join(narr.rejected_reasons[:3]),
        )
    payload = _build_payload(session, case_id, report_type, narr.narrative)
    canonical = _canonical_json(payload)
    report_id = f"RPT-{uuid4().hex[:12].upper()}"
    pdf_path = _render_pdf(report_id, report_type, payload)

    report = ReportRepository(session).create(
        report_id=report_id,
        case_id=case_id,
        type=report_type,
        status=ReportStatus.DRAFT,
        narrative=narr.narrative,
        json_payload=canonical,
        json_hash=_sha256(canonical),
        pdf_path=pdf_path,
        generated_by=actor_id,
        actor_type=actor_type,
        actor_id=actor_id,
    )
    return report, narr.rejected_reasons


def edit_narrative(
    session: Session, report_id: str, narrative: str, *, actor_type: ActorType, actor_id: str
) -> Report:
    """Edit a DRAFT report's narrative, re-building the payload, hash, and PDF so
    they stay consistent. Only DRAFT reports are editable — a FINALIZED/SUBMITTED
    report's content is locked (that is the point of finalizing)."""
    repo = ReportRepository(session)
    report = repo.get(report_id)
    if report is None:
        raise ValueError(f"report {report_id!r} does not exist")
    if report.status != ReportStatus.DRAFT:
        raise ReportStateError(f"report {report_id} is {report.status}, not DRAFT — cannot edit")

    payload = _build_payload(session, report.case_id, report.type, narrative)
    canonical = _canonical_json(payload)
    pdf_path = _render_pdf(report_id, report.type, payload)
    return repo.update(
        report_id, narrative=narrative, json_payload=canonical, json_hash=_sha256(canonical),
        pdf_path=pdf_path, actor_type=actor_type, actor_id=actor_id,
    )


def finalize_report(
    session: Session, report_id: str, *, actor_type: ActorType, actor_id: str
) -> Report:
    """Lock a DRAFT report's content (DRAFT -> FINALIZED)."""
    return _transition(
        session, report_id, ReportStatus.DRAFT, ReportStatus.FINALIZED,
        actor_type=actor_type, actor_id=actor_id,
    )


def submit_report(
    session: Session, report_id: str, fiu_reference: str, *, actor_type: ActorType, actor_id: str
) -> Report:
    """Record a FINALIZED report as filed with FIU-IND (FINALIZED -> SUBMITTED),
    stamping the reference and submission time."""
    return _transition(
        session, report_id, ReportStatus.FINALIZED, ReportStatus.SUBMITTED,
        actor_type=actor_type, actor_id=actor_id, fiu_reference=fiu_reference,
        submitted_at=utcnow(),
    )


def _transition(
    session: Session,
    report_id: str,
    expected: ReportStatus,
    new: ReportStatus,
    *,
    actor_type: ActorType,
    actor_id: str,
    fiu_reference: str | None = None,
    submitted_at: datetime | None = None,
) -> Report:
    repo = ReportRepository(session)
    report = repo.get(report_id)
    if report is None:
        raise ValueError(f"report {report_id!r} does not exist")
    if report.status != expected:
        raise ReportStateError(
            f"report {report_id} is {report.status}; expected {expected} to move to {new}"
        )
    kwargs: dict[str, Any] = {"status": new, "actor_type": actor_type, "actor_id": actor_id}
    if fiu_reference is not None:
        kwargs["fiu_reference"] = fiu_reference
    if submitted_at is not None:
        kwargs["submitted_at"] = submitted_at
    return repo.update(report_id, **kwargs)
