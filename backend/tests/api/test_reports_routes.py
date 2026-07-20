"""HTTP-round-trip tests for `/cases/{case_id}/reports` + `/reports/{report_id}`
(ROADMAP Phase 11) via `TestClient`, mirroring
`tests/api/test_recommendations_routes.py`'s harness.

These exercise the LLM-FREE route surface only — auth, case-scoping
(`require_case_access`), report-scoping (`_load_report_scoped`), the
CLOSED_TP generation gate, the DRAFT->FINALIZED->SUBMITTED state machine and its
409/403 guards, PDF availability, and request validation. The billed narrative
call itself is never invoked for real: even the one test that exercises a
successful `POST .../reports` (`test_generate_201_for_closed_tp_case`)
monkeypatches `generate_case_narrative`, same as `tests/investigation/
test_reporting.py`; everything else here uses a DRAFT report seeded directly,
and `edit` re-renders a real PDF (reportlab, no model). The full grounded-
generation path (payload/hash/PDF content) is covered in that other file.
"""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from api.app import create_app
from db.enums import (
    ActorType,
    CaseLevel,
    CaseStatus,
    Priority,
    ReportStatus,
    ReportType,
    UserRole,
)
from db.models import Base
from db.repositories.investigation import CaseRepository, ReportRepository
from db.repositories.platform import UserRepository
from db.repositories.reference import AccountRepository
from db.session import build_engine, get_db
from foundation.config import Settings
from foundation.security import hash_password
from investigation import reporting
from orchestration.report_narrative import NarrativeResult

_HASHED_PASSWORD = hash_password("correct-horse")
INVESTIGATOR = "0f0e0d0c-0b0a-0908-0706-050403020100"
OTHER_INV = "1f1e1d1c-1b1a-1918-1716-151413121110"
ADMIN = "2f2e2d2c-2b2a-2928-2726-252423222120"
MY_CASE = "CASE-MINE"
OTHER_CASE = "CASE-THEIRS"
MY_REPORT = "RPT-MINE"
OTHER_REPORT = "RPT-THEIRS"


@pytest.fixture()
def db_sessionmaker(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    engine = build_engine(f"sqlite:///{tmp_path / 'test_reports.db'}")
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    try:
        yield maker
    finally:
        engine.dispose()


@pytest.fixture()
def client(
    db_sessionmaker: sessionmaker[Session], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    # Keep rendered PDFs out of the real data/reports/ tree.
    monkeypatch.setattr(reporting, "_REPORTS_DIR", tmp_path / "reports")
    app = create_app(settings=Settings(env="dev", jwt_secret="test-secret"))

    def _override_get_db() -> Iterator[Session]:
        db = db_sessionmaker()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def seeded(db_sessionmaker: sessionmaker[Session]) -> sessionmaker[Session]:
    with db_sessionmaker() as db:
        users = UserRepository(db)
        for uid, uname, role in (
            (INVESTIGATOR, "inv", UserRole.INVESTIGATOR),
            (OTHER_INV, "other", UserRole.INVESTIGATOR),
            (ADMIN, "admin", UserRole.ADMIN_COMPLIANCE),
        ):
            users.create(
                user_id=uid, username=uname, email=f"{uname}@example.com",
                password_hash=_HASHED_PASSWORD, role=role, full_name=uname,
                actor_type=ActorType.SYSTEM, actor_id=None,
            )
        AccountRepository(db).create(account_id="A1", actor_type=ActorType.SYSTEM, actor_id=None)
        cases = CaseRepository(db)
        reports = ReportRepository(db)
        for cid, cuid, rid in (
            (MY_CASE, INVESTIGATOR, MY_REPORT),
            (OTHER_CASE, OTHER_INV, OTHER_REPORT),
        ):
            cases.create(
                case_id=cid, primary_account_id="A1", status=CaseStatus.IN_PROGRESS,
                level=CaseLevel.L1, priority=Priority.P1, risk_score=50.0,
                assigned_to=cuid, actor_type=ActorType.SYSTEM, actor_id=None,
            )
            # DRAFT report with no PDF yet — exercises the lifecycle + PDF-404 path.
            reports.create(
                report_id=rid, case_id=cid, type=ReportType.STR, status=ReportStatus.DRAFT,
                narrative="seed narrative", generated_by=cuid,
                actor_type=ActorType.SYSTEM, actor_id=None,
            )
        db.commit()
    return db_sessionmaker


def _headers(client: TestClient, username: str) -> dict[str, str]:
    resp = client.post("/auth/login", json={"username": username, "password": "correct-horse"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# ── generation + listing (case-scoped) ──────────────────────────────────


def test_generate_requires_auth(client: TestClient, seeded: sessionmaker[Session]) -> None:
    assert client.post(f"/cases/{MY_CASE}/reports").status_code == 401


def test_generate_404_for_unknown_case(client: TestClient, seeded: sessionmaker[Session]) -> None:
    r = client.post("/cases/CASE-NOPE/reports", headers=_headers(client, "inv"))
    assert r.status_code == 404


def test_generate_403_for_out_of_scope_case(
    client: TestClient, seeded: sessionmaker[Session]
) -> None:
    r = client.post(f"/cases/{OTHER_CASE}/reports", headers=_headers(client, "inv"))
    assert r.status_code == 403


# ── generation gated on CLOSED_TP case state ─────────────────────────────


def test_generate_409_when_case_not_closed_tp(
    client: TestClient, seeded: sessionmaker[Session]
) -> None:
    # MY_CASE is seeded as IN_PROGRESS. `json={}` -- `GenerateReportRequest`
    # has no required fields, but FastAPI still requires *a* body be sent
    # for a non-defaulted body parameter; the CLOSED_TP check itself only
    # runs once the request clears that (and the `require_case_access`
    # dependency), which every test in this section needs.
    r = client.post(f"/cases/{MY_CASE}/reports", headers=_headers(client, "inv"), json={})
    assert r.status_code == 409
    assert "CLOSED_TP" in r.json()["detail"]


def test_generate_409_for_closed_fp_case(
    client: TestClient, seeded: sessionmaker[Session]
) -> None:
    # A confirmed false-positive closure is the case the gate most needs to
    # block -- distinct from "just not closed yet".
    with seeded() as db:
        CaseRepository(db).create(
            case_id="CASE-FP", primary_account_id="A1", status=CaseStatus.CLOSED_FP,
            level=CaseLevel.L1, priority=Priority.P2, risk_score=10.0,
            assigned_to=INVESTIGATOR, actor_type=ActorType.SYSTEM, actor_id=None,
        )
        db.commit()
    r = client.post("/cases/CASE-FP/reports", headers=_headers(client, "inv"), json={})
    assert r.status_code == 409
    assert "CLOSED_TP" in r.json()["detail"]


def test_generate_409_for_admin_on_non_closed_tp_case(
    client: TestClient, seeded: sessionmaker[Session]
) -> None:
    # The gate is about case state, not who's asking -- an Admin bypasses the
    # assignment check but not the CLOSED_TP gate.
    r = client.post(f"/cases/{OTHER_CASE}/reports", headers=_headers(client, "admin"), json={})
    assert r.status_code == 409


def test_generate_201_for_closed_tp_case(
    client: TestClient, seeded: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Bypass the real (billed) LLM call, same trick `tests/investigation/
    # test_reporting.py` uses -- `investigation.reporting.generate_report`
    # calls the module-level `generate_case_narrative` name, so patching it
    # on the `reporting` module affects this route's call too.
    monkeypatch.setattr(
        reporting,
        "generate_case_narrative",
        lambda *a, **k: NarrativeResult(
            narrative="Account A1 moved funds through a layered chain.",
            grounded=True, facts={}, tools_called=[], rejected_reasons=[],
        ),
    )
    with seeded() as db:
        CaseRepository(db).create(
            case_id="CASE-TP", primary_account_id="A1", status=CaseStatus.CLOSED_TP,
            level=CaseLevel.L1, priority=Priority.P1, risk_score=90.0,
            assigned_to=INVESTIGATOR, actor_type=ActorType.SYSTEM, actor_id=None,
        )
        db.commit()
    r = client.post("/cases/CASE-TP/reports", headers=_headers(client, "inv"), json={})
    assert r.status_code == 201, r.text
    assert r.json()["case_id"] == "CASE-TP"


def test_list_reports_returns_case_reports(
    client: TestClient, seeded: sessionmaker[Session]
) -> None:
    r = client.get(f"/cases/{MY_CASE}/reports", headers=_headers(client, "inv"))
    assert r.status_code == 200, r.text
    assert [x["report_id"] for x in r.json()] == [MY_REPORT]


# ── report-scoping ───────────────────────────────────────────────────────


def test_get_report_404_for_unknown(client: TestClient, seeded: sessionmaker[Session]) -> None:
    assert client.get("/reports/RPT-NOPE", headers=_headers(client, "inv")).status_code == 404


def test_get_report_404_when_out_of_scope(
    client: TestClient, seeded: sessionmaker[Session]
) -> None:
    # INVESTIGATOR is not assigned to OTHER_CASE — the report is masked as 404.
    r = client.get(f"/reports/{OTHER_REPORT}", headers=_headers(client, "inv"))
    assert r.status_code == 404


def test_admin_can_read_any_report(client: TestClient, seeded: sessionmaker[Session]) -> None:
    r = client.get(f"/reports/{OTHER_REPORT}", headers=_headers(client, "admin"))
    assert r.status_code == 200, r.text
    assert r.json()["report_id"] == OTHER_REPORT


def test_pdf_404_when_not_yet_rendered(
    client: TestClient, seeded: sessionmaker[Session]
) -> None:
    # The seeded DRAFT has no pdf_path.
    r = client.get(f"/reports/{MY_REPORT}/pdf", headers=_headers(client, "inv"))
    assert r.status_code == 404


# ── lifecycle: edit -> finalize -> submit + guards ──────────────────────


def test_edit_rejects_empty_narrative(
    client: TestClient, seeded: sessionmaker[Session]
) -> None:
    r = client.patch(
        f"/reports/{MY_REPORT}", headers=_headers(client, "inv"), json={"narrative": ""}
    )
    assert r.status_code == 422


def test_full_lifecycle_edit_finalize_submit(
    client: TestClient, seeded: sessionmaker[Session]
) -> None:
    inv = _headers(client, "inv")
    admin = _headers(client, "admin")
    # Edit the DRAFT — re-renders a real PDF (no model), so the PDF becomes available.
    # Editing stays open to the assigned investigator (not a filing action).
    edited = client.patch(
        f"/reports/{MY_REPORT}", headers=inv, json={"narrative": "revised narrative body."}
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["narrative"] == "revised narrative body."
    assert edited.json()["has_pdf"] is True
    pdf = client.get(f"/reports/{MY_REPORT}/pdf", headers=inv)
    assert pdf.status_code == 200
    assert pdf.content[:4] == b"%PDF"

    # Finalize + submit are the actual regulatory-filing actions -> Admin/
    # Compliance only.
    fin = client.post(f"/reports/{MY_REPORT}/finalize", headers=admin)
    assert fin.status_code == 200
    assert fin.json()["status"] == str(ReportStatus.FINALIZED)

    # Editing a FINALIZED report is a state-machine violation -> 409 (still
    # would be blocked by the role check for an investigator, but here it's
    # the admin hitting the FSM guard).
    assert client.patch(
        f"/reports/{MY_REPORT}", headers=inv, json={"narrative": "too late"}
    ).status_code == 409
    # Finalizing again is also illegal -> 409.
    assert client.post(f"/reports/{MY_REPORT}/finalize", headers=admin).status_code == 409

    # Submit records the FIU filing.
    sub = client.post(
        f"/reports/{MY_REPORT}/submit", headers=admin, json={"fiu_reference": "FIU-2026-001"}
    )
    assert sub.status_code == 200, sub.text
    assert sub.json()["status"] == str(ReportStatus.SUBMITTED)
    assert sub.json()["fiu_reference"] == "FIU-2026-001"


def test_finalize_403_for_investigator_even_on_own_case(
    client: TestClient, seeded: sessionmaker[Session]
) -> None:
    # MY_REPORT is DRAFT and assigned to this investigator -- the role gate
    # blocks it regardless of case ownership.
    r = client.post(f"/reports/{MY_REPORT}/finalize", headers=_headers(client, "inv"))
    assert r.status_code == 403


def test_submit_403_for_investigator_even_on_own_case(
    client: TestClient, seeded: sessionmaker[Session]
) -> None:
    r = client.post(
        f"/reports/{MY_REPORT}/submit", headers=_headers(client, "inv"),
        json={"fiu_reference": "FIU-2026-002"},
    )
    assert r.status_code == 403


def test_submit_rejects_empty_reference(
    client: TestClient, seeded: sessionmaker[Session]
) -> None:
    # Admin headers -- this test targets request validation, not the role
    # gate (covered separately by test_submit_403_for_investigator_...).
    r = client.post(
        f"/reports/{MY_REPORT}/submit", headers=_headers(client, "admin"),
        json={"fiu_reference": ""},
    )
    assert r.status_code == 422


def test_submit_before_finalize_conflicts(
    client: TestClient, seeded: sessionmaker[Session]
) -> None:
    # MY_REPORT is DRAFT — submitting skips FINALIZED and must 409. Admin
    # headers -- this test targets the FSM guard, not the role gate.
    r = client.post(
        f"/reports/{MY_REPORT}/submit", headers=_headers(client, "admin"),
        json={"fiu_reference": "FIU-X"},
    )
    assert r.status_code == 409
