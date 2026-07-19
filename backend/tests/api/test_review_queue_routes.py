"""HTTP-round-trip tests for `/rule-proposals` — the Phase 12 admin review queue
— via `TestClient`, mirroring `tests/api/test_recommendations_routes.py`.

Covers: proposing (open to any authenticated user) with DSL validation, the
`ADMIN_COMPLIANCE`-only review gate, approve (which mints an enabled
`RuleDefinition`), reject (with a required note), and the PENDING-only
state-machine guards.
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
from db.repositories.detection import RuleDefinitionRepository
from db.repositories.platform import UserRepository
from db.session import build_engine, get_db
from foundation.config import Settings
from foundation.security import hash_password

_HASHED_PASSWORD = hash_password("correct-horse")
INVESTIGATOR = "0f0e0d0c-0b0a-0908-0706-050403020100"
ADMIN = "2f2e2d2c-2b2a-2928-2726-252423222120"

# A structurally valid single-primitive rule DSL.
_VALID_DSL = {
    "detection_type": "layering", "severity": "HIGH", "combinator": "AND",
    "conditions": [{"primitive": "chain", "params": {}, "negate": False}],
}


@pytest.fixture()
def db_sessionmaker(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    engine = build_engine(f"sqlite:///{tmp_path / 'test_rq.db'}")
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
            user_id=ADMIN, username="admin", email="admin@example.com",
            password_hash=_HASHED_PASSWORD, role=UserRole.ADMIN_COMPLIANCE,
            full_name="Admin", actor_type=ActorType.SYSTEM, actor_id=None,
        )
        db.commit()
    return db_sessionmaker


def _headers(client: TestClient, username: str) -> dict[str, str]:
    resp = client.post("/auth/login", json={"username": username, "password": "correct-horse"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _propose(client: TestClient, headers: dict[str, str], dsl=None) -> str:
    resp = client.post(
        "/rule-proposals", headers=headers,
        json={"name": "my rule", "dsl": dsl or _VALID_DSL, "tier": 1, "rationale": "edge case"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["proposal_id"]


def test_propose_requires_auth(client: TestClient, seeded: sessionmaker[Session]) -> None:
    assert client.post("/rule-proposals", json={}).status_code == 401


def test_investigator_can_propose(client: TestClient, seeded: sessionmaker[Session]) -> None:
    pid = _propose(client, _headers(client, "inv"))
    assert pid.startswith("RP-")


def test_propose_rejects_invalid_dsl(client: TestClient, seeded: sessionmaker[Session]) -> None:
    r = client.post(
        "/rule-proposals", headers=_headers(client, "inv"),
        json={
            "name": "bad", "tier": 1, "rationale": "x",
            "dsl": {"conditions": [{"primitive": "not_a_real_primitive"}]},
        },
    )
    assert r.status_code == 422
    assert "unknown primitive" in r.text


def test_propose_rejects_empty_conditions(
    client: TestClient, seeded: sessionmaker[Session]
) -> None:
    r = client.post(
        "/rule-proposals", headers=_headers(client, "inv"),
        json={"name": "bad", "tier": 1, "rationale": "x", "dsl": {"conditions": []}},
    )
    assert r.status_code == 422


def test_list_queue_admin_only(client: TestClient, seeded: sessionmaker[Session]) -> None:
    _propose(client, _headers(client, "inv"))
    assert client.get("/rule-proposals", headers=_headers(client, "inv")).status_code == 403
    admin = client.get("/rule-proposals", headers=_headers(client, "admin"))
    assert admin.status_code == 200
    assert len(admin.json()) == 1
    assert admin.json()[0]["status"] == "PENDING"


def test_approve_mints_enabled_rule(
    client: TestClient, seeded: sessionmaker[Session], db_sessionmaker: sessionmaker[Session]
) -> None:
    pid = _propose(client, _headers(client, "inv"))
    # Investigators can't approve.
    assert client.post(
        f"/rule-proposals/{pid}/approve", headers=_headers(client, "inv")
    ).status_code == 403

    resp = client.post(f"/rule-proposals/{pid}/approve", headers=_headers(client, "admin"))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "APPROVED"
    rule_id = body["created_rule_id"]
    assert rule_id is not None

    with db_sessionmaker() as db:
        rule = RuleDefinitionRepository(db).get(rule_id)
        assert rule is not None
        assert rule.enabled is True
        assert rule.confidence == 0.75  # DEFAULT_RULE_CONFIDENCE
        assert rule.dsl == _VALID_DSL


def test_approve_twice_conflicts(client: TestClient, seeded: sessionmaker[Session]) -> None:
    pid = _propose(client, _headers(client, "inv"))
    admin = _headers(client, "admin")
    assert client.post(f"/rule-proposals/{pid}/approve", headers=admin).status_code == 200
    assert client.post(f"/rule-proposals/{pid}/approve", headers=admin).status_code == 409


def test_approve_unknown_404(client: TestClient, seeded: sessionmaker[Session]) -> None:
    r = client.post("/rule-proposals/RP-NOPE/approve", headers=_headers(client, "admin"))
    assert r.status_code == 404


def test_reject_requires_note_and_records_it(
    client: TestClient, seeded: sessionmaker[Session]
) -> None:
    pid = _propose(client, _headers(client, "inv"))
    admin = _headers(client, "admin")
    # Empty note -> 422.
    assert client.post(
        f"/rule-proposals/{pid}/reject", headers=admin, json={"note": ""}
    ).status_code == 422

    resp = client.post(
        f"/rule-proposals/{pid}/reject", headers=admin, json={"note": "too noisy"}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "REJECTED"
    assert resp.json()["review_note"] == "too noisy"


def test_reject_then_approve_conflicts(
    client: TestClient, seeded: sessionmaker[Session]
) -> None:
    pid = _propose(client, _headers(client, "inv"))
    admin = _headers(client, "admin")
    assert client.post(
        f"/rule-proposals/{pid}/reject", headers=admin, json={"note": "no"}
    ).status_code == 200
    # A decided proposal can't then be approved.
    assert client.post(f"/rule-proposals/{pid}/approve", headers=admin).status_code == 409
