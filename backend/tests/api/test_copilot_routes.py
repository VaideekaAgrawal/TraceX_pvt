"""HTTP-round-trip tests for `/copilot/ask` (ROADMAP Phase 10) via `TestClient`,
mirroring `tests/api/test_recommendations_routes.py`'s harness. LLM-free paths
only (auth, validation, the no-cases short-circuit), so nothing bills."""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from api.app import create_app
from db.enums import ActorType, UserRole
from db.models import Base
from db.repositories.platform import UserRepository
from db.session import build_engine, get_db
from foundation.config import Settings
from foundation.security import hash_password

_PW = hash_password("correct-horse")
USER_ID = "2f2e2d2c-2b2a-2928-2726-252423222120"


@pytest.fixture()
def db_sessionmaker(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    engine = build_engine(f"sqlite:///{tmp_path / 'test_copilot.db'}")
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


@pytest.fixture()
def seeded(db_sessionmaker: sessionmaker[Session]) -> sessionmaker[Session]:
    with db_sessionmaker() as db:
        UserRepository(db).create(
            user_id=USER_ID, username="inv", email="inv@example.com", password_hash=_PW,
            role=UserRole.INVESTIGATOR, full_name="Inv", actor_type=ActorType.SYSTEM, actor_id=None,
        )
        db.commit()
    return db_sessionmaker


def _headers(client: TestClient) -> dict[str, str]:
    resp = client.post("/auth/login", json={"username": "inv", "password": "correct-horse"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_ask_requires_auth(client: TestClient, seeded: sessionmaker[Session]) -> None:
    assert client.post("/copilot/ask", json={"question": "hi"}).status_code == 401


def test_ask_rejects_empty_question(client: TestClient, seeded: sessionmaker[Session]) -> None:
    assert client.post(
        "/copilot/ask", headers=_headers(client), json={"question": ""}
    ).status_code == 422


def test_ask_rejects_overlong_question(client: TestClient, seeded: sessionmaker[Session]) -> None:
    assert client.post(
        "/copilot/ask", headers=_headers(client), json={"question": "x" * 5000}
    ).status_code == 422


def test_ask_with_no_cases_answers_false_without_a_model_call(
    client: TestClient, seeded: sessionmaker[Session]
) -> None:
    # The seeded investigator has no assigned cases, so the engine short-circuits
    # before any LLM call — a real 200 with answered=false.
    resp = client.post(
        "/copilot/ask", headers=_headers(client), json={"question": "what should I look at?"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["answered"] is False
    assert body["interaction_id"] is None
