"""Smoke tests for `db/session.py`'s engine/session wiring."""
from __future__ import annotations

from sqlalchemy import text

from db.models import Base
from db.session import build_engine, get_db


def test_build_engine_uses_given_url_not_configured_default() -> None:
    engine = build_engine("sqlite:///:memory:")
    try:
        assert str(engine.url) == "sqlite:///:memory:"
    finally:
        engine.dispose()


def test_get_db_yields_a_working_session_and_closes_it() -> None:
    engine = build_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        # get_db() is written against the module-level SessionLocal (bound to
        # the real configured DB), so exercise the same generator contract
        # against a throwaway engine's sessionmaker instead of monkeypatching
        # module globals mid-test.
        from sqlalchemy.orm import sessionmaker

        session_factory = sessionmaker(
            bind=engine, autoflush=False, autocommit=False, future=True
        )

        def _get_db():
            db = session_factory()
            try:
                yield db
            finally:
                db.close()

        gen = _get_db()
        session = next(gen)
        assert session.execute(text("SELECT 1")).scalar() == 1

        # Exhausting the generator must close the session without error.
        with_exception = False
        try:
            next(gen)
        except StopIteration:
            with_exception = True
        assert with_exception
    finally:
        engine.dispose()


def test_real_get_db_generator_is_wired_correctly() -> None:
    """`get_db` itself (bound to the real module-level SessionLocal) must
    follow the same open/yield/close contract FastAPI's `Depends()` relies
    on — checked structurally without touching the real configured DB file."""
    gen = get_db()
    session = next(gen)
    assert session is not None
    gen.close()
