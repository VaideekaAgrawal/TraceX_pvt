"""
Root-level shared fixtures — pytest auto-discovers this without an import.
Promoted from `tests/db/conftest.py` (Phase 2) once a second test subtree
(`tests/foundation/`, `tests/api/`) needed the same throwaway-SQLite
`session` fixture; `tests/db/test_repositories_*.py` keep using it unchanged
via auto-discovery. `tests/db/test_models.py` has its own separate local
fixture and is untouched (predates this file, no behavior change intended).
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
