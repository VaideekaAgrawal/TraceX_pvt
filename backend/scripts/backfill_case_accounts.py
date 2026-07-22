"""
One-time (rerunnable, idempotent) backfill: link every case's own
`primary_account_id` into `case_accounts` if it isn't already scoped there.

Found live (2026-07-22, post-Phase-22): all 50 `DEMO-CASE-*` rows in the
committed demo DB have zero `case_accounts` rows and zero linked alerts --
they were seeded purely as similarity/typology/outcome metadata for the
Similar Historical Cases panel (`investigation/similar_cases.py`), never
run through `investigation.cases.create_case_from_alert` (the only place
that normally populates `case_accounts`, from the triggering alert's
`account_ids`). That's fine for their original purpose, but Session 30's
"open a referenced case as a real tab" feature (`useOpenCaseTab`,
`require_case_read_access`) assumes any `case_id` is fully openable --
every account-scoped L1/L2 detail route (customer snapshot, money flow,
etc.) 404s with "Account not in this case's scope" for these cases as a
result, since `_load_scoped_account` (`foundation/auth.py`) checks against
an empty scope set.

This script closes that gap for the *primary* account only (hop_distance=0,
matching `create_case_from_alert`'s own convention) -- it does NOT
fabricate a fuller hop-1 network the way a real alert-triggered case would
have, since there's no real alert/pattern data backing these demo rows to
derive one from honestly. A demo case fixed by this script will show real
L1 detail for its own primary account but won't have extra linked accounts
in its Investigation Graph -- an honest reflection of what data actually
exists, not a gap papered over.

Usage (from `backend/`):

    python scripts/backfill_case_accounts.py [--dry-run]
"""
from __future__ import annotations

import argparse
import logging

from sqlalchemy import select

from db.enums import ActorType
from db.models.investigation import Case
from db.repositories.investigation import CaseAccountRepository
from db.session import SessionLocal

logger = logging.getLogger(__name__)

_ACTOR_ID = "backfill-case-accounts-cli"


def backfill_case_accounts(session, *, dry_run: bool = False) -> int:
    case_account_repo = CaseAccountRepository(session)

    # Direct query, not `CaseRepository.list()` -- that method defaults to
    # `limit=100`, and this backfill needs every case, not just a page.
    all_cases = session.scalars(select(Case)).all()

    fixed = 0
    for case in all_cases:
        if case.primary_account_id is None:
            continue
        scoped_ids = case_account_repo.list_account_ids_for_case(case.case_id)
        if case.primary_account_id in scoped_ids:
            continue
        fixed += 1
        logger.info(
            "case %s: primary account %s missing from case_accounts%s",
            case.case_id,
            case.primary_account_id,
            " (dry run, not writing)" if dry_run else "",
        )
        if not dry_run:
            case_account_repo.add_account(
                case_id=case.case_id,
                account_id=case.primary_account_id,
                hop_distance=0,
                actor_type=ActorType.SYSTEM,
                actor_id=_ACTOR_ID,
            )
    if not dry_run:
        session.commit()
    return fixed


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(
        description="Backfill case_accounts with each case's own primary_account_id "
        "for any case missing it (see this file's module docstring)."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Log what would change without writing."
    )
    args = parser.parse_args(argv)

    session = SessionLocal()
    try:
        fixed = backfill_case_accounts(session, dry_run=args.dry_run)
        logger.info("Done: %d case(s) %s.", fixed, "would be fixed" if args.dry_run else "fixed")
    finally:
        session.close()


if __name__ == "__main__":
    main()
