"""
Thin generic repository base — deliberately NOT a full generic CRUD facade.

Every repository in this package still defines its own typed, entity-
specific public methods (`create(...)`, `update(...)`, `list_by_x(...)`,
etc.) with real parameter names, matching this task's instruction not to
over-engineer a generic base beyond what's actually shared. What genuinely
is shared across all 21 tables, and so lives here, is:

  - fetch-by-primary-key (`get`) and a plain limit/offset listing (`list`),
  - the "add/mutate a row, then append the matching `audit_log` row in the
    same flush" plumbing (`_create`/`_update`) that implements the audit
    invariant from `docs/DATA_SCHEMA.md` §0 ("every write ... appends a row
    to audit_log ... Repositories enforce this, not callers") exactly once
    instead of once per repository.

`_UNSET` is the sentinel every repository's `update(...)` method uses for
"this field wasn't passed, leave it alone" — plain `None` can't mean that
here because several nullable columns (e.g. `cases.assigned_to`,
`accounts.customer_id`) need `None` to be a settable value (unassign a
case, clear a value) distinct from "don't touch this column".
"""
from __future__ import annotations

from typing import Any, ClassVar, Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.enums import ActorType
from db.repositories._audit import append_audit_log

ModelT = TypeVar("ModelT")

# Sentinel for "field not supplied, don't change it" in update() methods.
UNSET: Any = object()


def collect_changes(**kwargs: Any) -> dict[str, Any]:
    """Drop every `UNSET` keyword, keeping only fields the caller actually
    wants changed (including ones explicitly set to `None`)."""
    return {k: v for k, v in kwargs.items() if v is not UNSET}


class BaseRepository(Generic[ModelT]):
    model: ClassVar[Any]  # the mapped class; set by each subclass
    entity_type: ClassVar[str]  # audit_log.entity_type for this repo's rows
    pk_attr: ClassVar[str] = "id"  # name of the PK attribute on `model`

    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, pk: Any) -> ModelT | None:
        return self.session.get(self.model, pk)

    def list(self, *, limit: int = 100, offset: int = 0) -> list[ModelT]:
        stmt = select(self.model).limit(limit).offset(offset)
        return list(self.session.scalars(stmt))

    def _entity_id_of(self, obj: ModelT) -> str | None:
        value = getattr(obj, self.pk_attr)
        return None if value is None else str(value)

    def _create(
        self,
        obj: ModelT,
        *,
        actor_type: ActorType,
        actor_id: str | None,
        action: str,
        case_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> ModelT:
        """Add `obj`, flush (so PK/server-side defaults are populated), then
        append the matching audit_log row in the same Session before
        returning. Callers must still `session.commit()` — repositories flush,
        they never commit, so the caller controls the transaction boundary."""
        self.session.add(obj)
        self.session.flush()
        append_audit_log(
            self.session,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            entity_type=self.entity_type,
            entity_id=self._entity_id_of(obj),
            case_id=case_id,
            details=details,
        )
        return obj

    def _update(
        self,
        obj: ModelT,
        changes: dict[str, Any],
        *,
        actor_type: ActorType,
        actor_id: str | None,
        action: str,
        case_id: str | None = None,
    ) -> ModelT:
        """Apply `changes` (already filtered via `collect_changes`) to `obj`
        via setattr, flush, then append an audit_log row whose `details`
        captures a `{before, after}` snapshot of exactly the changed fields
        — auditable without duplicating the whole row into the log."""
        before = {field: getattr(obj, field) for field in changes}
        for field, value in changes.items():
            setattr(obj, field, value)
        self.session.flush()
        after = {field: getattr(obj, field) for field in changes}
        append_audit_log(
            self.session,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            entity_type=self.entity_type,
            entity_id=self._entity_id_of(obj),
            case_id=case_id,
            details={"before": before, "after": after},
        )
        return obj
