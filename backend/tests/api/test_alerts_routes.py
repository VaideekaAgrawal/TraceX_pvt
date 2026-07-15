"""
HTTP-round-trip tests for `/alerts*` (ROADMAP Phase 14) via
`fastapi.testclient.TestClient` -- mirrors `tests/api/test_cases_routes.py`'s
pattern (file-backed throwaway SQLite DB bound to its own sessionmaker,
overriding `get_db`).
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
    DetectionType,
    Priority,
    RiskLevel,
    UserRole,
)
from db.models import Base
from db.repositories.detection import AlertRepository
from db.repositories.investigation import CaseAccountRepository, CaseRepository
from db.repositories.platform import AuditLogRepository, UserRepository
from db.repositories.reference import AccountRepository
from db.session import build_engine, get_db
from foundation.config import Settings
from foundation.security import hash_password
from investigation.cases import claim_alert_for_new_case, create_case_from_alert

_HASHED_PASSWORD = hash_password("correct-horse")


@pytest.fixture()
def db_sessionmaker(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    engine = build_engine(f"sqlite:///{tmp_path / 'test_alerts.db'}")
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    try:
        yield maker
    finally:
        engine.dispose()


@pytest.fixture()
def client(db_sessionmaker: sessionmaker[Session]) -> Iterator[TestClient]:
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


def _seed_user(
    db_sessionmaker: sessionmaker[Session],
    *,
    user_id: str,
    username: str,
    role: UserRole = UserRole.INVESTIGATOR,
    active: bool = True,
) -> None:
    with db_sessionmaker() as db:
        UserRepository(db).create(
            user_id=user_id,
            username=username,
            email=f"{username}@example.com",
            password_hash=_HASHED_PASSWORD,
            role=role,
            full_name=username.title(),
            active=active,
            actor_type=ActorType.SYSTEM,
            actor_id=None,
        )
        db.commit()


def _login(client: TestClient, username: str) -> str:
    resp = client.post("/auth/login", json={"username": username, "password": "correct-horse"})
    assert resp.status_code == 200, resp.text
    token: str = resp.json()["access_token"]
    return token


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed_account(db_sessionmaker: sessionmaker[Session], account_id: str) -> None:
    with db_sessionmaker() as db:
        if AccountRepository(db).get(account_id) is None:
            AccountRepository(db).create(
                account_id=account_id, actor_type=ActorType.SYSTEM, actor_id=None
            )
            db.commit()


def _seed_alert(
    db_sessionmaker: sessionmaker[Session],
    *,
    alert_id: str,
    primary_account_id: str = "A1",
    risk_score: float = 75.0,
    severity: RiskLevel = RiskLevel.HIGH,
    priority: Priority = Priority.P1,
    case_id: str | None = None,
) -> None:
    _seed_account(db_sessionmaker, primary_account_id)
    with db_sessionmaker() as db:
        AlertRepository(db).create(
            alert_id=alert_id,
            detection_type=DetectionType.layering,
            primary_account_id=primary_account_id,
            account_ids=[primary_account_id],
            score=0.8,
            risk_score=risk_score,
            severity=severity,
            priority=priority,
            status="open" if case_id is None else "assigned",
            source="pipeline",
            case_id=case_id,
            actor_type=ActorType.SYSTEM,
            actor_id=None,
        )
        db.commit()


def _seed_case(
    db_sessionmaker: sessionmaker[Session],
    *,
    case_id: str,
    primary_account_id: str = "A1",
    status: CaseStatus = CaseStatus.IN_PROGRESS,
    assigned_to: str | None = None,
) -> None:
    _seed_account(db_sessionmaker, primary_account_id)
    with db_sessionmaker() as db:
        CaseRepository(db).create(
            case_id=case_id,
            primary_account_id=primary_account_id,
            status=status,
            level=CaseLevel.L1,
            priority=Priority.P2,
            assigned_to=assigned_to,
            actor_type=ActorType.SYSTEM,
            actor_id=None,
        )
        CaseAccountRepository(db).add_account(
            case_id=case_id,
            account_id=primary_account_id,
            actor_type=ActorType.SYSTEM,
            actor_id=None,
        )
        db.commit()


# ── GET /alerts: identical for both roles ───────────────────────────────


def test_investigator_and_admin_see_identical_alert_list(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    _seed_user(
        db_sessionmaker, user_id="U_ADMIN", username="admin1", role=UserRole.ADMIN_COMPLIANCE
    )
    _seed_alert(db_sessionmaker, alert_id="AL1", primary_account_id="A1", risk_score=90.0)
    _seed_alert(db_sessionmaker, alert_id="AL2", primary_account_id="A2", risk_score=40.0)

    inv_token = _login(client, "inv1")
    admin_token = _login(client, "admin1")

    inv_resp = client.get("/alerts", headers=_auth_headers(inv_token))
    admin_resp = client.get("/alerts", headers=_auth_headers(admin_token))

    assert inv_resp.status_code == 200
    assert admin_resp.status_code == 200
    inv_body = inv_resp.json()
    admin_body = admin_resp.json()
    assert inv_body["total_count"] == admin_body["total_count"] == 2
    inv_ids = {item["alert_id"] for item in inv_body["items"]}
    admin_ids = {item["alert_id"] for item in admin_body["items"]}
    assert inv_ids == admin_ids == {"AL1", "AL2"}


def test_get_alerts_filters_by_severity_and_sorts(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    _seed_alert(
        db_sessionmaker, alert_id="AL_LOW", primary_account_id="A1",
        risk_score=10.0, severity=RiskLevel.LOW,
    )
    _seed_alert(
        db_sessionmaker, alert_id="AL_HIGH", primary_account_id="A2",
        risk_score=95.0, severity=RiskLevel.HIGH,
    )
    token = _login(client, "inv1")

    resp = client.get(
        "/alerts", params={"severity": "HIGH", "sort": "risk_score_desc"},
        headers=_auth_headers(token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_count"] == 1
    assert [item["alert_id"] for item in body["items"]] == ["AL_HIGH"]


def test_get_alerts_rejects_invalid_sort(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    token = _login(client, "inv1")

    resp = client.get("/alerts", params={"sort": "nonsense"}, headers=_auth_headers(token))
    assert resp.status_code == 400


def test_get_alerts_surfaces_assigned_to_name_and_case_status(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    _seed_case(
        db_sessionmaker, case_id="CASE1", primary_account_id="A1",
        status=CaseStatus.IN_PROGRESS, assigned_to="U_INV",
    )
    _seed_alert(db_sessionmaker, alert_id="AL1", primary_account_id="A1", case_id="CASE1")
    token = _login(client, "inv1")

    resp = client.get("/alerts", headers=_auth_headers(token))
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["case_id"] == "CASE1"
    assert item["assigned_to"] == "U_INV"
    assert item["assigned_to_name"] == "Inv1"
    assert item["case_status"] == "IN_PROGRESS"


# ── GET /alerts/workload: Admin-only ────────────────────────────────────


def test_alert_workload_forbidden_for_investigator_allowed_for_admin(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    _seed_user(
        db_sessionmaker, user_id="U_ADMIN", username="admin1", role=UserRole.ADMIN_COMPLIANCE
    )
    inv_token = _login(client, "inv1")
    admin_token = _login(client, "admin1")

    resp = client.get("/alerts/workload", headers=_auth_headers(inv_token))
    assert resp.status_code == 403

    resp = client.get("/alerts/workload", headers=_auth_headers(admin_token))
    assert resp.status_code == 200
    body = resp.json()
    assert any(i["user_id"] == "U_INV" for i in body["investigators"])


# ── PATCH /alerts/{alert_id}/assign: Admin-only, both alert shapes ─────


def test_assign_forbidden_for_investigator(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    _seed_alert(db_sessionmaker, alert_id="AL1")
    token = _login(client, "inv1")

    resp = client.patch(
        "/alerts/AL1/assign", json={"investigator_id": "U_INV"}, headers=_auth_headers(token)
    )
    assert resp.status_code == 403


def test_assign_alert_with_no_case_creates_case_and_case_assigned_audit_row(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    _seed_user(
        db_sessionmaker, user_id="U_ADMIN", username="admin1", role=UserRole.ADMIN_COMPLIANCE
    )
    _seed_alert(db_sessionmaker, alert_id="AL_NOCASE", case_id=None)
    admin_token = _login(client, "admin1")

    resp = client.patch(
        "/alerts/AL_NOCASE/assign",
        json={"investigator_id": "U_INV"},
        headers=_auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["alert_id"] == "AL_NOCASE"
    assert body["assigned_to"] == "U_INV"
    assert body["case_status"] == "ASSIGNED"
    case_id = body["case_id"]

    with db_sessionmaker() as db:
        rows = AuditLogRepository(db).list_for_case(case_id)
        assert any(r.action == "case_assigned" for r in rows)
        assert not any(r.action == "case_reassigned" for r in rows)


def test_assign_alert_with_existing_open_case_reassigns_without_status_change(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    _seed_user(db_sessionmaker, user_id="U_INV2", username="inv2")
    _seed_user(
        db_sessionmaker, user_id="U_ADMIN", username="admin1", role=UserRole.ADMIN_COMPLIANCE
    )
    _seed_case(
        db_sessionmaker, case_id="CASE1", primary_account_id="A1",
        status=CaseStatus.IN_PROGRESS, assigned_to="U_INV",
    )
    _seed_alert(db_sessionmaker, alert_id="AL1", primary_account_id="A1", case_id="CASE1")
    admin_token = _login(client, "admin1")

    resp = client.patch(
        "/alerts/AL1/assign",
        json={"investigator_id": "U_INV2"},
        headers=_auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["case_id"] == "CASE1"
    assert body["assigned_to"] == "U_INV2"
    assert body["case_status"] == "IN_PROGRESS"  # unchanged

    with db_sessionmaker() as db:
        rows = AuditLogRepository(db).list_for_case("CASE1")
        assert any(r.action == "case_reassigned" for r in rows)


def test_assign_alert_on_terminal_case_returns_409(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    _seed_user(
        db_sessionmaker, user_id="U_ADMIN", username="admin1", role=UserRole.ADMIN_COMPLIANCE
    )
    _seed_case(
        db_sessionmaker, case_id="CASE1", primary_account_id="A1",
        status=CaseStatus.CLOSED_FP, assigned_to="U_INV",
    )
    _seed_alert(db_sessionmaker, alert_id="AL1", primary_account_id="A1", case_id="CASE1")
    admin_token = _login(client, "admin1")

    resp = client.patch(
        "/alerts/AL1/assign",
        json={"investigator_id": "U_INV"},
        headers=_auth_headers(admin_token),
    )
    assert resp.status_code == 409


def test_assign_alert_to_non_investigator_returns_422(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(
        db_sessionmaker, user_id="U_ADMIN", username="admin1", role=UserRole.ADMIN_COMPLIANCE
    )
    _seed_user(
        db_sessionmaker, user_id="U_ADMIN2", username="admin2", role=UserRole.ADMIN_COMPLIANCE
    )
    _seed_alert(db_sessionmaker, alert_id="AL1", case_id=None)
    admin_token = _login(client, "admin1")

    resp = client.patch(
        "/alerts/AL1/assign",
        json={"investigator_id": "U_ADMIN2"},
        headers=_auth_headers(admin_token),
    )
    assert resp.status_code == 422


def test_assign_alert_to_inactive_investigator_returns_422(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(
        db_sessionmaker, user_id="U_ADMIN", username="admin1", role=UserRole.ADMIN_COMPLIANCE
    )
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1", active=False)
    _seed_alert(db_sessionmaker, alert_id="AL1", case_id=None)
    admin_token = _login(client, "admin1")

    resp = client.patch(
        "/alerts/AL1/assign",
        json={"investigator_id": "U_INV"},
        headers=_auth_headers(admin_token),
    )
    assert resp.status_code == 422


def test_assign_unknown_alert_returns_404(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(
        db_sessionmaker, user_id="U_ADMIN", username="admin1", role=UserRole.ADMIN_COMPLIANCE
    )
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    admin_token = _login(client, "admin1")

    resp = client.patch(
        "/alerts/NOPE/assign",
        json={"investigator_id": "U_INV"},
        headers=_auth_headers(admin_token),
    )
    assert resp.status_code == 404


# ── GET /alerts: unassigned_only + assigned_to contradiction (Fix 3) ──────


def test_get_alerts_rejects_unassigned_only_with_assigned_to(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    """Code-review finding, Phase 14: `unassigned_only=true` (`case_id IS
    NULL`) AND `assigned_to=<id>` (`case_id IN <that investigator's
    cases>`) can never both match -- previously silently returned
    `total_count=0` with no indication the combination was contradictory.
    Must 400 instead."""
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    token = _login(client, "inv1")

    resp = client.get(
        "/alerts",
        params={"unassigned_only": "true", "assigned_to": "U_INV"},
        headers=_auth_headers(token),
    )
    assert resp.status_code == 400


# ── PATCH /alerts/{alert_id}/assign: concurrent-assignment race (Fix 1) ───


def test_assign_alert_concurrent_race_loser_reassigns_winners_case_no_orphan(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    """End-to-end simulation of the race the atomic claim fixes: between
    the route's own read of `alert.case_id` (still `None` at seed time) and
    its claim attempt, a "concurrent" second request is simulated directly
    against the DB -- winning the atomic claim and creating a Case, exactly
    as a real second HTTP request would have. The route call under test
    must then detect it lost the claim (rowcount == 0), fall through to
    reassigning the winner's case, and must NOT create a second, orphaned
    Case -- exactly one Case must exist for this alert afterward, and the
    HTTP call must still return 200 with the winner's case_id, not an
    error."""
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    _seed_user(db_sessionmaker, user_id="U_INV2", username="inv2")
    _seed_user(
        db_sessionmaker, user_id="U_ADMIN", username="admin1", role=UserRole.ADMIN_COMPLIANCE
    )
    _seed_alert(db_sessionmaker, alert_id="AL_RACE", primary_account_id="A1", case_id=None)

    # Simulate the concurrent "winner": atomically claim the alert and
    # create its case directly against the DB, exactly as `assign_alert`
    # itself would for the request that gets there first.
    winner_case_id = "CASE-WINNER-0001"
    with db_sessionmaker() as db:
        alert = AlertRepository(db).get("AL_RACE")
        assert alert is not None
        rowcount = claim_alert_for_new_case(db, "AL_RACE", winner_case_id)
        assert rowcount == 1
        alert.case_id = winner_case_id
        create_case_from_alert(
            db,
            alert,
            actor_type=ActorType.ADMIN,
            actor_id="U_ADMIN",
            assigned_to="U_INV",
            case_id=winner_case_id,
        )
        db.commit()

    admin_token = _login(client, "admin1")
    resp = client.patch(
        "/alerts/AL_RACE/assign",
        json={"investigator_id": "U_INV2"},
        headers=_auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Reassigned the WINNER's case -- not a second, orphaned one.
    assert body["case_id"] == winner_case_id
    assert body["assigned_to"] == "U_INV2"

    with db_sessionmaker() as db:
        all_cases = CaseRepository(db).list(limit=100)
        assert [c.case_id for c in all_cases] == [winner_case_id]

        rows = AuditLogRepository(db).list_for_case(winner_case_id)
        assert any(r.action == "case_reassigned" for r in rows)
