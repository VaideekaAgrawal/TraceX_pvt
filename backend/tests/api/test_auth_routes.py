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

# Computed once and reused across every seeded user in this module — these
# are throwaway fixture passwords, so there's no isolation reason to re-pay
# bcrypt's cost per test (code review, Phase 2 finding #9). `db_sessionmaker`
# itself stays function-scoped (fresh SQLite engine + full
# `Base.metadata.create_all()` per test) rather than being widened to
# session scope — sharing one SQLite file/engine across tests risks
# cross-test state leakage (a case/user created in one test silently
# visible in another) for a few seconds of savings that aren't worth it
# given this suite's size; only the password hash is safe to share, since
# it's stateless and identical every time.
_HASHED_PASSWORD = hash_password("correct-horse")


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


def test_healthz_unauthenticated(client: TestClient) -> None:
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_login_success_returns_token_and_records_login(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(db_sessionmaker, user_id="U1", username="jdoe")

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
    _seed_user(db_sessionmaker, user_id="U1", username="jdoe")
    resp = client.post("/auth/login", json={"username": "jdoe", "password": "wrong"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid username or password"


def test_login_unknown_username_returns_401_same_message(client: TestClient) -> None:
    resp = client.post("/auth/login", json={"username": "ghost", "password": "whatever"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid username or password"


def test_login_unknown_username_still_pays_bcrypt_cost(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression test (code review, Phase 2): a naive `user is None or ...`
    # short-circuit would skip verify_password entirely for an unknown
    # username, making that path return in a fraction of the time a real
    # user's wrong-password path takes — a timing side-channel that lets an
    # attacker enumerate valid usernames despite the identical response
    # body. Asserting verify_password is actually called (against the dummy
    # hash) on this path is what locks the fix in, since a wall-clock
    # timing assertion would be flaky in CI.
    calls: list[str] = []
    import api.routes.auth as auth_module

    real_verify = auth_module.verify_password

    def _tracking_verify(password: str, password_hash: str) -> bool:
        calls.append(password_hash)
        return real_verify(password, password_hash)

    monkeypatch.setattr(auth_module, "verify_password", _tracking_verify)

    resp = client.post("/auth/login", json={"username": "ghost", "password": "whatever"})
    assert resp.status_code == 401
    assert calls == [auth_module._DUMMY_PASSWORD_HASH]


def test_login_inactive_user_returns_401_same_message(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(db_sessionmaker, user_id="U2", username="disabled", active=False)
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
    _seed_user(db_sessionmaker, user_id="U1", username="jdoe")
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


def test_login_uses_the_settings_injected_into_create_app_not_the_global_singleton(
    db_sessionmaker: sessionmaker[Session],
) -> None:
    # Regression test (code review, Phase 2 finding #3): `create_app`'s
    # `settings` argument used to only reach `validate_secrets()` in
    # `lifespan` — `login`/`get_current_user` silently fell back to
    # `foundation.security`'s module-level `get_settings()` singleton for
    # the actual JWT sign/verify path, so a non-default `jwt_secret` passed
    # to `create_app` never actually took effect. Prove it now does: two
    # apps built with different `jwt_secret`s must produce tokens that
    # don't cross-verify, and each app must accept its own token.
    _seed_user(db_sessionmaker, user_id="U1", username="jdoe")

    def _override_get_db() -> Iterator[Session]:
        db = db_sessionmaker()
        try:
            yield db
        finally:
            db.close()

    app_a = create_app(settings=Settings(env="dev", jwt_secret="secret-a"))
    app_a.dependency_overrides[get_db] = _override_get_db
    app_b = create_app(settings=Settings(env="dev", jwt_secret="secret-b"))
    app_b.dependency_overrides[get_db] = _override_get_db

    with TestClient(app_a) as client_a, TestClient(app_b) as client_b:
        token_a = client_a.post(
            "/auth/login", json={"username": "jdoe", "password": "correct-horse"}
        ).json()["access_token"]
        token_b = client_b.post(
            "/auth/login", json={"username": "jdoe", "password": "correct-horse"}
        ).json()["access_token"]

        assert token_a != token_b

        # Each app accepts its own token.
        own_a = client_a.get("/auth/me", headers={"Authorization": f"Bearer {token_a}"})
        own_b = client_b.get("/auth/me", headers={"Authorization": f"Bearer {token_b}"})
        assert own_a.status_code == 200
        assert own_b.status_code == 200

        # Neither app accepts the other's token — proves each app really is
        # signing/verifying with its own injected `jwt_secret`, not a
        # shared global one.
        cross_1 = client_a.get("/auth/me", headers={"Authorization": f"Bearer {token_b}"})
        cross_2 = client_b.get("/auth/me", headers={"Authorization": f"Bearer {token_a}"})
        assert cross_1.status_code == 401
        assert cross_2.status_code == 401
