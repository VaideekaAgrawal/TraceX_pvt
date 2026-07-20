"""HTTP-round-trip tests for `/model-metrics` (ROADMAP Phase 12) via
`TestClient`, mirroring `tests/api/test_recommendations_routes.py`'s harness.

Covers the governance surface: auth, the `ADMIN_COMPLIANCE`-only gate, and that
the snapshot reports the active model, rules ordered by learned confidence, and a
durable verdict-based precision computed from `detection_feedback` rows.
"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from api.app import create_app
from db.enums import ActorType, CaseResolution, UserRole
from db.models import Base
from db.repositories.detection import (
    DetectionFeedbackRepository,
    ModelRunRepository,
    RuleDefinitionRepository,
)
from db.repositories.platform import UserRepository
from db.session import build_engine, get_db
from foundation.config import Settings
from foundation.security import hash_password

_HASHED_PASSWORD = hash_password("correct-horse")
INVESTIGATOR = "0f0e0d0c-0b0a-0908-0706-050403020100"
ADMIN = "2f2e2d2c-2b2a-2928-2726-252423222120"


@pytest.fixture()
def db_sessionmaker(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    engine = build_engine(f"sqlite:///{tmp_path / 'test_gov.db'}")
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
        ModelRunRepository(db).create(
            run_id="MR1", model_name="ensemble", model_type="xgboost", version="v3",
            trained_at=datetime(2026, 7, 1, tzinfo=UTC),
            metrics={"f1": 0.82, "auc": 0.95}, dataset_hash="abc123", active=True,
            actor_type=ActorType.SYSTEM, actor_id=None,
        )
        rules = RuleDefinitionRepository(db)
        rules.create(
            rule_id="R_NOISY", name="noisy", dsl={"primitive": "chain"}, tier=1,
            confidence=0.15, actor_type=ActorType.SYSTEM, actor_id=None,
        )
        rules.create(
            rule_id="R_GOOD", name="good", dsl={"primitive": "cycle"}, tier=1,
            confidence=0.90, actor_type=ActorType.SYSTEM, actor_id=None,
        )
        fb = DetectionFeedbackRepository(db)
        # 3 TP + 1 FP -> precision 0.75; + 1 enhanced-monitoring (not in precision).
        for i, (verdict, reward) in enumerate(
            [
                (CaseResolution.TRUE_POSITIVE_SAR, 1.0),
                (CaseResolution.TRUE_POSITIVE_SAR, 1.0),
                (CaseResolution.TRUE_POSITIVE_SAR, 1.0),
                (CaseResolution.FALSE_POSITIVE, -0.3),
                (CaseResolution.ENHANCED_MONITORING, 1.0),
            ]
        ):
            fb.create(
                case_id=f"C{i}", verdict=verdict, reward=reward, created_by=ADMIN,
                actor_type=ActorType.SYSTEM, actor_id=None,
            )
        db.commit()
    return db_sessionmaker


def _headers(client: TestClient, username: str) -> dict[str, str]:
    resp = client.post("/auth/login", json={"username": username, "password": "correct-horse"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_requires_auth(client: TestClient, seeded: sessionmaker[Session]) -> None:
    assert client.get("/model-metrics").status_code == 401


def test_investigator_forbidden(client: TestClient, seeded: sessionmaker[Session]) -> None:
    assert client.get("/model-metrics", headers=_headers(client, "inv")).status_code == 403


def test_admin_gets_governance_snapshot(
    client: TestClient, seeded: sessionmaker[Session]
) -> None:
    r = client.get("/model-metrics", headers=_headers(client, "admin"))
    assert r.status_code == 200, r.text
    body = r.json()

    # Active model surfaced with its metrics.
    assert len(body["models"]) == 1
    assert body["models"][0]["model_name"] == "ensemble"
    assert body["models"][0]["version"] == "v3"
    assert body["models"][0]["metrics"]["f1"] == 0.82

    # Rules ordered by confidence ascending — noisiest first.
    assert [x["rule_id"] for x in body["rules"]] == ["R_NOISY", "R_GOOD"]

    # Durable precision from the feedback rows: 3 TP / (3 TP + 1 FP) = 0.75.
    fb = body["feedback"]
    assert fb["total"] == 5
    assert fb["true_positive"] == 3
    assert fb["false_positive"] == 1
    assert fb["enhanced_monitoring"] == 1
    assert fb["precision"] == 0.75

    # RL block present with the global arm and its learned features.
    assert body["rl"]["arm_id"] == "global"
    assert len(body["rl"]["top_features"]) > 0


def test_precision_none_without_tp_or_fp(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    # No users/feedback beyond the admin — precision has no basis yet.
    with db_sessionmaker() as db:
        UserRepository(db).create(
            user_id=ADMIN, username="admin", email="admin@example.com",
            password_hash=_HASHED_PASSWORD, role=UserRole.ADMIN_COMPLIANCE,
            full_name="Admin", actor_type=ActorType.SYSTEM, actor_id=None,
        )
        db.commit()
    r = client.get("/model-metrics", headers=_headers(client, "admin"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["feedback"]["total"] == 0
    assert body["feedback"]["precision"] is None
