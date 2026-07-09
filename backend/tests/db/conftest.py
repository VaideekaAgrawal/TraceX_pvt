"""
Shared fixtures for `tests/db/` — in particular the repository tests under
`test_repositories_*.py`, which all need a throwaway SQLite schema. Mirrors
the local `session` fixture already used ad hoc in `test_models.py`
(kept local there rather than refactored to import from here, since this
file is new and that one predates it — no behavior change to existing
tests).
"""
from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session

from db.models import Base
from db.session import build_engine


@pytest.fixture()
def session() -> Iterator[Session]:
    engine = build_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as s:
            yield s
    finally:
        # SQLite in-memory engines keep their pooled connection open until
        # disposed; without this every test using this fixture leaks a
        # sqlite3 connection (visible as a ResourceWarning at GC time).
        engine.dispose()
