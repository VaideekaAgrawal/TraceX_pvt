"""
Pure auth primitives — password hashing and JWT encode/decode. No FastAPI
import here (that lives in `foundation/auth.py`, which needs `Depends(...)`
against a DB session); this module is usable standalone and unit-testable
without spinning up any request machinery.

`create_access_token`/`decode_access_token` implement the claims contract
this phase settles on: `sub` (user_id), `role` (`db.enums.UserRole` value),
`iat`, `exp`. No refresh tokens, no other claims — see `docs/ROADMAP.md`
Phase 2 and this phase's plan for why that's deliberately out of scope.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt
from passlib.context import CryptContext

from foundation.config import Settings, get_settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _pwd_context.verify(password, password_hash)


@dataclass(frozen=True)
class TokenPayload:
    """Decoded JWT claims — `sub` is the `users.user_id`, `role` is the raw
    `db.enums.UserRole` string value (not re-validated against the enum
    here; `foundation/auth.py::get_current_user` re-fetches the real `User`
    row and treats its `role`/`active` columns as the authorization source
    of truth, so a stale/forged `role` claim alone can't grant access)."""

    sub: str
    role: str
    iat: datetime
    exp: datetime


def create_access_token(
    *,
    user_id: str,
    role: str,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> str:
    """Sign a JWT for `user_id`/`role`. `settings` param optional (defaults
    to `get_settings()`), mirroring `db.session.build_engine`'s
    testability convention — tests can pass a `Settings(jwt_secret=...)`
    without touching real env/config state."""
    settings = settings if settings is not None else get_settings()
    issued_at = now if now is not None else datetime.now(UTC)
    expires_at = issued_at + timedelta(minutes=settings.jwt_expiry_minutes)
    claims = {
        "sub": user_id,
        "role": role,
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)


class TokenError(Exception):
    """Raised for any invalid/expired/malformed token — callers (mainly
    `foundation.auth.get_current_user`) catch this one type rather than
    reaching into `jose`'s exception hierarchy directly."""


def decode_access_token(token: str, *, settings: Settings | None = None) -> TokenPayload:
    settings = settings if settings is not None else get_settings()
    try:
        claims = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise TokenError(str(exc)) from exc
    try:
        return TokenPayload(
            sub=claims["sub"],
            role=claims["role"],
            iat=datetime.fromtimestamp(claims["iat"], tz=UTC),
            exp=datetime.fromtimestamp(claims["exp"], tz=UTC),
        )
    except KeyError as exc:
        raise TokenError(f"missing claim: {exc}") from exc
