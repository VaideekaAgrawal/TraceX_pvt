"""
`POST /auth/login`, `GET /auth/me` — the only routes this phase adds. All
case/alert/business routes are Phase 4's job (see `docs/ROADMAP.md`).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.models.platform import User
from db.repositories.platform import UserRepository
from db.session import get_db
from foundation.auth import actor_type_for_role, get_app_settings, get_current_user
from foundation.config import Settings
from foundation.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])

# Generic message for every login failure mode (wrong password, unknown
# username, deactivated user) — deliberately identical so the response can't
# be used to enumerate valid usernames or distinguish "no such user" from
# "wrong password" or "account disabled".
_INVALID_CREDENTIALS = "Invalid username or password"

# A fixed dummy hash so a missing/inactive user still pays the same bcrypt
# cost as a real password check. Without this, `user is None` short-circuits
# past `verify_password` and returns in well under 1ms, versus ~375ms for an
# existing user with a wrong password — a large, trivially measurable timing
# side-channel that lets an attacker enumerate valid usernames even though
# the response body is identical (code review, Phase 2).
_DUMMY_PASSWORD_HASH = hash_password("tracex-timing-parity-dummy")


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    user_id: str


class MeResponse(BaseModel):
    user_id: str
    username: str
    email: str
    role: str
    full_name: str


@router.post("/login", response_model=LoginResponse)
def login(
    body: LoginRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> LoginResponse:
    repo = UserRepository(db)
    user = repo.get_by_username(body.username)
    # Always call verify_password (real hash if the user exists, the dummy
    # hash otherwise) so every code path pays the same bcrypt cost — see
    # _DUMMY_PASSWORD_HASH above for why this can't short-circuit.
    password_hash = user.password_hash if user is not None else _DUMMY_PASSWORD_HASH
    password_ok = verify_password(body.password, password_hash)
    if user is None or not user.active or not password_ok:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, _INVALID_CREDENTIALS)

    repo.record_login(
        user.user_id,
        actor_type=actor_type_for_role(user.role),
        actor_id=user.user_id,
    )
    db.commit()

    token = create_access_token(user_id=user.user_id, role=user.role, settings=settings)
    return LoginResponse(access_token=token, role=user.role.value, user_id=user.user_id)


@router.get("/me", response_model=MeResponse)
def me(user: User = Depends(get_current_user)) -> MeResponse:
    return MeResponse(
        user_id=user.user_id,
        username=user.username,
        email=user.email,
        role=user.role.value,
        full_name=user.full_name,
    )
