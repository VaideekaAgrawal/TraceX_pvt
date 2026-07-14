"""
HTTP-round-trip tests for `GET /dashboard/summary` (ROADMAP Phase 14) --
mirrors `tests/api/test_cases_routes.py`'s throwaway-SQLite `TestClient`
pattern. Assertions compare against numbers manually computed in each
test's own fixture, not just "the route doesn't crash."
"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from api.app import create_app
from db.enums import ActorType, CaseLevel, CaseStatus, DetectionType, Priority, RiskLevel, UserRole
from db.models import Base
from db.repositories.detection import AlertRepository
from db.repositories.investigation import CaseRepository
from db.repositories.platform import UserRepository
from db.repositories.reference import AccountRepository
from db.session import build_engine, get_db
from foundation.config import Settings
from foundation.security import hash_password

_HASHED_PASSWORD = hash_password("correct-horse")


@pytest.fixture()
def db_sessionmaker(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    engine = build_engine(f"sqlite:///{tmp_path / 'test_dashboard.db'}")
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


def test_dashboard_summary_matches_manually_computed_aggregates(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    now = datetime.now(UTC)

    with db_sessionmaker() as db:
        AccountRepository(db).create(account_id="A1", actor_type=ActorType.SYSTEM, actor_id=None)

        # Two open cases, one closed -- open_case_count must be 2.
        CaseRepository(db).create(
            case_id="CASE_OPEN1", primary_account_id="A1", status=CaseStatus.NEW,
            level=CaseLevel.L1, priority=Priority.P2,
            actor_type=ActorType.SYSTEM, actor_id=None,
        )
        CaseRepository(db).create(
            case_id="CASE_OPEN2", primary_account_id="A1", status=CaseStatus.IN_PROGRESS,
            level=CaseLevel.L1, priority=Priority.P2,
            actor_type=ActorType.SYSTEM, actor_id=None,
        )
        CaseRepository(db).create(
            case_id="CASE_CLOSED", primary_account_id="A1", status=CaseStatus.CLOSED_FP,
            level=CaseLevel.L1, priority=Priority.P2,
            actor_type=ActorType.SYSTEM, actor_id=None,
        )

        # Three active alerts (severities HIGH, HIGH, LOW; risk 80/60/10)
        # and one "closed" alert excluded from every active-only aggregate.
        alert_repo = AlertRepository(db)
        alert_repo.create(
            alert_id="AL1", detection_type=DetectionType.layering, primary_account_id="A1",
            account_ids=["A1"], score=0.8, risk_score=80.0, severity=RiskLevel.HIGH,
            priority=Priority.P1, status="open", source="pipeline", created_at=now,
            actor_type=ActorType.SYSTEM, actor_id=None,
        )
        alert_repo.create(
            alert_id="AL2", detection_type=DetectionType.layering, primary_account_id="A1",
            account_ids=["A1"], score=0.6, risk_score=60.0, severity=RiskLevel.HIGH,
            priority=Priority.P2, status="assigned", source="pipeline", created_at=now,
            actor_type=ActorType.SYSTEM, actor_id=None,
        )
        alert_repo.create(
            alert_id="AL3", detection_type=DetectionType.dormancy, primary_account_id="A1",
            account_ids=["A1"], score=0.1, risk_score=10.0, severity=RiskLevel.LOW,
            priority=Priority.P4, status="open", source="pipeline",
            created_at=now - timedelta(days=1),
            actor_type=ActorType.SYSTEM, actor_id=None,
        )
        alert_repo.create(
            alert_id="AL_CLOSED", detection_type=DetectionType.layering, primary_account_id="A1",
            account_ids=["A1"], score=0.5, risk_score=999.0, severity=RiskLevel.CRITICAL,
            priority=Priority.P1, status="closed", source="pipeline", created_at=now,
            actor_type=ActorType.SYSTEM, actor_id=None,
        )
        db.commit()

    token = _login(client, "inv1")
    resp = client.get("/dashboard/summary", headers=_auth_headers(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["active_alert_count"] == 3
    assert body["open_case_count"] == 2
    assert body["avg_risk_score"] == pytest.approx((80.0 + 60.0 + 10.0) / 3)
    assert body["severity_breakdown"]["HIGH"] == 2
    assert body["severity_breakdown"]["LOW"] == 1
    assert body["severity_breakdown"]["MEDIUM"] == 0
    assert body["severity_breakdown"]["CRITICAL"] == 0  # AL_CLOSED excluded

    assert body["window_days"] == 30
    assert len(body["alerts_over_time"]) == 30
    by_date = {p["date"]: p["count"] for p in body["alerts_over_time"]}
    today_key = now.date().isoformat()
    yesterday_key = (now.date() - timedelta(days=1)).isoformat()
    # AL1/AL2/AL_CLOSED all created "today"; AL3 created "yesterday" -- all
    # four are counted here (count_by_day has no active/closed filter, only
    # the Dashboard's other aggregates exclude the closed alert).
    assert by_date[today_key] == 3
    assert by_date[yesterday_key] == 1
    # Every non-populated day in the 30-day window is zero-filled.
    assert sum(by_date.values()) == 4
    assert all(count >= 0 for count in by_date.values())


def test_dashboard_summary_zero_state_when_no_data(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    token = _login(client, "inv1")

    resp = client.get("/dashboard/summary", headers=_auth_headers(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["active_alert_count"] == 0
    assert body["open_case_count"] == 0
    assert body["avg_risk_score"] is None
    assert all(count == 0 for count in body["severity_breakdown"].values())
    assert set(body["severity_breakdown"].keys()) == {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
    assert all(p["count"] == 0 for p in body["alerts_over_time"])


def test_dashboard_summary_identical_for_investigator_and_admin(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    _seed_user(
        db_sessionmaker, user_id="U_ADMIN", username="admin1", role=UserRole.ADMIN_COMPLIANCE
    )
    inv_token = _login(client, "inv1")
    admin_token = _login(client, "admin1")

    inv_resp = client.get("/dashboard/summary", headers=_auth_headers(inv_token))
    admin_resp = client.get("/dashboard/summary", headers=_auth_headers(admin_token))
    assert inv_resp.status_code == admin_resp.status_code == 200
    assert inv_resp.json() == admin_resp.json()
