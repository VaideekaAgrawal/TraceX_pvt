"""
FastAPI auth dependencies: `get_current_user`, `require_role`,
`require_case_access`. Split out from `foundation/security.py` (which stays
FastAPI-free) because these need `Depends(get_db)` against a live Session.

`get_current_user` re-fetches the `User` row from the DB by the token's
`sub` on every request and treats `User.active` as the authorization source
of truth (not just the JWT's `role` claim) — costs nothing extra since the
DB session is already a request-scoped dependency, and it means
deactivating a user takes effect immediately with no token-revocation
infrastructure needed.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from db.enums import ActorType, UserRole
from db.models.platform import User
from db.repositories.investigation import CaseRepository
from db.repositories.platform import UserRepository
from db.session import get_db
from foundation.security import TokenError, decode_access_token

_bearer_scheme = HTTPBearer(auto_error=False)


def actor_type_for_role(role: UserRole) -> ActorType:
    """Bridge `UserRole` (RBAC role, `db.enums`) to `ActorType`
    (`audit_log.actor_type`) — the two enums are intentionally distinct
    (`db/enums.py`: `ActorType` also has `SYSTEM`/`AI`, which no `UserRole`
    maps to), so this is a translation at the auth boundary, not a "fix" of
    that mismatch."""
    if role == UserRole.ADMIN_COMPLIANCE:
        return ActorType.ADMIN
    return ActorType.INVESTIGATOR


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Decode the bearer token, re-fetch the `User` row, and reject if
    missing/deactivated. Raises 401 for every failure mode (missing header,
    malformed/expired token, unknown or deactivated user) — deliberately
    the same status for all of them so a caller can't distinguish "no such
    user" from "wrong token" (no user-enumeration signal)."""
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")

    try:
        payload = decode_access_token(credentials.credentials)
    except TokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token") from exc

    user = UserRepository(db).get(payload.sub)
    if user is None or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    return user


def require_role(*roles: UserRole):
    """Dependency factory: `Depends(require_role(UserRole.ADMIN_COMPLIANCE))`.
    403s (not 401 — the caller is authenticated, just not authorized) if
    `user.role` isn't one of `roles`."""

    def _check(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role for this action")
        return user

    return _check


def require_case_access(
    case_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """Data-scoping dependency: an Investigator only reaches their own
    assigned cases; Admin/Compliance bypasses (matches "Admin/Compliance
    closes cases, approves SAR, edits rules" — broader-than-own-queue
    access). 404s if the case doesn't exist at all (don't leak existence to
    a 403 before confirming it), 403s if it exists but isn't this
    investigator's. A plain callable, not wired to any route in this phase
    — Phase 4's case routes and the Copilot are the actual callers."""
    case = CaseRepository(db).get(case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    if user.role == UserRole.INVESTIGATOR and case.assigned_to != user.user_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not assigned to this case")
    return user
