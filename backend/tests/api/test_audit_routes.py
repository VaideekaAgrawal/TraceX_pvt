"""
HTTP-round-trip tests for `GET /audit-log` (ROADMAP Phase 14) -- mirrors
`tests/api/test_cases_routes.py`'s throwaway-SQLite `TestClient` pattern.
"""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from api.app import create_app
from db.enums import ActorType, CaseLevel, CaseStatus, Priority, UserRole
from db.models import Base
from db.repositories.investigation import CaseRepository
from db.repositories.platform import UserRepository
from db.repositories.reference import AccountRepository
from db.session import build_engine, get_db
from foundation.config import Settings
from foundation.security import hash_password

_HASHED_PASSWORD = hash_password("correct-horse")


@pytest.fixture()
def db_sessionmaker(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    engine = build_engine(f"sqlite:///{tmp_path / 'test_audit.db'}")
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


def _seed_case_by(
    db_sessionmaker: sessionmaker[Session],
    *,
    case_id: str,
    account_id: str,
    actor_type: ActorType,
    actor_id: str | None,
) -> None:
    """Creates one `case_created` audit row attributed to `actor_id` --
    the deterministic-actor building block these tests scope filters
    against, reusing the real repository write path (not a synthetic
    fixture insert) so the audit rows are authentic."""
    with db_sessionmaker() as db:
        if AccountRepository(db).get(account_id) is None:
            AccountRepository(db).create(
                account_id=account_id, actor_type=ActorType.SYSTEM, actor_id=None
            )
        CaseRepository(db).create(
            case_id=case_id,
            primary_account_id=account_id,
            status=CaseStatus.NEW,
            level=CaseLevel.L1,
            priority=Priority.P2,
            actor_type=actor_type,
            actor_id=actor_id,
        )
        db.commit()


def test_investigator_scoped_to_own_actions_by_default(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(db_sessionmaker, user_id="U_INV1", username="inv1")
    _seed_user(db_sessionmaker, user_id="U_INV2", username="inv2")
    _seed_case_by(
        db_sessionmaker, case_id="CASE1", account_id="A1",
        actor_type=ActorType.INVESTIGATOR, actor_id="U_INV1",
    )
    _seed_case_by(
        db_sessionmaker, case_id="CASE2", account_id="A2",
        actor_type=ActorType.INVESTIGATOR, actor_id="U_INV2",
    )
    token = _login(client, "inv1")

    resp = client.get("/audit-log", headers=_auth_headers(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_count"] >= 1
    assert all(item["actor_id"] == "U_INV1" for item in body["items"])
    assert not any(item["case_id"] == "CASE2" for item in body["items"])


def test_investigator_requesting_foreign_actor_id_gets_403(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(db_sessionmaker, user_id="U_INV1", username="inv1")
    _seed_user(db_sessionmaker, user_id="U_INV2", username="inv2")
    token = _login(client, "inv1")

    resp = client.get(
        "/audit-log", params={"actor_id": "U_INV2"}, headers=_auth_headers(token)
    )
    assert resp.status_code == 403


def test_investigator_requesting_own_actor_id_explicitly_is_allowed(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(db_sessionmaker, user_id="U_INV1", username="inv1")
    _seed_case_by(
        db_sessionmaker, case_id="CASE1", account_id="A1",
        actor_type=ActorType.INVESTIGATOR, actor_id="U_INV1",
    )
    token = _login(client, "inv1")

    resp = client.get(
        "/audit-log", params={"actor_id": "U_INV1"}, headers=_auth_headers(token)
    )
    assert resp.status_code == 200


def test_admin_unscoped_sees_every_actors_actions(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(db_sessionmaker, user_id="U_INV1", username="inv1")
    _seed_user(db_sessionmaker, user_id="U_INV2", username="inv2")
    _seed_user(
        db_sessionmaker, user_id="U_ADMIN", username="admin1", role=UserRole.ADMIN_COMPLIANCE
    )
    _seed_case_by(
        db_sessionmaker, case_id="CASE1", account_id="A1",
        actor_type=ActorType.INVESTIGATOR, actor_id="U_INV1",
    )
    _seed_case_by(
        db_sessionmaker, case_id="CASE2", account_id="A2",
        actor_type=ActorType.INVESTIGATOR, actor_id="U_INV2",
    )
    token = _login(client, "admin1")

    resp = client.get("/audit-log", headers=_auth_headers(token))
    assert resp.status_code == 200
    body = resp.json()
    actor_ids = {item["actor_id"] for item in body["items"]}
    assert {"U_INV1", "U_INV2"} <= actor_ids


def test_admin_can_scope_to_a_specific_actor_id(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(db_sessionmaker, user_id="U_INV1", username="inv1")
    _seed_user(db_sessionmaker, user_id="U_INV2", username="inv2")
    _seed_user(
        db_sessionmaker, user_id="U_ADMIN", username="admin1", role=UserRole.ADMIN_COMPLIANCE
    )
    _seed_case_by(
        db_sessionmaker, case_id="CASE1", account_id="A1",
        actor_type=ActorType.INVESTIGATOR, actor_id="U_INV1",
    )
    _seed_case_by(
        db_sessionmaker, case_id="CASE2", account_id="A2",
        actor_type=ActorType.INVESTIGATOR, actor_id="U_INV2",
    )
    token = _login(client, "admin1")

    resp = client.get(
        "/audit-log", params={"actor_id": "U_INV1"}, headers=_auth_headers(token)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert all(item["actor_id"] == "U_INV1" for item in body["items"])


def test_audit_log_filters_by_case_id_and_action(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(
        db_sessionmaker, user_id="U_ADMIN", username="admin1", role=UserRole.ADMIN_COMPLIANCE
    )
    _seed_case_by(
        db_sessionmaker, case_id="CASE1", account_id="A1",
        actor_type=ActorType.SYSTEM, actor_id=None,
    )
    token = _login(client, "admin1")

    resp = client.get("/audit-log", params={"case_id": "CASE1"}, headers=_auth_headers(token))
    assert resp.status_code == 200
    assert all(item["case_id"] == "CASE1" for item in resp.json()["items"])

    resp = client.get(
        "/audit-log", params={"action": "case_created"}, headers=_auth_headers(token)
    )
    assert resp.status_code == 200
    assert all(item["action"] == "case_created" for item in resp.json()["items"])


def test_audit_log_orders_most_recent_first(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(
        db_sessionmaker, user_id="U_ADMIN", username="admin1", role=UserRole.ADMIN_COMPLIANCE
    )
    _seed_case_by(
        db_sessionmaker, case_id="CASE1", account_id="A1",
        actor_type=ActorType.SYSTEM, actor_id=None,
    )
    _seed_case_by(
        db_sessionmaker, case_id="CASE2", account_id="A2",
        actor_type=ActorType.SYSTEM, actor_id=None,
    )
    token = _login(client, "admin1")

    resp = client.get("/audit-log", headers=_auth_headers(token))
    ids = [item["id"] for item in resp.json()["items"]]
    assert ids == sorted(ids, reverse=True)
