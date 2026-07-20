"""HTTP-round-trip tests for `/watchlist` (ROADMAP Phase 11) via `TestClient`,
mirroring `tests/api/test_recommendations_routes.py`'s harness (a file-backed
throwaway SQLite DB bound to its own sessionmaker, overriding `get_db`).

These cover the route surface: auth, the `require_role(ADMIN_COMPLIANCE)` gate on
the mutating routes, idempotent add, soft-delete, and request validation. The
screening/escalation logic behind a watchlist entry is covered directly in
`tests/investigation/test_watchlist.py`.
"""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from api.app import create_app
from db.enums import ActorType, EntityType, RiskLevel, UserRole
from db.models import Base
from db.repositories.platform import UserRepository
from db.repositories.reference import AccountRepository, CustomerRepository
from db.session import build_engine, get_db
from foundation.config import Settings
from foundation.security import hash_password

_HASHED_PASSWORD = hash_password("correct-horse")
INVESTIGATOR = "0f0e0d0c-0b0a-0908-0706-050403020100"
ADMIN = "2f2e2d2c-2b2a-2928-2726-252423222120"


@pytest.fixture()
def db_sessionmaker(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    engine = build_engine(f"sqlite:///{tmp_path / 'test_watchlist.db'}")
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


def test_list_requires_auth(client: TestClient, seeded: sessionmaker[Session]) -> None:
    assert client.get("/watchlist").status_code == 401


def test_investigator_can_list_but_not_add(
    client: TestClient, seeded: sessionmaker[Session]
) -> None:
    inv = _headers(client, "inv")
    assert client.get("/watchlist", headers=inv).status_code == 200
    # require_role(ADMIN_COMPLIANCE) forbids an investigator from adding.
    r = client.post(
        "/watchlist", headers=inv,
        json={"entity_type": "ACCOUNT", "entity_value": "DEMO-ACC-0001"},
    )
    assert r.status_code == 403


def test_admin_add_is_idempotent(client: TestClient, seeded: sessionmaker[Session]) -> None:
    admin = _headers(client, "admin")
    body = {"entity_type": "ACCOUNT", "entity_value": "DEMO-ACC-0001", "reason": "mule"}
    first = client.post("/watchlist", headers=admin, json=body)
    assert first.status_code == 201, first.text
    entry_id = first.json()["entry_id"]
    # Re-adding the same (type, value) returns the existing entry, not a duplicate.
    again = client.post("/watchlist", headers=admin, json=body)
    assert again.status_code == 201
    assert again.json()["entry_id"] == entry_id
    listed = client.get("/watchlist", headers=admin).json()
    assert [e["entry_id"] for e in listed] == [entry_id]


def test_admin_can_remove_and_delist(client: TestClient, seeded: sessionmaker[Session]) -> None:
    admin = _headers(client, "admin")
    created = client.post(
        "/watchlist", headers=admin,
        json={"entity_type": "CUSTOMER", "entity_value": "DEMO-CUST-0034"},
    )
    entry_id = created.json()["entry_id"]
    assert client.delete(f"/watchlist/{entry_id}", headers=admin).status_code == 204
    # Soft-deleted entries fall out of the active listing.
    assert client.get("/watchlist", headers=admin).json() == []


def test_remove_unknown_entry_404(client: TestClient, seeded: sessionmaker[Session]) -> None:
    r = client.delete("/watchlist/does-not-exist", headers=_headers(client, "admin"))
    assert r.status_code == 404


def test_add_rejects_empty_value(client: TestClient, seeded: sessionmaker[Session]) -> None:
    r = client.post(
        "/watchlist", headers=_headers(client, "admin"),
        json={"entity_type": "ACCOUNT", "entity_value": ""},
    )
    assert r.status_code == 422


# ── enrichment fields (created_at + display/risk/activity/alerts) ────────


def test_created_at_present_and_enrichment_defaults_when_unresolvable(
    client: TestClient, seeded: sessionmaker[Session]
) -> None:
    admin = _headers(client, "admin")
    created = client.post(
        "/watchlist", headers=admin,
        json={"entity_type": "ACCOUNT", "entity_value": "DEMO-ACC-0001"},
    )
    assert created.status_code == 201, created.text
    assert "created_at" in created.json()

    listed = client.get("/watchlist", headers=admin).json()
    assert len(listed) == 1
    entry = listed[0]
    assert "created_at" in entry
    # No backing Account row for DEMO-ACC-0001 in this seed -- resolved
    # fields come back honestly empty rather than erroring.
    assert entry["display_name"] is None
    assert entry["current_risk"] is None
    assert entry["latest_activity"] is None
    assert entry["alerts"] == []


def test_list_enriches_account_entry_from_owning_customer(
    client: TestClient, seeded: sessionmaker[Session]
) -> None:
    with seeded() as db:
        CustomerRepository(db).create(
            customer_id="CUST-WL1", name="Priya Nair", entity_type=EntityType.INDIVIDUAL,
            risk_rating=RiskLevel.LOW, actor_type=ActorType.SYSTEM, actor_id=None,
        )
        AccountRepository(db).create(
            account_id="ACC-WL1", customer_id="CUST-WL1", current_risk_score=64.0,
            actor_type=ActorType.SYSTEM, actor_id=None,
        )
        db.commit()
    admin = _headers(client, "admin")
    client.post(
        "/watchlist", headers=admin, json={"entity_type": "ACCOUNT", "entity_value": "ACC-WL1"}
    )
    entry = client.get("/watchlist", headers=admin).json()[0]
    assert entry["display_name"] == "Priya Nair"
    assert entry["current_risk"] == 64.0


def test_list_enriches_customer_entry_display_name_directly(
    client: TestClient, seeded: sessionmaker[Session]
) -> None:
    with seeded() as db:
        CustomerRepository(db).create(
            customer_id="CUST-WL2", name="Rahul Verma", entity_type=EntityType.INDIVIDUAL,
            risk_rating=RiskLevel.LOW, actor_type=ActorType.SYSTEM, actor_id=None,
        )
        db.commit()
    admin = _headers(client, "admin")
    client.post(
        "/watchlist", headers=admin, json={"entity_type": "CUSTOMER", "entity_value": "CUST-WL2"}
    )
    entry = client.get("/watchlist", headers=admin).json()[0]
    assert entry["display_name"] == "Rahul Verma"
    # No per-customer numeric risk score column exists.
    assert entry["current_risk"] is None
