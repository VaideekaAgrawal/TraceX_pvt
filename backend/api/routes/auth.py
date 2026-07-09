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
from foundation.auth import actor_type_for_role, get_current_user
from foundation.security import create_access_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])

# Generic message for every login failure mode (wrong password, unknown
# username, deactivated user) — deliberately identical so the response can't
# be used to enumerate valid usernames or distinguish "no such user" from
# "wrong password" or "account disabled".
_INVALID_CREDENTIALS = "Invalid username or password"


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
def login(body: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    repo = UserRepository(db)
    user = repo.get_by_username(body.username)
    if (
        user is None
        or not user.active
        or not verify_password(body.password, user.password_hash)
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, _INVALID_CREDENTIALS)

    repo.record_login(
        user.user_id,
        actor_type=actor_type_for_role(user.role),
        actor_id=user.user_id,
    )
    db.commit()

    token = create_access_token(user_id=user.user_id, role=user.role.value)
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
