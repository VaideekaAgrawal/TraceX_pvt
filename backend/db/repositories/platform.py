"""
Repositories for `docs/DATA_SCHEMA.md` §3.5 platform tables: `users`,
`audit_log`, `watchlist`, `ingestion_log`.

`AuditLogRepository` is read-only plus the hash-chain `verify_chain` helper
— every *write* to `audit_log` goes exclusively through
`db.repositories._audit.append_audit_log`, called by every other
repository's `_create`/`_update`. Giving `AuditLogRepository` its own
`create()` would open a second, unaudited path to the same table (an
audit_log row logging an audit_log row is also a nonsensical infinite
regress) — deliberately not built.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select

from db.enums import ActorType, UserRole, WatchEntityType
from db.models.base import utcnow
from db.models.platform import AuditLog, IngestionLog, User, Watchlist
from db.repositories._audit import verify_chain
from db.repositories.base import UNSET, BaseRepository, collect_changes


class UserRepository(BaseRepository[User]):
    model = User
    entity_type = "user"
    pk_attr = "user_id"

    def create(
        self,
        *,
        user_id: str,
        username: str,
        email: str,
        password_hash: str,
        role: UserRole,
        full_name: str,
        active: bool = True,
        actor_type: ActorType,
        actor_id: str | None,
    ) -> User:
        user = User(
            user_id=user_id,
            username=username,
            email=email,
            password_hash=password_hash,
            role=role,
            full_name=full_name,
            active=active,
        )
        return self._create(user, actor_type=actor_type, actor_id=actor_id, action="user_created")

    def update(
        self,
        user_id: str,
        *,
        actor_type: ActorType,
        actor_id: str | None,
        email: str = UNSET,
        password_hash: str = UNSET,
        role: UserRole = UNSET,
        full_name: str = UNSET,
        active: bool = UNSET,
        last_login_at: datetime = UNSET,
    ) -> User:
        user = self.get(user_id)
        if user is None:
            raise ValueError(f"user {user_id!r} does not exist")
        changes = collect_changes(
            email=email,
            password_hash=password_hash,
            role=role,
            full_name=full_name,
            active=active,
            last_login_at=last_login_at,
        )
        return self._update(
            user, changes, actor_type=actor_type, actor_id=actor_id, action="user_updated"
        )

    def deactivate(self, user_id: str, *, actor_type: ActorType, actor_id: str | None) -> User:
        """Soft delete (doc §0: domain rows are never hard-deleted)."""
        return self.update(user_id, active=False, actor_type=actor_type, actor_id=actor_id)

    def record_login(self, user_id: str, *, actor_type: ActorType, actor_id: str | None) -> User:
        return self.update(
            user_id, last_login_at=utcnow(), actor_type=actor_type, actor_id=actor_id
        )

    def get_by_username(self, username: str) -> User | None:
        stmt = select(User).where(User.username == username)
        return self.session.scalars(stmt).first()

    def list_by_role(self, role: UserRole) -> list[User]:
        stmt = select(User).where(User.role == role, User.active.is_(True))
        return list(self.session.scalars(stmt))

    def list_by_ids(self, user_ids: list[str]) -> list[User]:
        """Batched `user_id IN (...)` lookup -- same reasoning as
        `reference.AccountRepository.list_by_ids`/`CustomerRepository.
        list_by_ids` (ROADMAP Phase 14: `GET /alerts` needs the
        `assigned_to` display name for every case on the current page in
        one query, not one `.get()` per row). No chunking -- assumes a
        page-scale id list, not export-scale."""
        if not user_ids:
            return []
        stmt = select(User).where(User.user_id.in_(user_ids))
        return list(self.session.scalars(stmt))


class AuditLogRepository(BaseRepository[AuditLog]):
    model = AuditLog
    entity_type = "audit_log"
    pk_attr = "id"

    def list_for_case(self, case_id: str, *, limit: int = 500) -> list[AuditLog]:
        stmt = (
            select(AuditLog)
            .where(AuditLog.case_id == case_id)
            .order_by(AuditLog.id.asc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt))

    def list_for_entity(self, entity_type: str, entity_id: str) -> list[AuditLog]:
        stmt = (
            select(AuditLog)
            .where(AuditLog.entity_type == entity_type, AuditLog.entity_id == entity_id)
            .order_by(AuditLog.id.asc())
        )
        return list(self.session.scalars(stmt))

    def list_since(self, since: datetime, *, limit: int = 500) -> list[AuditLog]:
        """Powers the Copilot "what changed since last login" digest
        (doc §3.5: diff audit_log since `users.last_login_at`)."""
        stmt = (
            select(AuditLog)
            .where(AuditLog.created_at >= since)
            .order_by(AuditLog.id.asc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt))

    def verify_chain(self) -> bool:
        """Recompute and check the SHA-256 hash chain over every row in
        `id` order. See `db.repositories._audit.verify_chain` for exactly
        what this does and does not prove."""
        return verify_chain(self.session)

    def _filter_clauses(
        self,
        *,
        case_id: str | None = None,
        actor_id: str | None = None,
        action: str | list[str] | None = None,
        since: datetime | None = None,
    ) -> list[Any]:
        """Shared WHERE-clause builder for `list_filtered`/`count_filtered`
        (ROADMAP Phase 14: `GET /audit-log`). `action` accepts either a
        single action string or a list of them (repeated `?action=x&action=y`
        query params on the route side) -- an equality check for the common
        single-action case, an `IN` for the multi-action one."""
        clauses: list[Any] = []
        if case_id is not None:
            clauses.append(AuditLog.case_id == case_id)
        if actor_id is not None:
            clauses.append(AuditLog.actor_id == actor_id)
        if action is not None:
            if isinstance(action, str):
                clauses.append(AuditLog.action == action)
            else:
                clauses.append(AuditLog.action.in_(action))
        if since is not None:
            clauses.append(AuditLog.created_at >= since)
        return clauses

    def list_filtered(
        self,
        *,
        case_id: str | None = None,
        actor_id: str | None = None,
        action: str | list[str] | None = None,
        since: datetime | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[AuditLog]:
        """Most-recent-first (`id DESC`) -- deliberately the opposite order
        of `list_for_case`/`list_since` (both ascending, since they serve
        case-history replay / chronological digests). This method serves a
        "what just happened" feed (`GET /audit-log`, ROADMAP Phase 14),
        where the newest row belongs at the top."""
        clauses = self._filter_clauses(
            case_id=case_id, actor_id=actor_id, action=action, since=since
        )
        stmt = (
            select(AuditLog)
            .where(*clauses)
            .order_by(AuditLog.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.session.scalars(stmt))

    def count_filtered(
        self,
        *,
        case_id: str | None = None,
        actor_id: str | None = None,
        action: str | list[str] | None = None,
        since: datetime | None = None,
    ) -> int:
        clauses = self._filter_clauses(
            case_id=case_id, actor_id=actor_id, action=action, since=since
        )
        stmt = select(func.count()).select_from(AuditLog).where(*clauses)
        return self.session.scalar(stmt) or 0


class WatchlistRepository(BaseRepository[Watchlist]):
    model = Watchlist
    entity_type = "watchlist"
    pk_attr = "entry_id"

    def create(
        self,
        *,
        entry_id: str,
        entity_type: WatchEntityType,
        entity_value: str,
        added_by: str,
        reason: str | None = None,
        active: bool = True,
        expires_at: datetime | None = None,
        actor_type: ActorType,
        actor_id: str | None,
    ) -> Watchlist:
        entry = Watchlist(
            entry_id=entry_id,
            entity_type=entity_type,
            entity_value=entity_value,
            reason=reason,
            added_by=added_by,
            active=active,
            expires_at=expires_at,
        )
        return self._create(
            entry, actor_type=actor_type, actor_id=actor_id, action="watchlist_created"
        )

    def update(
        self,
        entry_id: str,
        *,
        actor_type: ActorType,
        actor_id: str | None,
        reason: str | None = UNSET,
        active: bool = UNSET,
        expires_at: datetime | None = UNSET,
    ) -> Watchlist:
        entry = self.get(entry_id)
        if entry is None:
            raise ValueError(f"watchlist entry {entry_id!r} does not exist")
        changes = collect_changes(reason=reason, active=active, expires_at=expires_at)
        return self._update(
            entry, changes, actor_type=actor_type, actor_id=actor_id, action="watchlist_updated"
        )

    def deactivate(
        self, entry_id: str, *, actor_type: ActorType, actor_id: str | None
    ) -> Watchlist:
        """Soft delete (doc §0)."""
        return self.update(entry_id, active=False, actor_type=actor_type, actor_id=actor_id)

    def list_active(self) -> list[Watchlist]:
        stmt = select(Watchlist).where(Watchlist.active.is_(True))
        return list(self.session.scalars(stmt))

    def get_active_by_value(
        self, entity_type: WatchEntityType, entity_value: str
    ) -> Watchlist | None:
        stmt = select(Watchlist).where(
            Watchlist.entity_type == entity_type,
            Watchlist.entity_value == entity_value,
            Watchlist.active.is_(True),
        )
        return self.session.scalars(stmt).first()


class IngestionLogRepository(BaseRepository[IngestionLog]):
    """Idempotent CSV ingest bookkeeping. The actual CSV parsing/validation
    is the next slice's scope (explicitly out of scope here) — this
    repository only makes the `ingestion_log` row durable and answers "have
    we already ingested this file" (doc §3.5: "prevents double-ingesting
    the same file")."""

    model = IngestionLog
    entity_type = "ingestion_log"
    pk_attr = "file_hash"

    def create(
        self,
        *,
        file_hash: str,
        filename: str,
        status: str,
        business_date: datetime | None = None,
        num_transactions: int = 0,
        num_accounts: int = 0,
        validation: dict | None = None,
        ingested_at: datetime | None = None,
        actor_type: ActorType,
        actor_id: str | None,
    ) -> IngestionLog:
        log = IngestionLog(
            file_hash=file_hash,
            filename=filename,
            business_date=business_date,
            num_transactions=num_transactions,
            num_accounts=num_accounts,
            status=status,
            validation=validation,
            ingested_at=ingested_at if ingested_at is not None else utcnow(),
        )
        return self._create(
            log, actor_type=actor_type, actor_id=actor_id, action="ingestion_log_created"
        )

    def update(
        self,
        file_hash: str,
        *,
        actor_type: ActorType,
        actor_id: str | None,
        status: str = UNSET,
        num_transactions: int = UNSET,
        num_accounts: int = UNSET,
        validation: dict | None = UNSET,
        business_date: datetime | None = UNSET,
    ) -> IngestionLog:
        log = self.get(file_hash)
        if log is None:
            raise ValueError(f"ingestion_log {file_hash!r} does not exist")
        changes = collect_changes(
            status=status,
            num_transactions=num_transactions,
            num_accounts=num_accounts,
            validation=validation,
            business_date=business_date,
        )
        return self._update(
            log, changes, actor_type=actor_type, actor_id=actor_id, action="ingestion_log_updated"
        )

    def exists(self, file_hash: str) -> bool:
        return self.get(file_hash) is not None
