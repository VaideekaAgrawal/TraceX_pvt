"""
CLI wrapper for the Demo & Training Data Studio (ROADMAP Phase 1B) --
mirrors `scripts/create_user.py`/`db/ingest.py`'s CLI-script precedent:
`argparse`, `logging.basicConfig` first, `SessionLocal()`/try-finally,
explicit `session.commit()` (the underlying repositories only flush),
`print()` a user-facing summary, non-zero exit on failure
(`create_user.py`'s `except ValueError -> SystemExit(1)` precedent).

Usage (from `backend/`):

    python scripts/generate_demo_data.py [--actor-id demo-data-studio-cli]

Safe to run repeatedly -- every sub-generator is gated by its own
`ingestion_log` marker (see `demo_data/seed.py`), so a second run is a true
no-op.
"""
from __future__ import annotations

import argparse
import logging
import sys

from db.enums import ActorType
from db.session import SessionLocal
from demo_data.seed import run_demo_data_studio

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(
        description="Seed the TraceX demo/training dataset (KYC mock, relationship "
        "networks, historical case corpus, golden edge-case scenarios) against the "
        "configured DB (foundation.config database_url). Strictly separate from the "
        "real ingest path (db/ingest.py) -- every row this writes is DEMO-prefixed."
    )
    parser.add_argument("--actor-id", default="demo-data-studio-cli")
    args = parser.parse_args(argv)

    session = SessionLocal()
    try:
        summary = run_demo_data_studio(
            session, actor_type=ActorType.SYSTEM, actor_id=args.actor_id
        )
        session.commit()
    except ValueError as exc:
        session.rollback()
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    finally:
        session.close()

    print(f"kyc customers created:        {summary.kyc_customers_created}")
    print(f"relationship clusters created: {summary.relationship_clusters_created}")
    print(f"relationships discovered:      {summary.relationships_discovered}")
    print(f"historical cases created:      {summary.historical_cases_created}")
    print(f"golden scenarios created:      {summary.golden_scenarios_created}")
    if summary.already_seeded:
        print(f"already seeded (skipped):      {', '.join(summary.already_seeded)}")


if __name__ == "__main__":
    main()
