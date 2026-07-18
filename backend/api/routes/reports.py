"""`/cases/{case_id}/reports` + `/reports/{report_id}` — STR/SAR reporting
(ROADMAP Phase 11).

Generating/listing reports is case-scoped via `require_case_access`. The
report-specific routes (`/reports/{id}/...`) load the report, then re-apply the
same case-access check against its case, so an investigator can only touch
reports on their own cases (an Admin/Compliance user bypasses, per
`require_case_access`'s own rule). Generation is a real (billed) LLM call — the
grounded narrative — so it POSTs and commits; the lifecycle transitions commit too.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from db.enums import ReportType, UserRole
from db.models.investigation import Case
from db.models.platform import User
from db.repositories.investigation import CaseRepository, ReportRepository
from db.session import get_db
from foundation.auth import (
    actor_type_for_role,
    get_app_settings,
    get_current_user,
    require_case_access,
)
from foundation.config import Settings
from investigation import reporting
from orchestration.agent_loop import AgentLoopError
from orchestration.gateway import ExplanationUnavailableError

router = APIRouter(tags=["reports"])


# ── models ──────────────────────────────────────────────────────────────


class ReportModel(BaseModel):
    report_id: str
    case_id: str
    type: str
    status: str
    narrative: str | None
    json_hash: str | None
    fiu_reference: str | None
    has_pdf: bool


class GenerateReportRequest(BaseModel):
    type: ReportType = ReportType.STR


class EditNarrativeRequest(BaseModel):
    narrative: str = Field(min_length=1, max_length=50_000)


class SubmitRequest(BaseModel):
    fiu_reference: str = Field(min_length=1, max_length=200)


def _to_model(r) -> ReportModel:
    return ReportModel(
        report_id=r.report_id, case_id=r.case_id, type=str(r.type), status=str(r.status),
        narrative=r.narrative, json_hash=r.json_hash, fiu_reference=r.fiu_reference,
        has_pdf=bool(r.pdf_path and os.path.exists(r.pdf_path)),
    )


def _load_report_scoped(report_id: str, user: User, db: Session):
    """Load a report and enforce the same case-access rule the case routes use:
    an INVESTIGATOR only on their assigned case, ADMIN_COMPLIANCE anywhere."""
    report = ReportRepository(db).get(report_id)
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "report not found")
    if user.role != UserRole.ADMIN_COMPLIANCE:
        case = CaseRepository(db).get(report.case_id)
        if case is None or case.assigned_to != user.user_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "report not found")
    return report


# ── case-scoped: generate + list ────────────────────────────────────────


@router.post("/cases/{case_id}/reports", response_model=ReportModel,
             status_code=status.HTTP_201_CREATED)
def generate_report(
    body: GenerateReportRequest,
    case: Case = Depends(require_case_access),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_app_settings),
    db: Session = Depends(get_db),
) -> ReportModel:
    """Generate a DRAFT STR/SAR (grounded narrative + JSON+SHA-256 + PDF). 503 if
    the LLM is unconfigured/unreachable; 502 if it could not produce a narrative."""
    try:
        report, _rejected = reporting.generate_report(
            db, case.case_id, body.type, settings=settings,
            actor_type=actor_type_for_role(user.role), actor_id=user.user_id,
        )
    except ExplanationUnavailableError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except AgentLoopError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    db.commit()
    return _to_model(report)


@router.get("/cases/{case_id}/reports", response_model=list[ReportModel])
def list_reports(
    case: Case = Depends(require_case_access),
    db: Session = Depends(get_db),
) -> list[ReportModel]:
    return [_to_model(r) for r in ReportRepository(db).list_for_case(case.case_id)]


# ── report-scoped: get / pdf / edit / finalize / submit ──────────────────


@router.get("/reports/{report_id}", response_model=ReportModel)
def get_report(
    report_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReportModel:
    return _to_model(_load_report_scoped(report_id, user, db))


@router.get("/reports/{report_id}/pdf")
def download_report_pdf(
    report_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FileResponse:
    report = _load_report_scoped(report_id, user, db)
    if not report.pdf_path or not os.path.exists(report.pdf_path):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "report PDF not available")
    return FileResponse(report.pdf_path, media_type="application/pdf",
                        filename=f"{report.report_id}.pdf")


@router.patch("/reports/{report_id}", response_model=ReportModel)
def edit_report_narrative(
    report_id: str,
    body: EditNarrativeRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReportModel:
    """Edit a DRAFT report's narrative (re-hashes + re-renders the PDF)."""
    _load_report_scoped(report_id, user, db)
    try:
        report = reporting.edit_narrative(
            db, report_id, body.narrative,
            actor_type=actor_type_for_role(user.role), actor_id=user.user_id,
        )
    except reporting.ReportStateError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    db.commit()
    return _to_model(report)


@router.post("/reports/{report_id}/finalize", response_model=ReportModel)
def finalize_report(
    report_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReportModel:
    _load_report_scoped(report_id, user, db)
    try:
        report = reporting.finalize_report(
            db, report_id, actor_type=actor_type_for_role(user.role), actor_id=user.user_id
        )
    except reporting.ReportStateError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    db.commit()
    return _to_model(report)


@router.post("/reports/{report_id}/submit", response_model=ReportModel)
def submit_report(
    report_id: str,
    body: SubmitRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReportModel:
    """Record a FINALIZED report as filed with FIU-IND. An investigator on their
    own case (or a compliance user) may record the filing."""
    _load_report_scoped(report_id, user, db)
    try:
        report = reporting.submit_report(
            db, report_id, body.fiu_reference,
            actor_type=actor_type_for_role(user.role), actor_id=user.user_id,
        )
    except reporting.ReportStateError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    db.commit()
    return _to_model(report)
