"""
`foundation/auth.py` dependencies, called directly (no ASGI/TestClient —
that's `tests/api/test_auth_routes.py`). Seeded via `UserRepository`/
`CaseRepository`/`AccountRepository` the same way
`tests/db/test_repositories_investigation.py` does.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from db.enums import ActorType, CaseLevel, CaseStatus, Priority, UserRole
from db.repositories.investigation import CaseRepository
from db.repositories.platform import UserRepository
from db.repositories.reference import AccountRepository
from foundation.auth import (
    actor_type_for_role,
    get_current_user,
    require_case_access,
    require_role,
)
from foundation.security import create_access_token, hash_password


def _seed_users_and_case(session: Session) -> None:
    AccountRepository(session).create(account_id="A1", actor_type=ActorType.SYSTEM, actor_id=None)
    UserRepository(session).create(
        user_id="INV1",
        username="inv1",
        email="inv1@example.com",
        password_hash=hash_password("pw"),
        role=UserRole.INVESTIGATOR,
        full_name="Investigator One",
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    UserRepository(session).create(
        user_id="INV2",
        username="inv2",
        email="inv2@example.com",
        password_hash=hash_password("pw"),
        role=UserRole.INVESTIGATOR,
        full_name="Investigator Two",
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    UserRepository(session).create(
        user_id="ADMIN1",
        username="admin1",
        email="admin1@example.com",
        password_hash=hash_password("pw"),
        role=UserRole.ADMIN_COMPLIANCE,
        full_name="Admin One",
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    UserRepository(session).create(
        user_id="INACTIVE1",
        username="inactive1",
        email="inactive1@example.com",
        password_hash=hash_password("pw"),
        role=UserRole.INVESTIGATOR,
        full_name="Inactive One",
        active=False,
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    CaseRepository(session).create(
        case_id="CASE1",
        primary_account_id="A1",
        status=CaseStatus.ASSIGNED,
        level=CaseLevel.L1,
        priority=Priority.P2,
        assigned_to="INV1",
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    session.commit()


def _bearer(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


# ── actor_type_for_role ──


def test_actor_type_for_role_maps_admin_and_investigator() -> None:
    assert actor_type_for_role(UserRole.ADMIN_COMPLIANCE) == ActorType.ADMIN
    assert actor_type_for_role(UserRole.INVESTIGATOR) == ActorType.INVESTIGATOR


# ── get_current_user ──


def test_get_current_user_valid_token(session: Session) -> None:
    _seed_users_and_case(session)
    token = create_access_token(user_id="INV1", role=UserRole.INVESTIGATOR.value)
    user = get_current_user(credentials=_bearer(token), db=session)
    assert user.user_id == "INV1"


def test_get_current_user_missing_token(session: Session) -> None:
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(credentials=None, db=session)
    assert exc_info.value.status_code == 401


def test_get_current_user_garbage_token(session: Session) -> None:
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(credentials=_bearer("not-a-real-token"), db=session)
    assert exc_info.value.status_code == 401


def test_get_current_user_expired_token(session: Session) -> None:
    _seed_users_and_case(session)
    from foundation.config import get_settings

    settings = get_settings()
    issued_at = datetime.now(UTC) - timedelta(minutes=settings.jwt_expiry_minutes + 10)
    token = create_access_token(
        user_id="INV1", role=UserRole.INVESTIGATOR.value, now=issued_at
    )
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(credentials=_bearer(token), db=session)
    assert exc_info.value.status_code == 401


def test_get_current_user_deactivated_user(session: Session) -> None:
    _seed_users_and_case(session)
    token = create_access_token(user_id="INACTIVE1", role=UserRole.INVESTIGATOR.value)
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(credentials=_bearer(token), db=session)
    assert exc_info.value.status_code == 401


def test_get_current_user_deleted_user_id(session: Session) -> None:
    _seed_users_and_case(session)
    token = create_access_token(user_id="GHOST", role=UserRole.INVESTIGATOR.value)
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(credentials=_bearer(token), db=session)
    assert exc_info.value.status_code == 401


# ── require_role ──


def test_require_role_allows_matching_role(session: Session) -> None:
    _seed_users_and_case(session)
    admin = UserRepository(session).get("ADMIN1")
    assert admin is not None
    checker = require_role(UserRole.ADMIN_COMPLIANCE)
    assert checker(user=admin) is admin


def test_require_role_rejects_non_matching_role(session: Session) -> None:
    _seed_users_and_case(session)
    investigator = UserRepository(session).get("INV1")
    assert investigator is not None
    checker = require_role(UserRole.ADMIN_COMPLIANCE)
    with pytest.raises(HTTPException) as exc_info:
        checker(user=investigator)
    assert exc_info.value.status_code == 403


# ── require_case_access ──


def test_require_case_access_assigned_investigator_passes(session: Session) -> None:
    _seed_users_and_case(session)
    investigator = UserRepository(session).get("INV1")
    assert investigator is not None
    result = require_case_access("CASE1", user=investigator, db=session)
    assert result is investigator


def test_require_case_access_unassigned_investigator_forbidden(session: Session) -> None:
    _seed_users_and_case(session)
    other_investigator = UserRepository(session).get("INV2")
    assert other_investigator is not None
    with pytest.raises(HTTPException) as exc_info:
        require_case_access("CASE1", user=other_investigator, db=session)
    assert exc_info.value.status_code == 403


def test_require_case_access_admin_always_passes(session: Session) -> None:
    _seed_users_and_case(session)
    admin = UserRepository(session).get("ADMIN1")
    assert admin is not None
    result = require_case_access("CASE1", user=admin, db=session)
    assert result is admin


def test_require_case_access_missing_case_not_found(session: Session) -> None:
    _seed_users_and_case(session)
    investigator = UserRepository(session).get("INV1")
    assert investigator is not None
    with pytest.raises(HTTPException) as exc_info:
        require_case_access("NOPE", user=investigator, db=session)
    assert exc_info.value.status_code == 404
