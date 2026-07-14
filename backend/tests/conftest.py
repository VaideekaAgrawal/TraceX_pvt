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
from foundation.config import Settings

# Every setting a developer's local `.env` (or exported shell env) could supply
# that would change what the suite actually exercises. `Settings` is a pydantic
# BaseSettings, so a bare `Settings(env="dev", jwt_secret="x")` in a fixture
# silently falls through to `.env` for everything it wasn't handed explicitly.
_DEVELOPER_ENV_VARS = (
    "ENV",
    "DATABASE_URL",
    "JWT_SECRET",
    "LLM_BASE_URL",
    "LLM_PROVIDER",
    "LLM_MODEL",
    "OPENROUTER_API_KEY",
    "PII_HMAC_KEY",
)


@pytest.fixture(autouse=True)
def isolate_settings_from_developer_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cut `Settings` off from `.env` and the ambient shell for the whole suite.

    ROADMAP Phase 8, and NOT a cosmetic isolation nicety — without it the suite
    is both wrong and expensive:

    - **It made real, billed LLM calls.** The "no API key configured" regression
      tests (`test_account_explanation_not_configured_is_never_cached`,
      `test_pattern_explanation_not_configured_fails_open_and_never_caches`)
      assert the not-configured path. They passed only because no `.env`
      existed. The moment a developer adds a real `OPENROUTER_API_KEY`, those
      fixtures' `Settings(env="dev", jwt_secret="test-secret")` picks it up,
      the "not configured" path stops being exercised at all, the tests hit
      OpenRouter for real, and they fail on the *second* call because the first
      one succeeded and cached.
    - **It made results machine-dependent.** A suite whose behavior changes
      based on whether the developer happens to have a `.env` is not a suite;
      CI (no `.env`) and local (a `.env`) would silently test different code.

    Tests that want a configured key must say so explicitly — pass
    `openrouter_api_key="test-key"` to `Settings(...)` — which is exactly what
    the tests exercising the success path already do."""
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for var in _DEVELOPER_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


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
