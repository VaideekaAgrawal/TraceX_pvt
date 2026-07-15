"""
`GET /audit-log` -- the unified queryable audit trail surface (ROADMAP
Phase 14). Read-only: `AuditLogRepository` deliberately has no `create()` of
its own (`db.repositories.platform`'s module docstring -- every write goes
through `db.repositories._audit.append_audit_log`, called internally by
every other repository's create/update).

RBAC here is data-scoping, not a blanket role gate (`foundation.auth.
require_role` isn't used): both roles can call this route, but an
Investigator is forced to see only their own actions (`actor_id=<self>`,
overriding whatever they passed), while Admin/Compliance can see anyone's
(`actor_id=None` by default, or any explicit value) -- an audit trail an
Investigator could freely scope to another user's `actor_id` would leak
what other investigators are doing on cases they're not assigned to. The
scoping decision itself is `foundation.auth.resolve_own_or_all_scope`
(code-review finding, Phase 14: promoted out of this module so `docs/
FRONTEND_ROADMAP.md`'s Phase 15 `GET /cases` route can plausibly reuse the
same pattern) -- this module just calls it.

Known limitation (code-review finding, Phase 14 -- see `list_audit_log`'s
docstring): "own actions only" scoping means an Investigator's
notification bell can't yet surface "a case was just assigned to me",
since the audit row for that action is attributed to the assigning Admin,
not to them.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.models.platform import User
from db.repositories.platform import AuditLogRepository
from db.session import get_db
from foundation.auth import get_current_user, resolve_own_or_all_scope

router = APIRouter(tags=["audit"])


# ── Response models ──────────────────────────────────────────────────────


class AuditLogItem(BaseModel):
    id: int
    actor_type: str
    actor_id: str | None
    action: str
    entity_type: str
    entity_id: str | None
    case_id: str | None
    details: dict[str, Any] | None
    created_at: datetime


class AuditLogListResponse(BaseModel):
    items: list[AuditLogItem]
    total_count: int
    limit: int
    offset: int


# ── Query params ─────────────────────────────────────────────────────────


@dataclass
class _AuditLogParams:
    case_id: str | None = Query(default=None)
    actor_id: str | None = Query(default=None)
    action: list[str] | None = Query(default=None)
    since: datetime | None = Query(default=None)
    limit: int = Query(default=200, le=1000)
    offset: int = Query(default=0, ge=0)


@router.get("/audit-log", response_model=AuditLogListResponse)
def list_audit_log(
    params: _AuditLogParams = Depends(),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AuditLogListResponse:
    """`actor_id` scoping is `foundation.auth.resolve_own_or_all_scope`:
    Investigators are pinned to their own actions, Admin/Compliance is
    unscoped by default (see module docstring).

    Known limitation (code-review finding, Phase 14, deliberately left
    unaddressed this phase): case-assignment audit rows (`case_assigned`/
    `case_reassigned`) carry the *assigning* Admin/Compliance user's
    `actor_id`, not the *receiving* Investigator's -- so an Investigator,
    pinned to `actor_id=self` here, can never see an audit row for "a case
    was just assigned to me" by someone else, only actions they personally
    performed. This means a notification-bell feature built directly on
    this endpoint cannot surface that event. The real fix needs `GET
    /cases` (explicitly Phase 15's scope, not this one) so the
    notification/audit layer can instead query "cases assigned to me"
    independent of who performed the assigning action."""
    actor_id = resolve_own_or_all_scope(user, params.actor_id)
    repo = AuditLogRepository(db)
    filter_kwargs: dict[str, Any] = {
        "case_id": params.case_id,
        "actor_id": actor_id,
        "action": params.action,
        "since": params.since,
    }
    total_count = repo.count_filtered(**filter_kwargs)
    rows = repo.list_filtered(**filter_kwargs, limit=params.limit, offset=params.offset)
    items = [
        AuditLogItem(
            id=r.id,
            actor_type=str(r.actor_type),
            actor_id=r.actor_id,
            action=r.action,
            entity_type=r.entity_type,
            entity_id=r.entity_id,
            case_id=r.case_id,
            details=r.details,
            created_at=r.created_at,
        )
        for r in rows
    ]
    return AuditLogListResponse(
        items=items, total_count=total_count, limit=params.limit, offset=params.offset
    )
