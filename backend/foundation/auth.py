"""
FastAPI auth dependencies: `get_current_user`, `require_role`,
`require_case_access`, `get_app_settings`. Split out from
`foundation/security.py` (which stays FastAPI-free) because these need
`Depends(get_db)` against a live Session.

`get_current_user` re-fetches the `User` row from the DB by the token's
`sub` on every request and treats `User.active` as the authorization source
of truth (not just the JWT's `role` claim) — costs nothing extra since the
DB session is already a request-scoped dependency, and it means
deactivating a user takes effect immediately with no token-revocation
infrastructure needed.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from db.enums import ActorType, UserRole
from db.models.investigation import Case
from db.models.platform import User
from db.models.reference import Account
from db.repositories.investigation import CaseAccountRepository, CaseRepository
from db.repositories.platform import UserRepository
from db.repositories.reference import AccountRepository
from db.session import get_db
from foundation.config import Settings
from foundation.security import TokenError, decode_access_token

_bearer_scheme = HTTPBearer(auto_error=False)


def actor_type_for_role(role: UserRole) -> ActorType:
    """Bridge `UserRole` (RBAC role, `db.enums`) to `ActorType`
    (`audit_log.actor_type`) — the two enums are intentionally distinct
    (`db/enums.py`: `ActorType` also has `SYSTEM`/`AI`, which no `UserRole`
    maps to), so this is a translation at the auth boundary, not a "fix" of
    that mismatch. Exhaustive: every known `UserRole` member has an explicit
    branch, and an unmapped one raises rather than silently mislabeling the
    tamper-evident audit trail (code review, Phase 2) — a wrong-but-silent
    actor_type on every audited row is worse than a loud failure here."""
    if role == UserRole.ADMIN_COMPLIANCE:
        return ActorType.ADMIN
    if role == UserRole.INVESTIGATOR:
        return ActorType.INVESTIGATOR
    raise ValueError(f"unmapped UserRole: {role!r}")


def get_app_settings(request: Request) -> Settings:
    """Read the `Settings` instance `api.app.create_app` resolved and stored
    on `app.state.settings`, so the real request path's JWT encode/decode
    calls use whatever `Settings` was actually passed to
    `create_app(settings=...)` — not the `foundation.security` module-level
    `get_settings()` singleton, which only coincidentally matches when no
    override was given (code review, Phase 2: `login`/`get_current_user`
    previously ignored the app's injected `settings` entirely, so a
    non-default `jwt_secret` passed to `create_app` never actually reached
    token signing/verification)."""
    settings: Settings = request.app.state.settings
    return settings


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> User:
    """Decode the bearer token, re-fetch the `User` row, and reject if
    missing/deactivated. Raises 401 for every failure mode (missing header,
    malformed/expired token, unknown or deactivated user) — deliberately
    the same status for all of them so a caller can't distinguish "no such
    user" from "wrong token" (no user-enumeration signal)."""
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")

    try:
        payload = decode_access_token(credentials.credentials, settings=settings)
    except TokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token") from exc

    user = UserRepository(db).get(payload.sub)
    if user is None or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    return user


def resolve_own_or_all_scope(user: User, requested_id: str | None) -> str | None:
    """Own-vs-all RBAC data-scoping helper (code-review finding, Phase 14:
    promoted out of `api.routes.audit`'s module-private
    `_resolve_actor_id_filter`, where this exact "Investigator forced to
    own id, Admin unscoped" logic used to live inline, non-reusable). A
    plain function, not a `Depends()` dependency -- it needs a query-param
    value the caller already parsed (e.g. `?actor_id=`), not something
    FastAPI can resolve on its own from the request.

    - Admin/Compliance: `requested_id` passes through unchanged (including
      `None`, meaning "everyone").
    - Investigator: pinned to `user.user_id` regardless of what they
      requested -- 403s if they explicitly asked for someone else's,
      otherwise silently forces the scope to their own id (no error for
      the common case of not passing anything at all).

    Currently has exactly one real caller (`api.routes.audit.
    list_audit_log`'s `actor_id` scoping), but is placed here, generically
    named, and not audit-log-specific in its parameters, because `docs/
    FRONTEND_ROADMAP.md`'s Phase 15 `GET /cases` route needs near-identical
    own-vs-all scoping (assigned_to=me for Investigators, broader for
    Admin/Compliance) and can plausibly reuse this same *pattern* even
    though the concrete field differs (case ownership vs. actor_id) --
    deliberately not built out further than this one function; a full
    generic "own-vs-all" framework is not justified by one real caller."""
    if user.role == UserRole.ADMIN_COMPLIANCE:
        return requested_id
    if requested_id is not None and requested_id != user.user_id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Investigators may only view their own actions"
        )
    return user.user_id


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
) -> Case:
    """Data-scoping dependency: an Investigator only reaches their own
    assigned cases; Admin/Compliance bypasses (matches "Admin/Compliance
    closes cases, approves SAR, edits rules" — broader-than-own-queue
    access). 404s if the case doesn't exist at all (don't leak existence to
    a 403 before confirming it), 403s if it exists but isn't this
    investigator's. Returns the loaded `Case` (not `user`) — this dependency
    already had to fetch it to check `assigned_to`, so returning it saves
    every future case route from re-querying; a route that also needs the
    current `User` can add `Depends(get_current_user)` as a separate
    parameter (FastAPI dedupes dependency calls within one request, so
    that's not a second real query) — code review, Phase 2. A plain
    callable, not wired to any route in this phase — Phase 4's case routes
    and the Copilot are the actual callers."""
    case = CaseRepository(db).get(case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    if user.role == UserRole.INVESTIGATOR and case.assigned_to != user.user_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not assigned to this case")
    return case


def _load_scoped_account(account_id: str, case: Case, db: Session) -> tuple[Account, list[str]]:
    """Shared core of `require_case_scoped_account`/`require_case_scoped_
    account_with_ids` -- computes `case`'s scoped account-id set once,
    validates `account_id` against it, and returns both the loaded
    `Account` and that id list, so a caller that needs the full scope set
    (e.g. to build a case-scoped graph) doesn't have to re-query it
    (code-review finding, Phase 6: `api.routes.l2.get_account_graph`/
    `investigation.transaction_search.search`'s account-scoped path were
    both re-running this exact query after this dependency already had the
    answer)."""
    scoped_ids = CaseAccountRepository(db).list_account_ids_for_case(case.case_id)
    if account_id not in scoped_ids:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Account not in this case's scope")
    account = AccountRepository(db).get(account_id)
    if account is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Account not found")
    return account, scoped_ids


def require_case_scoped_account(
    account_id: str,
    case: Case = Depends(require_case_access),
    db: Session = Depends(get_db),
) -> Account:
    """404s if `account_id` isn't in `case`'s `case_accounts` scope (don't
    leak "this account exists elsewhere in the system" to an investigator
    who isn't scoped to it), else loads and returns the `Account` row.

    Moved verbatim from `api.routes.cases` (ROADMAP Phase 6 — `api.routes.l2`
    is its second real caller, meeting this codebase's own "promote on
    second real caller" convention already used for e.g.
    `HIGH_PAGERANK_THRESHOLD`/`CLOSING_REWARD`/`list_account_ids_for_case`).
    No behavior change from the `cases.py` original."""
    account, _ = _load_scoped_account(account_id, case, db)
    return account


def require_case_scoped_account_with_ids(
    account_id: str,
    case: Case = Depends(require_case_access),
    db: Session = Depends(get_db),
) -> tuple[Account, list[str]]:
    """Sibling of `require_case_scoped_account` that also returns `case`'s
    full scoped account-id list, for the handful of routes that need both
    the validated `Account` and the full scope set in the same request
    (code-review finding, Phase 6, see `_load_scoped_account`). Most
    account-scoped routes should keep using the plain `require_case_scoped_
    account` — only switch a route to this one when it would otherwise
    re-run `CaseAccountRepository.list_account_ids_for_case` itself."""
    return _load_scoped_account(account_id, case, db)
