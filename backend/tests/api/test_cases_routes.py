"""
HTTP-round-trip tests for `/cases/*` (ROADMAP Phase 5) via
`fastapi.testclient.TestClient` -- mirrors `tests/api/test_auth_routes.py`'s
pattern (file-backed throwaway SQLite DB bound to its own sessionmaker,
overriding `get_db`; `TestClient` may dispatch onto a worker thread, and
SQLite `:memory:` isn't reliably shared across threads).
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
    AiAgent,
    CaseLevel,
    CaseResolution,
    CaseStatus,
    DetectionType,
    Priority,
    RiskLevel,
    UserRole,
)
from db.models import Base
from db.repositories.detection import AlertRepository, DetectionFeedbackRepository
from db.repositories.investigation import CaseAccountRepository, CaseRepository
from db.repositories.orchestration import AiInteractionRepository
from db.repositories.platform import UserRepository
from db.repositories.reference import AccountRepository
from db.session import build_engine, get_db
from foundation.config import Settings
from foundation.security import hash_password

_HASHED_PASSWORD = hash_password("correct-horse")


@pytest.fixture()
def db_sessionmaker(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    engine = build_engine(f"sqlite:///{tmp_path / 'test_cases.db'}")
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
) -> None:
    with db_sessionmaker() as db:
        UserRepository(db).create(
            user_id=user_id,
            username=username,
            email=f"{username}@example.com",
            password_hash=_HASHED_PASSWORD,
            role=role,
            full_name=username.title(),
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


def _seed_case(
    db_sessionmaker: sessionmaker[Session],
    *,
    case_id: str,
    primary_account_id: str,
    account_ids: list[str],
    assigned_to: str | None,
    status: CaseStatus = CaseStatus.ASSIGNED,
) -> None:
    with db_sessionmaker() as db:
        for account_id in account_ids:
            if AccountRepository(db).get(account_id) is None:
                AccountRepository(db).create(
                    account_id=account_id, actor_type=ActorType.SYSTEM, actor_id=None
                )
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
        for account_id in account_ids:
            CaseAccountRepository(db).add_account(
                case_id=case_id, account_id=account_id,
                actor_type=ActorType.SYSTEM, actor_id=None,
            )
        AlertRepository(db).create(
            alert_id=f"AL_{case_id}",
            detection_type=DetectionType.layering,
            primary_account_id=primary_account_id,
            account_ids=account_ids,
            score=0.8,
            risk_score=75.0,
            severity=RiskLevel.HIGH,
            priority=Priority.P1,
            status="assigned",
            source="pipeline",
            case_id=case_id,
            actor_type=ActorType.SYSTEM,
            actor_id=None,
        )
        db.commit()


def test_assigned_investigator_gets_200_on_alert_summary(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    _seed_case(
        db_sessionmaker, case_id="CASE1", primary_account_id="A1",
        account_ids=["A1"], assigned_to="U_INV",
    )
    token = _login(client, "inv1")

    resp = client.get("/cases/CASE1/summary/alerts", headers=_auth_headers(token))
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["alert_id"] == "AL_CASE1"


def test_account_not_in_case_scope_returns_404(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    _seed_case(
        db_sessionmaker, case_id="CASE1", primary_account_id="A1",
        account_ids=["A1"], assigned_to="U_INV",
    )
    with db_sessionmaker() as db:
        AccountRepository(db).create(
            account_id="A_OUTSIDE", actor_type=ActorType.SYSTEM, actor_id=None
        )
        db.commit()
    token = _login(client, "inv1")

    resp = client.get(
        "/cases/CASE1/accounts/A_OUTSIDE/customer-snapshot", headers=_auth_headers(token)
    )
    assert resp.status_code == 404


def test_unassigned_investigator_403_admin_bypasses(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    _seed_user(db_sessionmaker, user_id="U_INV2", username="inv2")
    _seed_user(
        db_sessionmaker, user_id="U_ADMIN", username="admin1", role=UserRole.ADMIN_COMPLIANCE
    )
    _seed_case(
        db_sessionmaker, case_id="CASE1", primary_account_id="A1",
        account_ids=["A1"], assigned_to="U_INV",
    )

    other_token = _login(client, "inv2")
    resp = client.get("/cases/CASE1/summary/alerts", headers=_auth_headers(other_token))
    assert resp.status_code == 403

    admin_token = _login(client, "admin1")
    resp = client.get("/cases/CASE1/summary/alerts", headers=_auth_headers(admin_token))
    assert resp.status_code == 200


def test_close_fp_forbidden_for_investigator_allowed_for_admin(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    _seed_user(
        db_sessionmaker, user_id="U_ADMIN", username="admin1", role=UserRole.ADMIN_COMPLIANCE
    )
    _seed_case(
        db_sessionmaker, case_id="CASE1", primary_account_id="A1", account_ids=["A1"],
        assigned_to="U_INV", status=CaseStatus.IN_PROGRESS,
    )

    inv_token = _login(client, "inv1")
    resp = client.post(
        "/cases/CASE1/decision",
        json={"decision": "close_fp", "reason": "not suspicious"},
        headers=_auth_headers(inv_token),
    )
    assert resp.status_code == 403

    admin_token = _login(client, "admin1")
    resp = client.post(
        "/cases/CASE1/decision",
        json={"decision": "close_fp", "reason": "not suspicious", "note": "reviewed, cleared"},
        headers=_auth_headers(admin_token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "CLOSED_FP"
    assert body["resolution"] == "FALSE_POSITIVE"

    with db_sessionmaker() as db:
        case = CaseRepository(db).get("CASE1")
        assert case is not None
        assert case.status == CaseStatus.CLOSED_FP
        assert case.resolution == CaseResolution.FALSE_POSITIVE

        feedback = DetectionFeedbackRepository(db).list_for_case("CASE1")
        assert len(feedback) == 1
        assert feedback[0].verdict == CaseResolution.FALSE_POSITIVE


def test_escalate_from_illegal_status_returns_409(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    _seed_case(
        db_sessionmaker, case_id="CASE1", primary_account_id="A1", account_ids=["A1"],
        assigned_to="U_INV", status=CaseStatus.NEW,
    )
    token = _login(client, "inv1")

    resp = client.post(
        "/cases/CASE1/decision",
        json={"decision": "escalate", "reason": "needs compliance review"},
        headers=_auth_headers(token),
    )
    assert resp.status_code == 409


def test_escalate_and_request_info_succeed_for_investigator(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    _seed_case(
        db_sessionmaker, case_id="CASE_ESC", primary_account_id="A1", account_ids=["A1"],
        assigned_to="U_INV", status=CaseStatus.IN_PROGRESS,
    )
    _seed_case(
        db_sessionmaker, case_id="CASE_REQ", primary_account_id="A2", account_ids=["A2"],
        assigned_to="U_INV", status=CaseStatus.IN_PROGRESS,
    )
    token = _login(client, "inv1")

    resp = client.post(
        "/cases/CASE_ESC/decision",
        json={"decision": "escalate", "reason": "pattern too complex for L1"},
        headers=_auth_headers(token),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ESCALATED"

    resp = client.post(
        "/cases/CASE_REQ/decision",
        json={"decision": "request_info", "reason": "need more transaction history"},
        headers=_auth_headers(token),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "AWAITING_REVIEW"


def test_network_risk_lazy_fill_then_recompute(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    _seed_case(
        db_sessionmaker, case_id="CASE1", primary_account_id="A1", account_ids=["A1"],
        assigned_to="U_INV", status=CaseStatus.IN_PROGRESS,
    )
    with db_sessionmaker() as db:
        case = CaseRepository(db).get("CASE1")
        assert case is not None
        assert case.network_risk_score is None
    token = _login(client, "inv1")

    resp = client.get("/cases/CASE1/network-risk", headers=_auth_headers(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["network_risk_score"] is not None

    with db_sessionmaker() as db:
        case = CaseRepository(db).get("CASE1")
        assert case is not None
        assert case.network_risk_score == body["network_risk_score"]
        assert case.network_risk_reasons is not None

    resp = client.post("/cases/CASE1/network-risk/recompute", headers=_auth_headers(token))
    assert resp.status_code == 200
    assert resp.json()["network_risk_score"] == body["network_risk_score"]


def test_account_explanation_second_call_is_cached(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    _seed_case(
        db_sessionmaker, case_id="CASE1", primary_account_id="A1", account_ids=["A1"],
        assigned_to="U_INV", status=CaseStatus.IN_PROGRESS,
    )
    token = _login(client, "inv1")

    first = client.get(
        "/cases/CASE1/accounts/A1/explanation", headers=_auth_headers(token)
    )
    assert first.status_code == 200
    assert first.json()["cached"] is False

    second = client.get(
        "/cases/CASE1/accounts/A1/explanation", headers=_auth_headers(token)
    )
    assert second.status_code == 200
    assert second.json()["cached"] is True
    assert second.json()["explanation"] == first.json()["explanation"]

    with db_sessionmaker() as db:
        interactions = AiInteractionRepository(db).list_for_case_and_agent(
            "CASE1", AiAgent.RECOMMENDATION
        )
        assert len(interactions) == 1  # cached read did not write a second row
