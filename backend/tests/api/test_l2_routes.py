"""
HTTP-round-trip tests for `/cases/*`'s L2 surface (ROADMAP Phase 6,
`api.routes.l2`) via `fastapi.testclient.TestClient` -- mirrors
`tests/api/test_cases_routes.py`'s pattern (file-backed throwaway SQLite DB,
overriding `get_db`).

Seeds a multi-hop source -> mule -> sink graph plus a prior
TRUE_POSITIVE_SAR case sharing the sink account, and drives every new
route.
"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
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
    Channel,
    DetectionType,
    EntityType,
    Priority,
    RiskLevel,
    UserRole,
)
from db.models import Base
from db.repositories.detection import AlertRepository
from db.repositories.investigation import CaseAccountRepository, CaseRepository
from db.repositories.orchestration import AiInteractionRepository, RelationshipRepository
from db.repositories.platform import AuditLogRepository, UserRepository
from db.repositories.reference import AccountRepository, CustomerRepository, TransactionRepository
from db.session import build_engine, get_db
from foundation.config import Settings
from foundation.security import hash_password
from orchestration import graph_explanation

_HASHED_PASSWORD = hash_password("correct-horse")
TS = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture()
def db_sessionmaker(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    engine = build_engine(f"sqlite:///{tmp_path / 'test_l2.db'}")
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
            user_id=user_id, username=username, email=f"{username}@example.com",
            password_hash=_HASHED_PASSWORD, role=role, full_name=username.title(),
            actor_type=ActorType.SYSTEM, actor_id=None,
        )
        db.commit()


def _login(client: TestClient, username: str) -> str:
    resp = client.post("/auth/login", json={"username": username, "password": "correct-horse"})
    assert resp.status_code == 200, resp.text
    token: str = resp.json()["access_token"]
    return token


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed_case_graph(db_sessionmaker: sessionmaker[Session], *, assigned_to: str) -> None:
    """SRC -> MULE -> SINK, plus an OUTSIDE account never linked to the
    case, plus a prior TRUE_POSITIVE_SAR case sharing SINK."""
    with db_sessionmaker() as db:
        for account_id in ("SRC", "MULE", "SINK", "OUTSIDE"):
            expected_volume = 100.0 if account_id == "SRC" else None
            AccountRepository(db).create(
                account_id=account_id, expected_monthly_volume=expected_volume,
                actor_type=ActorType.SYSTEM, actor_id=None,
            )
        TransactionRepository(db).create(
            txn_id="T1", timestamp=TS, source_account="SRC", dest_account="MULE",
            amount=10_000.0, channel=Channel.UPI, is_laundering=1, ingested_at=TS,
            actor_type=ActorType.SYSTEM, actor_id=None,
        )
        ts2 = TS.replace(hour=1)
        TransactionRepository(db).create(
            txn_id="T2", timestamp=ts2, source_account="MULE", dest_account="SINK",
            amount=9_500.0, channel=Channel.branch_cash, is_laundering=1, ingested_at=TS,
            actor_type=ActorType.SYSTEM, actor_id=None,
        )

        # Prior, closed TRUE_POSITIVE_SAR case sharing SINK -- network-wide
        # prior-SAR signal for the graph/profile routes.
        CaseRepository(db).create(
            case_id="OLD_CASE", primary_account_id="SINK", status=CaseStatus.CLOSED_TP,
            level=CaseLevel.L1, priority=Priority.P1, actor_type=ActorType.SYSTEM, actor_id=None,
        )
        CaseRepository(db).update(
            "OLD_CASE", resolution=CaseResolution.TRUE_POSITIVE_SAR,
            actor_type=ActorType.SYSTEM, actor_id=None,
        )
        AlertRepository(db).create(
            alert_id="OLD_ALERT", detection_type=DetectionType.round_trip,
            primary_account_id="SINK", account_ids=["SINK"], score=0.9, risk_score=95.0,
            severity=RiskLevel.CRITICAL, priority=Priority.P1, status="closed", source="pipeline",
            case_id="OLD_CASE", actor_type=ActorType.SYSTEM, actor_id=None,
        )

        CaseRepository(db).create(
            case_id="CASE1", primary_account_id="SRC", status=CaseStatus.IN_PROGRESS,
            level=CaseLevel.L2, priority=Priority.P1, assigned_to=assigned_to,
            actor_type=ActorType.SYSTEM, actor_id=None,
        )
        for account_id in ("SRC", "MULE", "SINK"):
            CaseAccountRepository(db).add_account(
                case_id="CASE1", account_id=account_id,
                actor_type=ActorType.SYSTEM, actor_id=None,
            )
        AlertRepository(db).create(
            alert_id="AL1", detection_type=DetectionType.layering,
            primary_account_id="SRC", account_ids=["SRC", "MULE", "SINK"], score=0.8,
            risk_score=80.0, severity=RiskLevel.HIGH, priority=Priority.P1, confidence="high",
            rule_ids=["RULE_LAYER_1"], status="open", source="pipeline", case_id="CASE1",
            actor_type=ActorType.SYSTEM, actor_id=None,
        )
        db.commit()


@pytest.fixture()
def seeded(client: TestClient, db_sessionmaker: sessionmaker[Session]) -> str:
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    _seed_case_graph(db_sessionmaker, assigned_to="U_INV")
    return _login(client, "inv1")


def test_graph_route_returns_denormalized_nodes_and_marks_graph_expanded(
    client: TestClient, db_sessionmaker: sessionmaker[Session], seeded: str
) -> None:
    resp = client.get(
        "/cases/CASE1/accounts/SRC/graph?radius=2", headers=_auth_headers(seeded)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["center"] == "SRC"
    node_ids = {n["account_id"] for n in body["nodes"]}
    assert node_ids == {"SRC", "MULE", "SINK"}
    sink_node = next(n for n in body["nodes"] if n["account_id"] == "SINK")
    assert sink_node["has_prior_sar"] is True  # network-wide prior-SAR reach
    src_node = next(n for n in body["nodes"] if n["account_id"] == "SRC")
    assert src_node["hop_distance"] == 0

    with db_sessionmaker() as db:
        actions = [
            r.action for r in AuditLogRepository(db).list_for_entity("case", "CASE1")
        ]
        assert "graph_expanded" in actions


def test_graph_route_suspicious_only_filter(client: TestClient, seeded: str) -> None:
    resp = client.get(
        "/cases/CASE1/accounts/SRC/graph?suspicious_only=true", headers=_auth_headers(seeded)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert {e["txn_id"] for e in body["edges"]} == {"T1", "T2"}  # both are is_laundering=1


def test_graph_route_radius_clamped(client: TestClient, seeded: str) -> None:
    resp = client.get(
        "/cases/CASE1/accounts/SRC/graph?radius=999", headers=_auth_headers(seeded)
    )
    assert resp.status_code == 200
    assert resp.json()["radius"] == 4  # MAX_RADIUS


def test_profile_route(client: TestClient, seeded: str) -> None:
    resp = client.get("/cases/CASE1/accounts/SINK/profile", headers=_auth_headers(seeded))
    assert resp.status_code == 200
    body = resp.json()
    assert body["account_id"] == "SINK"
    assert body["prior_sar_count"] == 1
    assert "beneficial_owner" in body["omitted_fields"]


def test_transaction_search_case_wide_and_account_scoped(client: TestClient, seeded: str) -> None:
    resp = client.get("/cases/CASE1/transactions/search", headers=_auth_headers(seeded))
    assert resp.status_code == 200
    body = resp.json()
    assert {i["txn_id"] for i in body["items"]} == {"T1", "T2"}
    assert body["total_count"] == 2

    resp2 = client.get(
        "/cases/CASE1/accounts/MULE/transactions/search", headers=_auth_headers(seeded)
    )
    assert resp2.status_code == 200
    body2 = resp2.json()
    assert {i["txn_id"] for i in body2["items"]} == {"T1", "T2"}  # both touch MULE


def test_transaction_search_out_of_scope_account_404s(client: TestClient, seeded: str) -> None:
    resp = client.get(
        "/cases/CASE1/accounts/OUTSIDE/transactions/search", headers=_auth_headers(seeded)
    )
    assert resp.status_code == 404


def test_behavior_route(client: TestClient, seeded: str) -> None:
    resp = client.get("/cases/CASE1/accounts/SRC/behavior", headers=_auth_headers(seeded))
    assert resp.status_code == 200
    body = resp.json()
    assert body["account_id"] == "SRC"
    assert body["deferred"] == ["salary_mismatch", "seasonal_trends"]


def test_timeline_route(client: TestClient, seeded: str) -> None:
    resp = client.get("/cases/CASE1/accounts/MULE/timeline", headers=_auth_headers(seeded))
    assert resp.status_code == 200
    body = resp.json()
    assert [e["txn_id"] for e in body["events"]] == ["T1", "T2"]


def test_pattern_explanation_not_configured_fails_open_and_never_caches(
    client: TestClient, db_sessionmaker: sessionmaker[Session], seeded: str
) -> None:
    # No openrouter_api_key configured on this fixture's client -- must
    # fail open with the same visible message, cached=False, both times.
    first = client.get(
        "/cases/CASE1/alerts/AL1/pattern-explanation", headers=_auth_headers(seeded)
    )
    second = client.get(
        "/cases/CASE1/alerts/AL1/pattern-explanation", headers=_auth_headers(seeded)
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["cached"] is False
    assert second.json()["cached"] is False

    with db_sessionmaker() as db:
        interactions = AiInteractionRepository(db).list_for_case_and_agent(
            "CASE1", AiAgent.RECOMMENDATION
        )
        assert interactions == []


def test_pattern_explanation_unknown_alert_404s(client: TestClient, seeded: str) -> None:
    resp = client.get(
        "/cases/CASE1/alerts/NOPE/pattern-explanation", headers=_auth_headers(seeded)
    )
    assert resp.status_code == 404


def test_pin_unknown_evidence_id_404s(client: TestClient, seeded: str) -> None:
    resp = client.patch("/cases/CASE1/evidence/NOPE/pin", headers=_auth_headers(seeded))
    assert resp.status_code == 404


def test_graph_explanation_second_call_is_cached(
    client: TestClient, db_sessionmaker: sessionmaker[Session], seeded: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Monkeypatch the actual LLM call (not the route) so this exercises the
    # real HTTP route + DB round-trip end to end, mirroring `tests/api/
    # test_cases_routes.py::test_account_explanation_second_call_is_cached`.
    def _fake_call(prompt: str, *, settings: Settings, max_tokens: int = 300) -> str:
        return "Fake graph explanation."

    monkeypatch.setattr(graph_explanation, "_call_llm", _fake_call)

    first = client.get(
        "/cases/CASE1/accounts/SRC/graph-explanation", headers=_auth_headers(seeded)
    )
    assert first.status_code == 200
    assert first.json()["cached"] is False
    assert first.json()["explanation"] == "Fake graph explanation."
    assert first.json()["account_id"] == "SRC"

    second = client.get(
        "/cases/CASE1/accounts/SRC/graph-explanation", headers=_auth_headers(seeded)
    )
    assert second.status_code == 200
    assert second.json()["cached"] is True
    assert second.json()["explanation"] == first.json()["explanation"]

    with db_sessionmaker() as db:
        interactions = AiInteractionRepository(db).list_for_case_and_agent(
            "CASE1", AiAgent.RECOMMENDATION
        )
        assert len(interactions) == 1  # cached read did not write a second row


def test_graph_explanation_not_configured_is_never_cached(client: TestClient, seeded: str) -> None:
    # No openrouter_api_key configured on this fixture's client -- must fail
    # open with the same visible message, cached=False, both times.
    first = client.get(
        "/cases/CASE1/accounts/SRC/graph-explanation", headers=_auth_headers(seeded)
    )
    second = client.get(
        "/cases/CASE1/accounts/SRC/graph-explanation", headers=_auth_headers(seeded)
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["cached"] is False
    assert second.json()["cached"] is False


def test_graph_explanation_out_of_scope_account_404s(client: TestClient, seeded: str) -> None:
    resp = client.get(
        "/cases/CASE1/accounts/OUTSIDE/graph-explanation", headers=_auth_headers(seeded)
    )
    assert resp.status_code == 404


def test_transaction_search_invalid_channel_400s(client: TestClient, seeded: str) -> None:
    resp = client.get(
        "/cases/CASE1/transactions/search?channels=NOT_A_REAL_CHANNEL",
        headers=_auth_headers(seeded),
    )
    assert resp.status_code == 400


def test_evidence_create_pin_and_list(client: TestClient, seeded: str) -> None:
    create_resp = client.post(
        "/cases/CASE1/evidence",
        json={"type": "TRANSACTION", "ref_id": "T1", "label": "Suspicious hop"},
        headers=_auth_headers(seeded),
    )
    assert create_resp.status_code == 201
    evidence_id = create_resp.json()["evidence_id"]
    assert create_resp.json()["pinned"] is False

    pin_resp = client.patch(
        f"/cases/CASE1/evidence/{evidence_id}/pin", headers=_auth_headers(seeded)
    )
    assert pin_resp.status_code == 200
    assert pin_resp.json()["pinned"] is True

    list_resp = client.get("/cases/CASE1/evidence", headers=_auth_headers(seeded))
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1

    pinned_resp = client.get("/cases/CASE1/evidence?pinned=true", headers=_auth_headers(seeded))
    assert len(pinned_resp.json()) == 1

    unpinned_resp = client.get(
        "/cases/CASE1/evidence?pinned=false", headers=_auth_headers(seeded)
    )
    assert unpinned_resp.json() == []


def test_evidence_graph_snapshot_payload_round_trips(client: TestClient, seeded: str) -> None:
    payload = {"radius": 2, "filters": {"suspicious_only": True}, "highlighted_edges": ["T1"]}
    resp = client.post(
        "/cases/CASE1/evidence",
        json={"type": "GRAPH_SNAPSHOT", "label": "Layering path", "payload": payload},
        headers=_auth_headers(seeded),
    )
    assert resp.status_code == 201
    assert resp.json()["payload"] == payload


def test_notes_create_and_list(client: TestClient, seeded: str) -> None:
    resp = client.post(
        "/cases/CASE1/notes", json={"body": "Reviewed the mule hop, escalating."},
        headers=_auth_headers(seeded),
    )
    assert resp.status_code == 201
    assert resp.json()["source"] == "INVESTIGATOR"

    list_resp = client.get("/cases/CASE1/notes", headers=_auth_headers(seeded))
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1
    assert list_resp.json()[0]["body"] == "Reviewed the mule hop, escalating."


def test_relationships_route_surfaces_hidden_one_hop_customer(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    """ROADMAP Phase 7: Relationship Explorer v1 (`GET .../relationships`)
    -- a customer with no shared transaction and no `case_accounts` row at
    all (`CUST_HIDDEN`) must still surface as a node, connected by a
    discovered `Relationship` edge, precisely the "hidden mule network"
    reveal transactions alone can't provide."""
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    with db_sessionmaker() as db:
        AccountRepository(db).create(
            account_id="R_SRC", customer_id="CUST_IN_CASE",
            actor_type=ActorType.SYSTEM, actor_id=None,
        )
        CustomerRepository(db).create(
            customer_id="CUST_IN_CASE", name="In Case Customer", entity_type=EntityType.INDIVIDUAL,
            risk_rating=RiskLevel.MEDIUM, pan="DEMOSHARED1D",
            actor_type=ActorType.SYSTEM, actor_id=None,
        )
        CustomerRepository(db).create(
            customer_id="CUST_HIDDEN", name="Hidden Linked Customer",
            entity_type=EntityType.INDIVIDUAL, risk_rating=RiskLevel.MEDIUM, pan="DEMOSHARED1D",
            actor_type=ActorType.SYSTEM, actor_id=None,
        )
        CustomerRepository(db).create(
            customer_id="CUST_UNRELATED", name="Unrelated Customer",
            entity_type=EntityType.INDIVIDUAL, risk_rating=RiskLevel.MEDIUM,
            actor_type=ActorType.SYSTEM, actor_id=None,
        )
        RelationshipRepository(db).create(
            entity_a="CUST_HIDDEN", entity_b="CUST_IN_CASE", shared_attribute="pan",
            value_hash="deadbeef", confidence=0.95, method="shared_attribute_v1",
            actor_type=ActorType.SYSTEM, actor_id=None,
        )
        CaseRepository(db).create(
            case_id="RCASE1", primary_account_id="R_SRC", status=CaseStatus.IN_PROGRESS,
            level=CaseLevel.L2, priority=Priority.P1, assigned_to="U_INV",
            actor_type=ActorType.SYSTEM, actor_id=None,
        )
        CaseAccountRepository(db).add_account(
            case_id="RCASE1", account_id="R_SRC", actor_type=ActorType.SYSTEM, actor_id=None
        )
        db.commit()
    token = _login(client, "inv1")

    resp = client.get("/cases/RCASE1/relationships", headers=_auth_headers(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["case_id"] == "RCASE1"

    nodes_by_id = {n["customer_id"]: n for n in body["nodes"]}
    assert nodes_by_id["CUST_IN_CASE"]["in_case_scope"] is True
    assert nodes_by_id["CUST_HIDDEN"]["in_case_scope"] is False
    assert "CUST_UNRELATED" not in nodes_by_id

    assert len(body["edges"]) == 1
    edge = body["edges"][0]
    assert {edge["entity_a"], edge["entity_b"]} == {"CUST_HIDDEN", "CUST_IN_CASE"}
    assert edge["shared_attribute"] == "pan"
    assert edge["confidence"] == 0.95


def test_unassigned_investigator_can_read_every_account_scoped_l2_route(
    client: TestClient, db_sessionmaker: sessionmaker[Session], seeded: str
) -> None:
    """RBAC read/write split (bug-fix pass, `fix/l1-l2-usability-and-bugs`):
    every GET route below moved from `require_case_access`/`require_case_
    scoped_account` to `require_case_read_access`/`require_case_scoped_
    account_read` -- an unassigned Investigator can now view them. This
    used to 403 (see git history); it no longer does, by design (see
    `foundation.auth.require_case_read_access`'s docstring)."""
    _seed_user(db_sessionmaker, user_id="U_OTHER", username="other1")
    other_token = _login(client, "other1")

    routes = [
        "/cases/CASE1/accounts/SRC/graph",
        "/cases/CASE1/accounts/SRC/profile",
        "/cases/CASE1/accounts/SRC/transactions/search",
        "/cases/CASE1/accounts/SRC/behavior",
        "/cases/CASE1/accounts/SRC/timeline",
        "/cases/CASE1/evidence",
        "/cases/CASE1/notes",
        "/cases/CASE1/relationships",
        "/cases/CASE1/transactions/search",
        "/cases/CASE1/alerts/AL1/pattern-explanation",
        "/cases/CASE1/accounts/SRC/graph-explanation",
    ]
    for path in routes:
        resp = client.get(path, headers=_auth_headers(other_token))
        assert resp.status_code == 200, f"{path} did not 200 for an unassigned investigator"


def test_unassigned_investigator_403_on_every_l2_write_route(
    client: TestClient, db_sessionmaker: sessionmaker[Session], seeded: str
) -> None:
    """Write routes remain assignment-gated -- the RBAC read/write split
    only widened GET access; every mutation route is still `require_case_
    access`, unchanged."""
    _seed_user(db_sessionmaker, user_id="U_OTHER", username="other1")
    other_token = _login(client, "other1")

    resp = client.post(
        "/cases/CASE1/evidence",
        json={"type": "TRANSACTION", "ref_id": "T1", "label": "x"},
        headers=_auth_headers(other_token),
    )
    assert resp.status_code == 403

    resp = client.post(
        "/cases/CASE1/notes", json={"body": "x"}, headers=_auth_headers(other_token)
    )
    assert resp.status_code == 403


def test_out_of_scope_account_404_on_every_account_scoped_l2_route(
    client: TestClient, seeded: str
) -> None:
    routes = [
        "/cases/CASE1/accounts/OUTSIDE/graph",
        "/cases/CASE1/accounts/OUTSIDE/profile",
        "/cases/CASE1/accounts/OUTSIDE/transactions/search",
        "/cases/CASE1/accounts/OUTSIDE/behavior",
        "/cases/CASE1/accounts/OUTSIDE/timeline",
        "/cases/CASE1/accounts/OUTSIDE/graph-explanation",
    ]
    for path in routes:
        resp = client.get(path, headers=_auth_headers(seeded))
        assert resp.status_code == 404, f"{path} did not 404 for an out-of-scope account"
