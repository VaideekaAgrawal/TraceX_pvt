"""
SQLAlchemy engine/session wiring, built off `foundation.config.get_settings()`
so the DB URL is never hardcoded here (SQLite for pilot/dev, Postgres DSN for
prod — `docs/DATA_SCHEMA.md` §0).

This module intentionally stops at "engine + session factory + FastAPI-style
dependency" — no repository layer and no API routes are wired here. Those are
separate follow-up tasks (repository layer, ingest path) per this task's
scope.
"""
from __future__ import annotations

from collections.abc import Generator
from typing import Any

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from foundation.config import get_settings


def _engine_kwargs(database_url: str) -> dict[str, Any]:
    """SQLite needs `check_same_thread=False` to be usable across the
    request-scoped sessions FastAPI's dependency injection creates (each
    request may run on a different thread from the one that opened the
    connection); Postgres needs no such override."""
    if database_url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    return {}


def build_engine(database_url: str | None = None) -> Engine:
    """Build a SQLAlchemy engine for `database_url` (defaults to
    `foundation.config.get_settings().database_url`). A factory function
    rather than only a module-level singleton so tests can build an engine
    against a throwaway SQLite file/`:memory:` DB without touching the
    real configured one.
    """
    url = database_url if database_url is not None else get_settings().database_url
    return create_engine(url, future=True, **_engine_kwargs(url))


# Module-level engine/sessionmaker for real app use (later phases' repository
# layer and, eventually, API routes import these) — built lazily from
# settings the first time this module is imported, not at import-of-nothing
# time, so it still respects env overrides made before import.
engine: Engine = build_engine()
SessionLocal: sessionmaker[Session] = sessionmaker(
    bind=engine, autoflush=False, autocommit=False, future=True
)


def get_db() -> Generator[Session, None, None]:
    """FastAPI-style dependency-injectable session generator:

        @router.get("/x")
        def handler(db: Session = Depends(get_db)): ...

    No routes exist yet (none are wired in this task's scope) — this is the
    seam later phases' `api/` routers plug into.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
