"""
Create-only CLI to provision a `users` row. No user-management API exists in
this phase (out of the Phase 2 checklist) — this is how the first
Admin/Compliance and Investigator accounts get created, and how ops adds
accounts later, until such an API lands.

Usage (from `backend/`):

    python scripts/create_user.py --username jdoe --email jdoe@bank.example \\
        --password 'change-me' --full-name "Jane Doe" --role INVESTIGATOR
"""
from __future__ import annotations

import argparse
import sys
import uuid

from sqlalchemy.orm import Session

from db.enums import ActorType, UserRole
from db.repositories.platform import UserRepository
from db.session import SessionLocal
from foundation.security import hash_password


def create_user(
    db: Session,
    *,
    username: str,
    email: str,
    password: str,
    full_name: str,
    role: UserRole,
    user_id: str | None = None,
) -> str:
    """Create-only: raises `ValueError` if `username` already exists, or if
    an explicitly-passed `user_id` collides with an existing user (checked
    the same way as `username` — code review, Phase 2: an unchecked
    `--user-id` collision used to fall through to `repo.create()` and raise
    a raw, unhandled IntegrityError on flush instead of this same clean
    error). Returns the created `user_id`. Split out from `main()` so tests
    can call it directly against a throwaway session (see
    `tests/test_create_user_script.py`) without going through argparse/CLI
    plumbing."""
    repo = UserRepository(db)
    if repo.get_by_username(username) is not None:
        raise ValueError(f"username {username!r} already exists")
    if user_id is not None and repo.get(user_id) is not None:
        raise ValueError(f"user_id {user_id!r} already exists")

    resolved_user_id = user_id if user_id is not None else str(uuid.uuid4())
    user = repo.create(
        user_id=resolved_user_id,
        username=username,
        email=email,
        password_hash=hash_password(password),
        role=role,
        full_name=full_name,
        actor_type=ActorType.SYSTEM,
        actor_id=None,
    )
    db.commit()
    return user.user_id


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Create a TraceX user (create-only).")
    parser.add_argument("--username", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--full-name", required=True, dest="full_name")
    parser.add_argument("--role", required=True, choices=[r.value for r in UserRole])
    parser.add_argument("--user-id", default=None, dest="user_id")
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        user_id = create_user(
            db,
            username=args.username,
            email=args.email,
            password=args.password,
            full_name=args.full_name,
            role=UserRole(args.role),
            user_id=args.user_id,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    finally:
        db.close()

    print(f"created user {user_id!r} (username={args.username!r}, role={args.role})")


if __name__ == "__main__":
    main()
