"""`/watchlist` — watchlist management (ROADMAP Phase 11).

Adding/removing a watchlisted entity is a compliance function, so every mutating
route is gated to `ADMIN_COMPLIANCE` via `require_role`; listing is open to any
authenticated user (an investigator can see what's monitored). Screening itself
(auto-escalating alerts that touch a watchlisted entity) happens in the detection
pipeline — see `investigation.watchlist`.
"""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from db.enums import UserRole, WatchEntityType
from db.models.platform import User, Watchlist
from db.repositories.platform import WatchlistRepository
from db.session import get_db
from foundation.auth import actor_type_for_role, get_current_user, require_role
from investigation.watchlist import WatchlistAlertRef, enrich_entry

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


class WatchlistEntryModel(BaseModel):
    entry_id: str
    entity_type: str
    entity_value: str
    reason: str | None
    added_by: str
    active: bool
    created_at: datetime
    #: Resolved display name (`Customer.name`, direct or via the owning
    #: customer for an ACCOUNT entry) -- `None` for DEVICE/MERCHANT/COMPANY,
    #: which have no backing column to resolve against.
    display_name: str | None = None
    #: `Account.current_risk_score` for an ACCOUNT entry; always `None` for
    #: CUSTOMER (no per-customer numeric score exists, only the coarse
    #: `risk_rating` enum) and for DEVICE/MERCHANT/COMPANY.
    current_risk: float | None = None
    #: Most recent `Transaction.timestamp` touching the entry's account(s).
    latest_activity: datetime | None = None
    #: Every alert raised at/after this entry's `created_at`, newest first --
    #: what makes an entry clickable through to its alert(s)/case(s).
    alerts: list[WatchlistAlertRef] = Field(default_factory=list)


class AddWatchlistRequest(BaseModel):
    entity_type: WatchEntityType
    entity_value: str = Field(min_length=1, max_length=200)
    reason: str | None = Field(default=None, max_length=1000)


def _to_model(e: Watchlist) -> WatchlistEntryModel:
    """The base fields only, no enrichment -- `add_watchlist`'s response
    (a freshly-created/idempotently-returned entry has nothing to enrich
    yet worth an extra query round-trip for)."""
    return WatchlistEntryModel(
        entry_id=e.entry_id, entity_type=str(e.entity_type), entity_value=e.entity_value,
        reason=e.reason, added_by=e.added_by, active=e.active, created_at=e.created_at,
    )


@router.get("", response_model=list[WatchlistEntryModel])
def list_watchlist(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[WatchlistEntryModel]:
    """Every active watchlist entry, enriched with display name / current
    risk / latest activity / post-entry alert history (`investigation.
    watchlist.enrich_entry`) so the frontend doesn't have to fake these
    client-side."""
    result = []
    for e in WatchlistRepository(db).list_active():
        enrichment = enrich_entry(db, e)
        result.append(
            WatchlistEntryModel(
                entry_id=e.entry_id, entity_type=str(e.entity_type),
                entity_value=e.entity_value, reason=e.reason, added_by=e.added_by,
                active=e.active, created_at=e.created_at,
                display_name=enrichment.display_name, current_risk=enrichment.current_risk,
                latest_activity=enrichment.latest_activity, alerts=enrichment.alerts,
            )
        )
    return result


@router.post("", response_model=WatchlistEntryModel, status_code=status.HTTP_201_CREATED)
def add_watchlist(
    body: AddWatchlistRequest,
    user: User = Depends(require_role(UserRole.ADMIN_COMPLIANCE)),
    db: Session = Depends(get_db),
) -> WatchlistEntryModel:
    """Add an entity to the watchlist (compliance only). Idempotent on
    (entity_type, entity_value): re-adding an already-active entry returns it
    rather than creating a duplicate."""
    repo = WatchlistRepository(db)
    existing = repo.get_active_by_value(body.entity_type, body.entity_value)
    if existing is not None:
        entry = existing
    else:
        entry = repo.create(
            entry_id=str(uuid4()),
            entity_type=body.entity_type,
            entity_value=body.entity_value,
            reason=body.reason,
            added_by=user.user_id,
            actor_type=actor_type_for_role(user.role),
            actor_id=user.user_id,
        )
        db.commit()
    return _to_model(entry)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_watchlist(
    entry_id: str,
    user: User = Depends(require_role(UserRole.ADMIN_COMPLIANCE)),
    db: Session = Depends(get_db),
) -> None:
    """Deactivate a watchlist entry (soft delete, compliance only)."""
    try:
        WatchlistRepository(db).deactivate(
            entry_id, actor_type=actor_type_for_role(user.role), actor_id=user.user_id
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    db.commit()
