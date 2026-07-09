"""
Shared declarative base, timestamp mixins, and type helpers for every ORM
model under `db/models/`. Keeping one `Base` (and therefore one `MetaData`)
across all model modules is what lets Alembic's `env.py` autogenerate against
the full schema and what lets `Base.metadata.create_all()` build every table
in one call (see `db/models/__init__.py`).

Logical->physical type mapping follows `docs/DATA_SCHEMA.md` §0 exactly:
  TEXT  -> sqlalchemy.Text        (SQLite TEXT / Postgres TEXT)
  INT   -> sqlalchemy.Integer     (SQLite INTEGER / Postgres INTEGER-BIGINT)
  MONEY -> sqlalchemy.Numeric(18, 2)  (never Float — currency)
  REAL  -> sqlalchemy.Float       (scores/ratios only)
  BOOL  -> sqlalchemy.Boolean     (SQLite INTEGER 0/1 / Postgres BOOLEAN)
  TS    -> sqlalchemy.DateTime(timezone=True)
  JSON  -> sqlalchemy.JSON (portable — SQLite TEXT-encoded / Postgres JSON).
           Deliberately the generic portable type, not a Postgres-only JSONB
           import, per this task's explicit constraint not to hardcode a
           SQLite-only type where Postgres has a native equivalent while also
           not tying the model layer to one backend's variant type.
  ENUM  -> sqlalchemy.Enum(SomeEnum) (SQLite: VARCHAR + CHECK constraint;
           Postgres: native ENUM type) — exactly the §0 mapping.
"""
from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum as PyEnum
from typing import TypeVar

from sqlalchemy import DateTime
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

_E = TypeVar("_E", bound=PyEnum)


def utcnow() -> datetime:
    """Timezone-aware UTC now, used as the Python-side default for every
    created_at/updated_at column (doc §0: "All UTC")."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Declarative base every ORM model inherits from."""


def sa_enum(enum_cls: type[_E], *, name: str | None = None) -> SAEnum:
    """Build the SQLAlchemy column type for a `docs/DATA_SCHEMA.md` §2 enum.

    `name` becomes the Postgres native ENUM type name; defaults to the
    lower-cased Python class name (SQLAlchemy's own default) which is stable
    and collision-free across the modules in this package.
    """
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=True,
        validate_strings=True,
    )


class CreatedAtMixin:
    """Every table has `created_at` (doc §0)."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class UpdatedAtMixin:
    """Mutable tables also have `updated_at` (doc §0)."""

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
