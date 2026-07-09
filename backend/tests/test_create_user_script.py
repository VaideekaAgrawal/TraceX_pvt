"""
Light test for `scripts/create_user.py` — calls the internal `create_user`
function directly against the shared throwaway `session` fixture (see
`tests/conftest.py`), not through argparse/CLI plumbing.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

# `scripts/` is not an installed package (deliberately excluded from
# `[tool.setuptools.packages.find]` — it's a standalone CLI, not part of the
# app), so it isn't importable via the editable install; add it to
# `sys.path` directly for this test module only.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from create_user import create_user  # noqa: E402

from db.enums import UserRole
from db.repositories.platform import UserRepository
from foundation.security import verify_password


def test_create_user_persists_hashed_password(session: Session) -> None:
    user_id = create_user(
        session,
        username="jdoe",
        email="jdoe@example.com",
        password="correct-horse",
        full_name="Jane Doe",
        role=UserRole.INVESTIGATOR,
    )

    user = UserRepository(session).get(user_id)
    assert user is not None
    assert user.username == "jdoe"
    assert user.password_hash != "correct-horse"
    assert verify_password("correct-horse", user.password_hash) is True


def test_create_user_refuses_duplicate_username(session: Session) -> None:
    create_user(
        session,
        username="jdoe",
        email="jdoe@example.com",
        password="correct-horse",
        full_name="Jane Doe",
        role=UserRole.INVESTIGATOR,
    )
    with pytest.raises(ValueError, match="already exists"):
        create_user(
            session,
            username="jdoe",
            email="other@example.com",
            password="different",
            full_name="Someone Else",
            role=UserRole.ADMIN_COMPLIANCE,
        )


def test_create_user_refuses_duplicate_user_id(session: Session) -> None:
    user_id = create_user(
        session,
        username="jdoe",
        email="jdoe@example.com",
        password="correct-horse",
        full_name="Jane Doe",
        role=UserRole.INVESTIGATOR,
    )

    with pytest.raises(ValueError, match="already exists"):
        create_user(
            session,
            username="someoneelse",
            email="other@example.com",
            password="different",
            full_name="Someone Else",
            role=UserRole.ADMIN_COMPLIANCE,
            user_id=user_id,
        )
