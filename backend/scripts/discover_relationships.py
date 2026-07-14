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

from db.enums import ActorType
from db.session import SessionLocal
from foundation.config import get_settings
from investigation.relationship_discovery import discover_relationships

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

    session = SessionLocal()
    try:
        stats = discover_relationships(
            session,
            actor_type=ActorType.SYSTEM,
            actor_id=_ACTOR_ID,
            hmac_key=get_settings().pii_hmac_key,
        )
        session.commit()
    finally:
        session.close()

    print(f"candidate_pool_size={stats.candidate_pool_size}")
    print(f"pairs_compared={stats.pairs_compared}")
    print(f"relationships_created={stats.relationships_created}")
    print(f"relationships_skipped_existing={stats.relationships_skipped_existing}")


if __name__ == "__main__":
    main()
