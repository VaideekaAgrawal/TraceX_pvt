"""
HTTP-round-trip tests for `/cases/*` (ROADMAP Phase 5) via
`fastapi.testclient.TestClient` -- mirrors `tests/api/test_auth_routes.py`'s
pattern (file-backed throwaway SQLite DB bound to its own sessionmaker,
overriding `get_db`; `TestClient` may dispatch onto a worker thread, and
SQLite `:memory:` isn't reliably shared across threads).
"""
from __future__ import annotations

from collections.abc import Iterator
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
    DetectionType,
    Priority,
    RiskLevel,
    UserRole,
)
from db.models import Base
from db.repositories.detection import AlertRepository, DetectionFeedbackRepository
from db.repositories.investigation import (
    CaseAccountRepository,
    CaseFeatureVectorRepository,
    CaseRepository,
)
from db.repositories.orchestration import AiInteractionRepository
from db.repositories.platform import UserRepository
from db.repositories.reference import AccountRepository
from db.session import build_engine, get_db
from foundation.config import Settings
from foundation.security import hash_password
from orchestration import account_explanation

_HASHED_PASSWORD = hash_password("correct-horse")


@pytest.fixture()
def db_sessionmaker(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    engine = build_engine(f"sqlite:///{tmp_path / 'test_cases.db'}")
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


def _seed_case(
    db_sessionmaker: sessionmaker[Session],
    *,
    case_id: str,
    primary_account_id: str,
    account_ids: list[str],
    assigned_to: str | None,
    status: CaseStatus = CaseStatus.ASSIGNED,
    priority: Priority = Priority.P2,
) -> None:
    with db_sessionmaker() as db:
        for account_id in account_ids:
            if AccountRepository(db).get(account_id) is None:
                AccountRepository(db).create(
                    account_id=account_id, actor_type=ActorType.SYSTEM, actor_id=None
                )
        CaseRepository(db).create(
            case_id=case_id,
            primary_account_id=primary_account_id,
            status=status,
            level=CaseLevel.L1,
            priority=priority,
            assigned_to=assigned_to,
            actor_type=ActorType.SYSTEM,
            actor_id=None,
        )
        for account_id in account_ids:
            CaseAccountRepository(db).add_account(
                case_id=case_id, account_id=account_id,
                actor_type=ActorType.SYSTEM, actor_id=None,
            )
        AlertRepository(db).create(
            alert_id=f"AL_{case_id}",
            detection_type=DetectionType.layering,
            primary_account_id=primary_account_id,
            account_ids=account_ids,
            score=0.8,
            risk_score=75.0,
            severity=RiskLevel.HIGH,
            priority=Priority.P1,
            status="assigned",
            source="pipeline",
            case_id=case_id,
            actor_type=ActorType.SYSTEM,
            actor_id=None,
        )
        db.commit()


def test_assigned_investigator_gets_200_on_alert_summary(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    _seed_case(
        db_sessionmaker, case_id="CASE1", primary_account_id="A1",
        account_ids=["A1"], assigned_to="U_INV",
    )
    token = _login(client, "inv1")

    resp = client.get("/cases/CASE1/summary/alerts", headers=_auth_headers(token))
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["alert_id"] == "AL_CASE1"


def test_account_not_in_case_scope_returns_404(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    _seed_case(
        db_sessionmaker, case_id="CASE1", primary_account_id="A1",
        account_ids=["A1"], assigned_to="U_INV",
    )
    with db_sessionmaker() as db:
        AccountRepository(db).create(
            account_id="A_OUTSIDE", actor_type=ActorType.SYSTEM, actor_id=None
        )
        db.commit()
    token = _login(client, "inv1")

    resp = client.get(
        "/cases/CASE1/accounts/A_OUTSIDE/customer-snapshot", headers=_auth_headers(token)
    )
    assert resp.status_code == 404


def test_unassigned_investigator_can_read_summary_alerts_admin_too(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    """RBAC read/write split (bug-fix pass, `fix/l1-l2-usability-and-bugs`):
    `GET /{case_id}/summary/alerts` moved from `require_case_access` to
    `require_case_read_access` -- any authenticated user may now view it
    regardless of case assignment, not just the assigned Investigator or
    Admin/Compliance. This used to 403 an unassigned Investigator (see git
    history); it no longer does, by design -- see `foundation.auth.
    require_case_read_access`'s docstring."""
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    _seed_user(db_sessionmaker, user_id="U_INV2", username="inv2")
    _seed_user(
        db_sessionmaker, user_id="U_ADMIN", username="admin1", role=UserRole.ADMIN_COMPLIANCE
    )
    _seed_case(
        db_sessionmaker, case_id="CASE1", primary_account_id="A1",
        account_ids=["A1"], assigned_to="U_INV",
    )

    other_token = _login(client, "inv2")
    resp = client.get("/cases/CASE1/summary/alerts", headers=_auth_headers(other_token))
    assert resp.status_code == 200

    admin_token = _login(client, "admin1")
    resp = client.get("/cases/CASE1/summary/alerts", headers=_auth_headers(admin_token))
    assert resp.status_code == 200


def test_unassigned_investigator_403_on_write_admin_bypasses(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    """Write routes remain assignment-gated for Investigators -- the RBAC
    read/write split only widened GET access; every mutation route is
    still `require_case_access`, unchanged. `POST /decision` used here as
    the write-route exemplar; Admin/Compliance still bypasses, exactly as
    before."""
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    _seed_user(db_sessionmaker, user_id="U_INV2", username="inv2")
    _seed_user(
        db_sessionmaker, user_id="U_ADMIN", username="admin1", role=UserRole.ADMIN_COMPLIANCE
    )
    _seed_case(
        db_sessionmaker, case_id="CASE1", primary_account_id="A1",
        account_ids=["A1"], assigned_to="U_INV", status=CaseStatus.IN_PROGRESS,
    )

    other_token = _login(client, "inv2")
    resp = client.post(
        "/cases/CASE1/decision",
        json={"decision": "escalate", "reason": "test"},
        headers=_auth_headers(other_token),
    )
    assert resp.status_code == 403

    admin_token = _login(client, "admin1")
    resp = client.post(
        "/cases/CASE1/decision",
        json={"decision": "escalate", "reason": "test"},
        headers=_auth_headers(admin_token),
    )
    assert resp.status_code == 200


def test_close_fp_forbidden_for_investigator_allowed_for_admin(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    _seed_user(
        db_sessionmaker, user_id="U_ADMIN", username="admin1", role=UserRole.ADMIN_COMPLIANCE
    )
    _seed_case(
        db_sessionmaker, case_id="CASE1", primary_account_id="A1", account_ids=["A1"],
        assigned_to="U_INV", status=CaseStatus.IN_PROGRESS,
    )

    inv_token = _login(client, "inv1")
    resp = client.post(
        "/cases/CASE1/decision",
        json={"decision": "close_fp", "reason": "not suspicious"},
        headers=_auth_headers(inv_token),
    )
    assert resp.status_code == 403

    admin_token = _login(client, "admin1")
    resp = client.post(
        "/cases/CASE1/decision",
        json={"decision": "close_fp", "reason": "not suspicious", "note": "reviewed, cleared"},
        headers=_auth_headers(admin_token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "CLOSED_FP"
    assert body["resolution"] == "FALSE_POSITIVE"

    with db_sessionmaker() as db:
        case = CaseRepository(db).get("CASE1")
        assert case is not None
        assert case.status == CaseStatus.CLOSED_FP
        assert case.resolution == CaseResolution.FALSE_POSITIVE

        feedback = DetectionFeedbackRepository(db).list_for_case("CASE1")
        assert len(feedback) == 1
        assert feedback[0].verdict == CaseResolution.FALSE_POSITIVE


def test_close_tp_admin_from_awaiting_review(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    """ROADMAP Phase 12: a TRUE_POSITIVE_SAR close is now reachable via the API
    (previously only `close_fp` was), feeding the positive side of the loop."""
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    _seed_user(
        db_sessionmaker, user_id="U_ADMIN", username="admin1", role=UserRole.ADMIN_COMPLIANCE
    )
    # TRUE_POSITIVE_SAR is only FSM-legal from AWAITING_REVIEW / ESCALATED.
    _seed_case(
        db_sessionmaker, case_id="CASE1", primary_account_id="A1", account_ids=["A1"],
        assigned_to="U_INV", status=CaseStatus.AWAITING_REVIEW,
    )

    # An investigator still may not close.
    inv = _auth_headers(_login(client, "inv1"))
    forbidden = client.post(
        "/cases/CASE1/decision",
        json={"decision": "close_tp", "reason": "confirmed layering"}, headers=inv,
    )
    assert forbidden.status_code == 403

    admin = _auth_headers(_login(client, "admin1"))
    resp = client.post(
        "/cases/CASE1/decision",
        json={"decision": "close_tp", "reason": "confirmed layering"}, headers=admin,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "CLOSED_TP"
    assert body["resolution"] == "TRUE_POSITIVE_SAR"

    with db_sessionmaker() as db:
        feedback = DetectionFeedbackRepository(db).list_for_case("CASE1")
        assert len(feedback) == 1
        assert feedback[0].verdict == CaseResolution.TRUE_POSITIVE_SAR
        assert feedback[0].reward > 0  # positive signal into the loop


def test_close_tp_from_in_progress_is_fsm_conflict(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(
        db_sessionmaker, user_id="U_ADMIN", username="admin1", role=UserRole.ADMIN_COMPLIANCE
    )
    # A fresh IN_PROGRESS case can't jump straight to a TP close.
    _seed_case(
        db_sessionmaker, case_id="CASE1", primary_account_id="A1", account_ids=["A1"],
        assigned_to=None, status=CaseStatus.IN_PROGRESS,
    )
    admin = _auth_headers(_login(client, "admin1"))
    resp = client.post(
        "/cases/CASE1/decision",
        json={"decision": "close_tp", "reason": "too early"}, headers=admin,
    )
    assert resp.status_code == 409


def test_close_monitoring_forbidden_for_investigator_allowed_for_admin(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    _seed_user(
        db_sessionmaker, user_id="U_ADMIN", username="admin1", role=UserRole.ADMIN_COMPLIANCE
    )
    _seed_case(
        db_sessionmaker, case_id="CASE1", primary_account_id="A1", account_ids=["A1"],
        assigned_to="U_INV", status=CaseStatus.AWAITING_REVIEW,
    )

    inv_token = _login(client, "inv1")
    resp = client.post(
        "/cases/CASE1/decision",
        json={"decision": "close_monitoring", "reason": "keep an eye on it"},
        headers=_auth_headers(inv_token),
    )
    assert resp.status_code == 403

    admin_token = _login(client, "admin1")
    resp = client.post(
        "/cases/CASE1/decision",
        json={"decision": "close_monitoring", "reason": "pattern plausible but inconclusive"},
        headers=_auth_headers(admin_token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "MONITORING"
    assert body["resolution"] == "ENHANCED_MONITORING"

    with db_sessionmaker() as db:
        case = CaseRepository(db).get("CASE1")
        assert case is not None
        assert case.status == CaseStatus.MONITORING
        assert case.resolution == CaseResolution.ENHANCED_MONITORING


def test_close_monitoring_from_illegal_status_returns_409(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(
        db_sessionmaker, user_id="U_ADMIN", username="admin1", role=UserRole.ADMIN_COMPLIANCE
    )
    _seed_case(
        db_sessionmaker, case_id="CASE1", primary_account_id="A1", account_ids=["A1"],
        assigned_to=None, status=CaseStatus.IN_PROGRESS,
    )
    token = _login(client, "admin1")

    resp = client.post(
        "/cases/CASE1/decision",
        json={"decision": "close_monitoring", "reason": "too early"},
        headers=_auth_headers(token),
    )
    assert resp.status_code == 409


def test_escalate_from_illegal_status_returns_409(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    _seed_case(
        db_sessionmaker, case_id="CASE1", primary_account_id="A1", account_ids=["A1"],
        assigned_to="U_INV", status=CaseStatus.NEW,
    )
    token = _login(client, "inv1")

    resp = client.post(
        "/cases/CASE1/decision",
        json={"decision": "escalate", "reason": "needs compliance review"},
        headers=_auth_headers(token),
    )
    assert resp.status_code == 409


def test_escalate_and_request_info_succeed_for_investigator(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    _seed_case(
        db_sessionmaker, case_id="CASE_ESC", primary_account_id="A1", account_ids=["A1"],
        assigned_to="U_INV", status=CaseStatus.IN_PROGRESS,
    )
    _seed_case(
        db_sessionmaker, case_id="CASE_REQ", primary_account_id="A2", account_ids=["A2"],
        assigned_to="U_INV", status=CaseStatus.IN_PROGRESS,
    )
    token = _login(client, "inv1")

    resp = client.post(
        "/cases/CASE_ESC/decision",
        json={"decision": "escalate", "reason": "pattern too complex for L1"},
        headers=_auth_headers(token),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ESCALATED"

    resp = client.post(
        "/cases/CASE_REQ/decision",
        json={"decision": "request_info", "reason": "need more transaction history"},
        headers=_auth_headers(token),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "AWAITING_REVIEW"


def test_network_risk_lazy_fill_then_recompute(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    _seed_case(
        db_sessionmaker, case_id="CASE1", primary_account_id="A1", account_ids=["A1"],
        assigned_to="U_INV", status=CaseStatus.IN_PROGRESS,
    )
    with db_sessionmaker() as db:
        case = CaseRepository(db).get("CASE1")
        assert case is not None
        assert case.network_risk_score is None
    token = _login(client, "inv1")

    resp = client.get("/cases/CASE1/network-risk", headers=_auth_headers(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["network_risk_score"] is not None

    with db_sessionmaker() as db:
        case = CaseRepository(db).get("CASE1")
        assert case is not None
        assert case.network_risk_score == body["network_risk_score"]
        assert case.network_risk_reasons is not None

    resp = client.post("/cases/CASE1/network-risk/recompute", headers=_auth_headers(token))
    assert resp.status_code == 200
    assert resp.json()["network_risk_score"] == body["network_risk_score"]


def test_similar_cases_returns_ranked_resolved_corpus_excluding_self(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    _seed_case(
        db_sessionmaker, case_id="CASE1", primary_account_id="A1", account_ids=["A1"],
        assigned_to="U_INV", status=CaseStatus.IN_PROGRESS,
    )
    # `CASE1`'s query vector (`typology="layering"`, `risk_score=80.0`, every
    # other `base_rl_feature_dict` dim at its default) is exactly:
    #   [0.8, 0, 0, 0.2, 1.0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0.2, 1.0]
    # -- computed here (not asserted blind) so `CASE_HIST_1`/`CASE_HIST_2`
    # below can be constructed as deliberately near-identical/orthogonal to
    # it, making the expected ranking exact rather than incidental.
    query_vector = [0.8, 0.0, 0.0, 0.2, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.2, 1.0]
    orthogonal_vector = [0.0, 5.0] + [0.0] * 14  # nonzero only where query_vector is 0

    with db_sessionmaker() as db:
        CaseRepository(db).update(
            "CASE1", typology="layering", risk_score=80.0,
            actor_type=ActorType.SYSTEM, actor_id=None,
        )
        # A resolved corpus row for CASE1 itself (as if this same case had
        # been closed previously) -- must never appear in its own results.
        CaseFeatureVectorRepository(db).upsert(
            case_id="CASE1", vector=query_vector, typology="layering",
            outcome=CaseResolution.TRUE_POSITIVE_SAR,
            actor_type=ActorType.SYSTEM, actor_id=None,
        )
        CaseFeatureVectorRepository(db).upsert(
            case_id="CASE_HIST_1", vector=query_vector, typology="layering",
            outcome=CaseResolution.TRUE_POSITIVE_SAR,
            actor_type=ActorType.SYSTEM, actor_id=None,
        )
        CaseFeatureVectorRepository(db).upsert(
            case_id="CASE_HIST_2", vector=orthogonal_vector, typology="dormancy",
            outcome=CaseResolution.FALSE_POSITIVE,
            actor_type=ActorType.SYSTEM, actor_id=None,
        )
        db.commit()
    token = _login(client, "inv1")

    resp = client.get("/cases/CASE1/similar-cases", headers=_auth_headers(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["case_id"] == "CASE1"
    result_ids = [item["case_id"] for item in body["similar_cases"]]
    assert "CASE1" not in result_ids
    assert result_ids == ["CASE_HIST_1", "CASE_HIST_2"]
    assert body["similar_cases"][0]["outcome"] == "TRUE_POSITIVE_SAR"

    resp_top1 = client.get(
        "/cases/CASE1/similar-cases", params={"top_k": 1}, headers=_auth_headers(token)
    )
    assert resp_top1.status_code == 200
    assert len(resp_top1.json()["similar_cases"]) == 1


def test_similar_cases_is_read_access_not_assignment_gated(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    """RBAC read/write split (bug-fix pass): Similar Historical Cases is a
    read-only panel and surfaces other investigators' case_ids regardless of
    assignment already -- `GET .../similar-cases` moved to `require_case_
    read_access` to match, so an unassigned Investigator can open what this
    panel already tells them exists."""
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    _seed_user(db_sessionmaker, user_id="U_INV2", username="inv2")
    _seed_case(
        db_sessionmaker, case_id="CASE1", primary_account_id="A1", account_ids=["A1"],
        assigned_to="U_INV",
    )
    other_token = _login(client, "inv2")
    resp = client.get("/cases/CASE1/similar-cases", headers=_auth_headers(other_token))
    assert resp.status_code == 200


def test_account_explanation_second_call_is_cached(
    client: TestClient, db_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Monkeypatch the actual LLM call (not the route) so this still exercises
    # the real HTTP route + DB round-trip end to end, just without a real
    # network call -- mirrors tests/orchestration/test_account_explanation.py's
    # pattern, applied over TestClient this time.
    def _fake_call(prompt: str, *, settings: Settings, max_tokens: int = 300) -> str:
        return "Fake explanation."

    monkeypatch.setattr(account_explanation, "_call_llm", _fake_call)

    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    _seed_case(
        db_sessionmaker, case_id="CASE1", primary_account_id="A1", account_ids=["A1"],
        assigned_to="U_INV", status=CaseStatus.IN_PROGRESS,
    )
    token = _login(client, "inv1")

    first = client.get(
        "/cases/CASE1/accounts/A1/explanation", headers=_auth_headers(token)
    )
    assert first.status_code == 200
    assert first.json()["cached"] is False
    assert first.json()["explanation"] == "Fake explanation."

    second = client.get(
        "/cases/CASE1/accounts/A1/explanation", headers=_auth_headers(token)
    )
    assert second.status_code == 200
    assert second.json()["cached"] is True
    assert second.json()["explanation"] == first.json()["explanation"]

    with db_sessionmaker() as db:
        interactions = AiInteractionRepository(db).list_for_case_and_agent(
            "CASE1", AiAgent.RECOMMENDATION
        )
        assert len(interactions) == 1  # cached read did not write a second row


def test_account_explanation_not_configured_is_never_cached(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    # Regression test (code-review finding, Phase 5): with no
    # openrouter_api_key configured (this fixture's real `client`), every
    # call must fail open with the same visible message and NEVER be
    # served back as cached=True.
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    _seed_case(
        db_sessionmaker, case_id="CASE1", primary_account_id="A1", account_ids=["A1"],
        assigned_to="U_INV", status=CaseStatus.IN_PROGRESS,
    )
    token = _login(client, "inv1")

    first = client.get("/cases/CASE1/accounts/A1/explanation", headers=_auth_headers(token))
    second = client.get("/cases/CASE1/accounts/A1/explanation", headers=_auth_headers(token))

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["cached"] is False
    assert second.json()["cached"] is False

    with db_sessionmaker() as db:
        interactions = AiInteractionRepository(db).list_for_case_and_agent(
            "CASE1", AiAgent.RECOMMENDATION
        )
        assert interactions == []


# ── GET /cases: role-scoped case list (ROADMAP Phase 15) ─────────────────


def test_investigator_only_sees_own_assigned_cases_regardless_of_status(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(db_sessionmaker, user_id="U_INV1", username="inv1")
    _seed_user(db_sessionmaker, user_id="U_INV2", username="inv2")
    _seed_case(
        db_sessionmaker, case_id="CASE_MINE_NEW", primary_account_id="A1",
        account_ids=["A1"], assigned_to="U_INV1", status=CaseStatus.NEW,
    )
    _seed_case(
        db_sessionmaker, case_id="CASE_MINE_CLOSED", primary_account_id="A2",
        account_ids=["A2"], assigned_to="U_INV1", status=CaseStatus.CLOSED_FP,
    )
    _seed_case(
        db_sessionmaker, case_id="CASE_OTHERS", primary_account_id="A3",
        account_ids=["A3"], assigned_to="U_INV2", status=CaseStatus.NEW,
    )
    token = _login(client, "inv1")

    resp = client.get("/cases", headers=_auth_headers(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_count"] == 2
    ids = {item["case_id"] for item in body["items"]}
    assert ids == {"CASE_MINE_NEW", "CASE_MINE_CLOSED"}


def test_admin_only_sees_awaiting_review_or_escalated_cases(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    _seed_user(
        db_sessionmaker, user_id="U_ADMIN", username="admin1", role=UserRole.ADMIN_COMPLIANCE
    )
    _seed_case(
        db_sessionmaker, case_id="CASE_NEW", primary_account_id="A1",
        account_ids=["A1"], assigned_to="U_INV", status=CaseStatus.NEW,
    )
    _seed_case(
        db_sessionmaker, case_id="CASE_AWAITING", primary_account_id="A2",
        account_ids=["A2"], assigned_to="U_INV", status=CaseStatus.AWAITING_REVIEW,
    )
    _seed_case(
        db_sessionmaker, case_id="CASE_ESCALATED", primary_account_id="A3",
        account_ids=["A3"], assigned_to="U_INV", status=CaseStatus.ESCALATED,
    )
    _seed_case(
        db_sessionmaker, case_id="CASE_CLOSED", primary_account_id="A4",
        account_ids=["A4"], assigned_to="U_INV", status=CaseStatus.CLOSED_FP,
    )
    admin_token = _login(client, "admin1")

    resp = client.get("/cases", headers=_auth_headers(admin_token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_count"] == 2
    ids = {item["case_id"] for item in body["items"]}
    assert ids == {"CASE_AWAITING", "CASE_ESCALATED"}


def test_admin_out_of_set_status_filter_returns_400(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(
        db_sessionmaker, user_id="U_ADMIN", username="admin1", role=UserRole.ADMIN_COMPLIANCE
    )
    admin_token = _login(client, "admin1")

    resp = client.get(
        "/cases", params={"status": "NEW"}, headers=_auth_headers(admin_token)
    )
    assert resp.status_code == 400


def test_admin_status_filter_within_set_narrows(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    _seed_user(
        db_sessionmaker, user_id="U_ADMIN", username="admin1", role=UserRole.ADMIN_COMPLIANCE
    )
    _seed_case(
        db_sessionmaker, case_id="CASE_AWAITING", primary_account_id="A1",
        account_ids=["A1"], assigned_to="U_INV", status=CaseStatus.AWAITING_REVIEW,
    )
    _seed_case(
        db_sessionmaker, case_id="CASE_ESCALATED", primary_account_id="A2",
        account_ids=["A2"], assigned_to="U_INV", status=CaseStatus.ESCALATED,
    )
    admin_token = _login(client, "admin1")

    resp = client.get(
        "/cases", params={"status": "ESCALATED"}, headers=_auth_headers(admin_token)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_count"] == 1
    assert body["items"][0]["case_id"] == "CASE_ESCALATED"


def test_investigator_status_filter_narrows_own_queue(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(db_sessionmaker, user_id="U_INV1", username="inv1")
    _seed_case(
        db_sessionmaker, case_id="CASE_NEW", primary_account_id="A1",
        account_ids=["A1"], assigned_to="U_INV1", status=CaseStatus.NEW,
    )
    _seed_case(
        db_sessionmaker, case_id="CASE_CLOSED", primary_account_id="A2",
        account_ids=["A2"], assigned_to="U_INV1", status=CaseStatus.CLOSED_TP,
    )
    token = _login(client, "inv1")

    resp = client.get(
        "/cases", params={"status": "CLOSED_TP"}, headers=_auth_headers(token)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_count"] == 1
    assert body["items"][0]["case_id"] == "CASE_CLOSED"


def test_cases_pagination_and_total_count(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    for i in range(5):
        _seed_case(
            db_sessionmaker, case_id=f"CASE{i}", primary_account_id=f"A{i}",
            account_ids=[f"A{i}"], assigned_to="U_INV", status=CaseStatus.NEW,
        )
    token = _login(client, "inv1")

    page1 = client.get(
        "/cases", params={"limit": 2, "offset": 0}, headers=_auth_headers(token)
    )
    assert page1.status_code == 200
    body1 = page1.json()
    assert body1["total_count"] == 5
    assert len(body1["items"]) == 2
    assert body1["limit"] == 2
    assert body1["offset"] == 0

    page3 = client.get(
        "/cases", params={"limit": 2, "offset": 4}, headers=_auth_headers(token)
    )
    assert page3.status_code == 200
    body3 = page3.json()
    assert body3["total_count"] == 5
    assert len(body3["items"]) == 1


def test_cases_default_sort_is_updated_at_desc(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    # Seeded in this order -- `created_at`/`updated_at` both default to
    # `utcnow()` at insert time, so this order is also the ascending
    # `updated_at` order.
    _seed_case(
        db_sessionmaker, case_id="CASE_OLDEST", primary_account_id="A1",
        account_ids=["A1"], assigned_to="U_INV", status=CaseStatus.NEW,
    )
    _seed_case(
        db_sessionmaker, case_id="CASE_MIDDLE", primary_account_id="A2",
        account_ids=["A2"], assigned_to="U_INV", status=CaseStatus.NEW,
    )
    _seed_case(
        db_sessionmaker, case_id="CASE_NEWEST", primary_account_id="A3",
        account_ids=["A3"], assigned_to="U_INV", status=CaseStatus.NEW,
    )
    token = _login(client, "inv1")

    resp = client.get("/cases", headers=_auth_headers(token))
    assert resp.status_code == 200
    body = resp.json()
    assert [item["case_id"] for item in body["items"]] == [
        "CASE_NEWEST", "CASE_MIDDLE", "CASE_OLDEST",
    ]


def test_cases_rejects_invalid_sort(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    token = _login(client, "inv1")

    resp = client.get(
        "/cases", params={"sort": "nonsense"}, headers=_auth_headers(token)
    )
    assert resp.status_code == 400


# ── POST /cases/{case_id}/start: the missing ASSIGNED -> IN_PROGRESS step ──


def test_start_investigation_succeeds_from_assigned(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    _seed_case(
        db_sessionmaker, case_id="CASE1", primary_account_id="A1", account_ids=["A1"],
        assigned_to="U_INV", status=CaseStatus.ASSIGNED,
    )
    token = _login(client, "inv1")

    resp = client.post("/cases/CASE1/start", headers=_auth_headers(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["case_id"] == "CASE1"
    assert body["status"] == "IN_PROGRESS"

    with db_sessionmaker() as db:
        case = CaseRepository(db).get("CASE1")
        assert case is not None
        assert case.status == CaseStatus.IN_PROGRESS

    # Now legally reachable, closing the gap this route exists to fix:
    # ASSIGNED could never reach ESCALATED directly (correctly rejected),
    # but IN_PROGRESS -> ESCALATED is legal once /start has run.
    resp = client.post(
        "/cases/CASE1/decision",
        json={"decision": "escalate", "reason": "needs compliance review"},
        headers=_auth_headers(token),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ESCALATED"


def test_start_investigation_illegal_transition_returns_409(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    _seed_case(
        db_sessionmaker, case_id="CASE1", primary_account_id="A1", account_ids=["A1"],
        assigned_to="U_INV", status=CaseStatus.IN_PROGRESS,  # already past ASSIGNED
    )
    token = _login(client, "inv1")

    resp = client.post("/cases/CASE1/start", headers=_auth_headers(token))
    assert resp.status_code == 409

    with db_sessionmaker() as db:
        case = CaseRepository(db).get("CASE1")
        assert case is not None
        assert case.status == CaseStatus.IN_PROGRESS  # unchanged


def test_start_investigation_from_new_returns_409(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    _seed_case(
        db_sessionmaker, case_id="CASE1", primary_account_id="A1", account_ids=["A1"],
        assigned_to="U_INV", status=CaseStatus.NEW,
    )
    token = _login(client, "inv1")

    resp = client.post("/cases/CASE1/start", headers=_auth_headers(token))
    assert resp.status_code == 409


def test_start_investigation_requires_case_access(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    """`/start` is a real state mutation and stays assignment-gated, unlike
    the read-only GET routes this same bug-fix pass widened."""
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    _seed_user(db_sessionmaker, user_id="U_INV2", username="inv2")
    _seed_case(
        db_sessionmaker, case_id="CASE1", primary_account_id="A1", account_ids=["A1"],
        assigned_to="U_INV", status=CaseStatus.ASSIGNED,
    )
    other_token = _login(client, "inv2")

    resp = client.post("/cases/CASE1/start", headers=_auth_headers(other_token))
    assert resp.status_code == 403


# ── GET /cases/{case_id}: single-case lookup ───────────────────────────────


def test_get_single_case_returns_case_list_item_shape(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    _seed_case(
        db_sessionmaker, case_id="CASE1", primary_account_id="A1", account_ids=["A1"],
        assigned_to="U_INV", priority=Priority.P1,
    )
    token = _login(client, "inv1")

    resp = client.get("/cases/CASE1", headers=_auth_headers(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["case_id"] == "CASE1"
    assert body["primary_account_id"] == "A1"
    assert body["assigned_to"] == "U_INV"
    assert body["priority"] == "P1"


def test_get_single_case_404s_for_unknown_case_id(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    token = _login(client, "inv1")

    resp = client.get("/cases/NOPE", headers=_auth_headers(token))
    assert resp.status_code == 404


def test_get_single_case_is_read_access_not_assignment_gated(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    """The exact gap this route exists to close: Similar Historical Cases /
    Previous Investigation History surface other investigators' case_ids
    already; this route lets an investigator actually open one."""
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    _seed_user(db_sessionmaker, user_id="U_INV2", username="inv2")
    _seed_case(
        db_sessionmaker, case_id="CASE1", primary_account_id="A1", account_ids=["A1"],
        assigned_to="U_INV",
    )
    other_token = _login(client, "inv2")

    resp = client.get("/cases/CASE1", headers=_auth_headers(other_token))
    assert resp.status_code == 200
    assert resp.json()["case_id"] == "CASE1"


def test_get_single_case_requires_authentication(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    _seed_case(
        db_sessionmaker, case_id="CASE1", primary_account_id="A1", account_ids=["A1"],
        assigned_to=None,
    )
    resp = client.get("/cases/CASE1")
    assert resp.status_code == 401


# ── RBAC read/write split, end to end on one case ──────────────────────────


def test_rbac_read_write_split_unassigned_investigator(
    client: TestClient, db_sessionmaker: sessionmaker[Session]
) -> None:
    """An unassigned Investigator can now GET a case's L1 detail (the RBAC
    read/write split this bug-fix pass adds), but every write route --
    `/decision` and the new `/start` -- still 403s for them, unchanged."""
    _seed_user(db_sessionmaker, user_id="U_INV", username="inv1")
    _seed_user(db_sessionmaker, user_id="U_INV2", username="inv2")
    _seed_case(
        db_sessionmaker, case_id="CASE1", primary_account_id="A1", account_ids=["A1"],
        assigned_to="U_INV", status=CaseStatus.IN_PROGRESS,
    )
    other_token = _login(client, "inv2")

    read_routes = [
        "/cases/CASE1",
        "/cases/CASE1/summary/alerts",
        "/cases/CASE1/accounts/A1/customer-snapshot",
        "/cases/CASE1/accounts/A1/geo-risk",
        "/cases/CASE1/accounts/A1/transaction-summary",
        "/cases/CASE1/accounts/A1/transaction-purpose",
        "/cases/CASE1/accounts/A1/previous-alerts",
        "/cases/CASE1/accounts/A1/money-flow",
        "/cases/CASE1/network-risk",
        "/cases/CASE1/similar-cases",
        "/cases/CASE1/accounts/A1/explanation",  # fails open (no API key) but must not 403
    ]
    for path in read_routes:
        resp = client.get(path, headers=_auth_headers(other_token))
        assert resp.status_code == 200, f"{path} did not 200 for an unassigned investigator"

    resp = client.post(
        "/cases/CASE1/decision",
        json={"decision": "escalate", "reason": "test"},
        headers=_auth_headers(other_token),
    )
    assert resp.status_code == 403

    resp = client.post("/cases/CASE1/start", headers=_auth_headers(other_token))
    assert resp.status_code == 403
