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
what other investigators are doing on cases they're not assigned to.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.enums import UserRole
from db.models.platform import User
from db.repositories.platform import AuditLogRepository
from db.session import get_db
from foundation.auth import get_current_user

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


def _resolve_actor_id_filter(params: _AuditLogParams, user: User) -> str | None:
    """The RBAC-scoping decision described in this module's docstring:
    Investigators are pinned to their own `actor_id` regardless of what
    they passed (403 if they explicitly asked for someone else's);
    Admin/Compliance's `actor_id` filter passes through unchanged."""
    if user.role == UserRole.ADMIN_COMPLIANCE:
        return params.actor_id
    if params.actor_id is not None and params.actor_id != user.user_id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Investigators may only view their own actions"
        )
    return user.user_id


@router.get("/audit-log", response_model=AuditLogListResponse)
def list_audit_log(
    params: _AuditLogParams = Depends(),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AuditLogListResponse:
    actor_id = _resolve_actor_id_filter(params, user)
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
