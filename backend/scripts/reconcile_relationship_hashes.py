"""
One-time HMAC reconciliation for `relationships.value_hash` (ROADMAP Phase
8). Mirrors `scripts/discover_relationships.py`'s CLI shape.

`investigation.relationship_discovery._value_hash` used to be an unsalted
`hashlib.sha256(value)` -- brute-forceable/rainbow-tableable for low-entropy
PII (e.g. a 10-character PAN) if the DB ever leaks. The fix keys it with
`Settings.pii_hmac_secret` (`foundation.hashing.hmac_sha256_hex`), but
`Relationship` rows are immutable-by-design (`RelationshipRepository` has
no `update`/`delete`), so an in-place migration of existing rows isn't
possible -- this script clears every existing row
(`RelationshipRepository.clear_all`, itself scoped solely to this
reconciliation use case) and reruns discovery under the new HMAC.
Acceptable data loss for pilot data (the relationships table holds derived,
re-discoverable signal, not source-of-truth evidence).

Destructive -- requires an explicit `--yes` flag before proceeding (same
"require explicit confirmation for a destructive op" judgment call this
repo doesn't yet have a single existing precedent script for, but matches
this task's own instruction to require one here regardless).

Usage (from `backend/`):

    python scripts/reconcile_relationship_hashes.py --yes
"""
from __future__ import annotations

import argparse
import logging
import sys

from db.enums import ActorType
from db.repositories.orchestration import RelationshipRepository
from db.session import SessionLocal
from foundation.config import get_settings
from investigation.relationship_discovery import discover_relationships, print_discovery_stats

logger = logging.getLogger(__name__)

_ACTOR_ID = "reconcile-relationship-hashes-cli"


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(
        description="One-time reconciliation of relationships.value_hash from the old "
        "unsalted sha256 scheme to the new HMAC (Settings.pii_hmac_secret)-keyed one: "
        "clears every existing relationships row and reruns discovery under the new "
        "hash. Destructive -- requires --yes."
    )
    parser.add_argument(
        "--yes", action="store_true",
        help="Required to actually run -- this clears every existing relationships row.",
    )
    args = parser.parse_args(argv)

    if not args.yes:
        print(
            "error: this clears every existing relationships row and reruns discovery "
            "-- pass --yes to confirm.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    settings = get_settings()
    if not settings.pii_hmac_secret:
        print(
            "error: PII_HMAC_SECRET is not set -- required to compute the new HMAC-keyed "
            "value_hash.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    session = SessionLocal()
    try:
        relationship_repo = RelationshipRepository(session)

        # `cleared` (clear_all()'s own return value) IS the before-count --
        # no separate full-table load needed just to take a len() of it
        # (code-review finding: this used to run
        # `len(relationship_repo.list(limit=10_000_000))` twice, a full
        # ORM-hydrating table load purely for a count that was already
        # available for free both times -- see `stats.relationships_created`
        # below for the after-count, since the table starts empty post-clear).
        cleared = relationship_repo.clear_all(actor_type=ActorType.SYSTEM, actor_id=_ACTOR_ID)
        session.commit()
        print(f"relationships before reconciliation: {cleared}")
        print(f"cleared {cleared} relationships row(s)")

        stats = discover_relationships(
            session,
            actor_type=ActorType.SYSTEM,
            actor_id=_ACTOR_ID,
            secret=settings.pii_hmac_secret,
        )
        session.commit()
        print(f"relationships after reconciliation:  {stats.relationships_created}")
    finally:
        session.close()

    print_discovery_stats(stats)


if __name__ == "__main__":
    main()
