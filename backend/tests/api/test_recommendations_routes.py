"""
HTTP-round-trip tests for `/cases/{case_id}/recommendations*` (ROADMAP Phase 9)
via `TestClient`, mirroring `tests/api/test_alerts_routes.py`'s harness (a
file-backed throwaway SQLite DB bound to its own sessionmaker, overriding
`get_db`).

These deliberately exercise only the LLM-FREE paths of the routes — auth,
case-scoping (`require_case_access`), request validation, and the
no-alerts-short-circuit — so the suite never makes a billed model call. The
grounding/ranking/persistence logic behind a real call is covered directly in
`tests/orchestration/recommendation/test_engine.py` with the loop monkeypatched.
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
INVESTIGATOR = "0f0e0d0c-0b0a-0908-0706-050403020100"
OTHER_INV = "1f1e1d1c-1b1a-1918-1716-151413121110"
MY_CASE = "CASE-MINE"
OTHER_CASE = "CASE-THEIRS"


@pytest.fixture()
def db_sessionmaker(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    engine = build_engine(f"sqlite:///{tmp_path / 'test_recs.db'}")
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
        users = UserRepository(db)
        users.create(
            user_id=INVESTIGATOR, username="inv", email="inv@example.com",
            password_hash=_HASHED_PASSWORD, role=UserRole.INVESTIGATOR,
            full_name="Inv", actor_type=ActorType.SYSTEM, actor_id=None,
        )
        users.create(
            user_id=OTHER_INV, username="other", email="other@example.com",
            password_hash=_HASHED_PASSWORD, role=UserRole.INVESTIGATOR,
            full_name="Other", actor_type=ActorType.SYSTEM, actor_id=None,
        )
        AccountRepository(db).create(account_id="A1", actor_type=ActorType.SYSTEM, actor_id=None)
        cases = CaseRepository(db)
        # MY_CASE is assigned to INVESTIGATOR and has NO alerts (engine short-circuits).
        cases.create(
            case_id=MY_CASE, primary_account_id="A1", status=CaseStatus.IN_PROGRESS,
            level=CaseLevel.L1, priority=Priority.P1, risk_score=50.0,
            assigned_to=INVESTIGATOR, actor_type=ActorType.SYSTEM, actor_id=None,
        )
        cases.create(
            case_id=OTHER_CASE, primary_account_id="A1", status=CaseStatus.IN_PROGRESS,
            level=CaseLevel.L1, priority=Priority.P1, risk_score=50.0,
            assigned_to=OTHER_INV, actor_type=ActorType.SYSTEM, actor_id=None,
        )
        db.commit()
    return db_sessionmaker


def _headers(client: TestClient, username: str) -> dict[str, str]:
    resp = client.post("/auth/login", json={"username": username, "password": "correct-horse"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_recommendations_requires_auth(client: TestClient, seeded: sessionmaker[Session]) -> None:
    assert client.post(f"/cases/{MY_CASE}/recommendations").status_code == 401


def test_recommendations_404_for_unknown_case(
    client: TestClient, seeded: sessionmaker[Session]
) -> None:
    r = client.post("/cases/CASE-NOPE/recommendations", headers=_headers(client, "inv"))
    assert r.status_code == 404


def test_recommendations_403_for_out_of_scope_case(
    client: TestClient, seeded: sessionmaker[Session]
) -> None:
    # INVESTIGATOR is not assigned to OTHER_CASE — require_case_access forbids it.
    r = client.post(f"/cases/{OTHER_CASE}/recommendations", headers=_headers(client, "inv"))
    assert r.status_code == 403


def test_recommendations_empty_when_no_alerts_no_model_call(
    client: TestClient, seeded: sessionmaker[Session]
) -> None:
    # MY_CASE has no alerts, so the engine returns an empty result WITHOUT ever
    # calling the model — a real 200 with no billed call.
    r = client.post(f"/cases/{MY_CASE}/recommendations", headers=_headers(client, "inv"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["recommendations"] == []
    assert body["interaction_id"] is None


def test_challenge_rejects_empty_question(
    client: TestClient, seeded: sessionmaker[Session]
) -> None:
    r = client.post(
        f"/cases/{MY_CASE}/recommendations/challenge",
        headers=_headers(client, "inv"), json={"question": ""},
    )
    assert r.status_code == 422


def test_challenge_rejects_overlong_question(
    client: TestClient, seeded: sessionmaker[Session]
) -> None:
    r = client.post(
        f"/cases/{MY_CASE}/recommendations/challenge",
        headers=_headers(client, "inv"), json={"question": "x" * 5000},
    )
    assert r.status_code == 422
