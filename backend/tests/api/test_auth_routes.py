"""
HTTP-round-trip auth tests via `fastapi.testclient.TestClient` — this is
what actually falsifies CLAUDE.md's "No auth wired in" landmine (auth
exercised through a real HTTP round trip, not just unit-tested in
isolation).

Uses a file-backed throwaway SQLite DB (not `:memory:`) bound to its own
sessionmaker, overriding `get_db` — `TestClient` may dispatch sync
endpoints on a worker thread, and SQLite `:memory:` databases are only
reliably shared within a single connection/thread, so a file-backed DB
avoids that flakiness class entirely.
"""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from api.app import create_app
from db.enums import ActorType, UserRole
from db.models import Base
from db.repositories.platform import AuditLogRepository, UserRepository
from db.session import build_engine, get_db
from foundation.config import Settings
from foundation.security import hash_password


@pytest.fixture()
def db_sessionmaker(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    engine = build_engine(f"sqlite:///{tmp_path / 'test_auth.db'}")
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


def _seed_active_user(db_sessionmaker: sessionmaker[Session]) -> None:
    with db_sessionmaker() as db:
        UserRepository(db).create(
            user_id="U1",
            username="jdoe",
            email="jdoe@example.com",
            password_hash=hash_password("correct-horse"),
            role=UserRole.INVESTIGATOR,
            full_name="Jane Doe",
            actor_type=ActorType.SYSTEM,
            actor_id=None,
        )
        db.commit()


def _seed_inactive_user(db_sessionmaker: sessionmaker[Session]) -> None:
    with db_sessionmaker() as db:
        UserRepository(db).create(
            user_id="U2",
            username="disabled",
            email="disabled@example.com",
            password_hash=hash_password("correct-horse"),
            role=UserRole.INVESTIGATOR,
            full_name="Disabled User",
            active=False,
            actor_type=ActorType.SYSTEM,
            actor_id=None,
        )
        db.commit()


def test_healthz_unauthenticated(client: TestClient) -> None:
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_login_success_returns_token_and_records_login(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_active_user(db_sessionmaker)

    resp = client.post("/auth/login", json={"username": "jdoe", "password": "correct-horse"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"]
    assert body["role"] == "INVESTIGATOR"
    assert body["user_id"] == "U1"

    with db_sessionmaker() as db:
        user = UserRepository(db).get("U1")
        assert user is not None
        assert user.last_login_at is not None

        audit_rows = AuditLogRepository(db).list_for_entity("user", "U1")
        assert any(row.action == "user_updated" for row in audit_rows)


def test_login_wrong_password_returns_401_generic_message(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_active_user(db_sessionmaker)
    resp = client.post("/auth/login", json={"username": "jdoe", "password": "wrong"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid username or password"


def test_login_unknown_username_returns_401_same_message(client: TestClient) -> None:
    resp = client.post("/auth/login", json={"username": "ghost", "password": "whatever"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid username or password"


def test_login_inactive_user_returns_401_same_message(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_inactive_user(db_sessionmaker)
    resp = client.post(
        "/auth/login", json={"username": "disabled", "password": "correct-horse"}
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid username or password"


def test_me_without_token_returns_401(client: TestClient) -> None:
    resp = client.get("/auth/me")
    assert resp.status_code == 401


def test_me_with_token_returns_200(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_active_user(db_sessionmaker)
    login_resp = client.post(
        "/auth/login", json={"username": "jdoe", "password": "correct-horse"}
    )
    token = login_resp.json()["access_token"]

    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == "U1"
    assert body["username"] == "jdoe"
    assert body["role"] == "INVESTIGATOR"


def test_create_app_raises_runtime_error_on_missing_secrets_in_prod() -> None:
    app = create_app(settings=Settings(env="prod", jwt_secret="", openrouter_api_key=""))
    with pytest.raises(RuntimeError):
        with TestClient(app):
            pass
