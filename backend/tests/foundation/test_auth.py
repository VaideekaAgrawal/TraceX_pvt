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
from foundation.config import get_settings
from foundation.security import create_access_token, hash_password

# Computed once and reused across every seeded user in this module — these
# are throwaway fixture passwords never checked for their actual value, so
# there's no isolation reason to re-pay bcrypt's cost per user (code review,
# Phase 2 finding #9).
_HASHED_PASSWORD = hash_password("pw")

# `get_current_user` now requires an explicit `settings=` (it's a request-
# scoped `Depends(get_app_settings)` param when called through FastAPI, but
# these tests call it directly) — use the same default `get_settings()`
# instance `create_access_token`'s own default resolves to, so tokens
# created and decoded in this file are consistent.
_SETTINGS = get_settings()


def _create_user(
    session: Session,
    *,
    user_id: str,
    username: str,
    role: UserRole = UserRole.INVESTIGATOR,
    active: bool = True,
) -> None:
    UserRepository(session).create(
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


def _seed_users_and_case(session: Session) -> None:
    AccountRepository(session).create(account_id="A1", actor_type=ActorType.SYSTEM, actor_id=None)
    _create_user(session, user_id="INV1", username="inv1", role=UserRole.INVESTIGATOR)
    _create_user(session, user_id="INV2", username="inv2", role=UserRole.INVESTIGATOR)
    _create_user(session, user_id="ADMIN1", username="admin1", role=UserRole.ADMIN_COMPLIANCE)
    _create_user(
        session, user_id="INACTIVE1", username="inactive1", role=UserRole.INVESTIGATOR, active=False
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
    token = create_access_token(user_id="INV1", role=UserRole.INVESTIGATOR, settings=_SETTINGS)
    user = get_current_user(credentials=_bearer(token), db=session, settings=_SETTINGS)
    assert user.user_id == "INV1"


def test_get_current_user_missing_token(session: Session) -> None:
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(credentials=None, db=session, settings=_SETTINGS)
    assert exc_info.value.status_code == 401


def test_get_current_user_garbage_token(session: Session) -> None:
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(credentials=_bearer("not-a-real-token"), db=session, settings=_SETTINGS)
    assert exc_info.value.status_code == 401


def test_get_current_user_expired_token(session: Session) -> None:
    _seed_users_and_case(session)
    issued_at = datetime.now(UTC) - timedelta(minutes=_SETTINGS.jwt_expiry_minutes + 10)
    token = create_access_token(
        user_id="INV1", role=UserRole.INVESTIGATOR, settings=_SETTINGS, now=issued_at
    )
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(credentials=_bearer(token), db=session, settings=_SETTINGS)
    assert exc_info.value.status_code == 401


def test_get_current_user_deactivated_user(session: Session) -> None:
    _seed_users_and_case(session)
    token = create_access_token(
        user_id="INACTIVE1", role=UserRole.INVESTIGATOR, settings=_SETTINGS
    )
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(credentials=_bearer(token), db=session, settings=_SETTINGS)
    assert exc_info.value.status_code == 401


def test_get_current_user_deleted_user_id(session: Session) -> None:
    _seed_users_and_case(session)
    token = create_access_token(user_id="GHOST", role=UserRole.INVESTIGATOR, settings=_SETTINGS)
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(credentials=_bearer(token), db=session, settings=_SETTINGS)
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
# Returns the loaded `Case`, not `User` (code review, Phase 2 finding #6).


def test_require_case_access_assigned_investigator_passes(session: Session) -> None:
    _seed_users_and_case(session)
    investigator = UserRepository(session).get("INV1")
    assert investigator is not None
    result = require_case_access("CASE1", user=investigator, db=session)
    assert result.case_id == "CASE1"


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
    assert result.case_id == "CASE1"


def test_require_case_access_missing_case_not_found(session: Session) -> None:
    _seed_users_and_case(session)
    investigator = UserRepository(session).get("INV1")
    assert investigator is not None
    with pytest.raises(HTTPException) as exc_info:
        require_case_access("NOPE", user=investigator, db=session)
    assert exc_info.value.status_code == 404
