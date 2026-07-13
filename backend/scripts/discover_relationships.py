"""
Relationship Explorer v1 discovery CLI (ROADMAP Phase 7). Mirrors `scripts/
train_detection_model.py`'s CLI shape: an explicit, one-time (rerunnable,
idempotent) invocation against the configured DB, never auto-triggered at
app boot or per-case-view -- see `investigation.relationship_discovery`'s
module docstring for why this is a global batch job, not lazy-fill.

Usage (from `backend/`):

    python scripts/discover_relationships.py
"""
from __future__ import annotations

import argparse
import logging
import sys

from db.enums import ActorType
from db.session import SessionLocal
from foundation.config import get_settings
from investigation.relationship_discovery import discover_relationships, print_discovery_stats

logger = logging.getLogger(__name__)

_ACTOR_ID = "discover-relationships-cli"


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(
        description="Run Relationship Explorer v1 discovery (shared PAN/fuzzy-name/"
        "income-bracket/branch-city) against the configured DB (foundation.config "
        "database_url) and persist any newly-found relationships rows."
    )
    parser.parse_args(argv)

    settings = get_settings()
    if not settings.pii_hmac_secret:
        # Code-review finding: without this check, an unset PII_HMAC_SECRET
        # crashed with an unhandled ValueError deep inside
        # foundation.hashing.hmac_sha256_hex instead of a clean error --
        # matches scripts/reconcile_relationship_hashes.py's identical guard.
        print(
            "error: PII_HMAC_SECRET is not set -- required to compute relationships."
            "value_hash.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    session = SessionLocal()
    try:
        stats = discover_relationships(
            session,
            actor_type=ActorType.SYSTEM,
            actor_id=_ACTOR_ID,
            secret=settings.pii_hmac_secret,
        )
        session.commit()
    finally:
        session.close()

    print_discovery_stats(stats)


if __name__ == "__main__":
    main()
