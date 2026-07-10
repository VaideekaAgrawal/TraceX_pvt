"""
Provisioning CLI to train + persist the ML ensemble (IsolationForest +
XGBoost) once against the configured DB's real data. Mirrors `scripts/
create_user.py`'s CLI shape (Phase 2): an explicit one-time invocation,
never auto-triggered at app boot -- the exact fix for the "ML model
retrains from scratch each boot" landmine (`archive/SALVAGE.md`,
`CLAUDE.md`).

Usage (from `backend/`):

    python scripts/train_detection_model.py [--model-name ensemble_v1]
"""
from __future__ import annotations

import argparse
import logging

from db.session import SessionLocal
from detection.data import accounts_touched_by, load_accounts_df, load_transactions_df
from detection.scoring.training import train_and_persist
from foundation.config import get_settings


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(
        description="Train the TraceX detection ensemble against the configured DB "
        "(foundation.config database_url) and persist the artifact + model_runs row."
    )
    parser.add_argument("--model-name", default="ensemble_v1")
    args = parser.parse_args(argv)

    session = SessionLocal()
    try:
        transactions_df = load_transactions_df(session)
        accounts_df = load_accounts_df(session, accounts_touched_by(transactions_df))
        print(f"loaded {len(accounts_df)} accounts, {len(transactions_df)} transactions")

        run = train_and_persist(
            session,
            accounts_df=accounts_df,
            transactions_df=transactions_df,
            model_artifact_dir=get_settings().model_artifact_dir,
            model_name=args.model_name,
            actor_id="train-detection-model-cli",
        )
        # Read every field the summary below needs *before* the session
        # closes -- `train_and_persist` commits internally, which expires
        # ORM attributes; reading them after `session.close()` (in the
        # `finally` block) raises `DetachedInstanceError` instead of
        # silently reloading (verified live during Phase 3 checkout).
        run_id, model_name, active = run.run_id, run.model_name, run.active
        artifact_path, metrics = run.artifact_path, run.metrics
    finally:
        session.close()

    print(f"trained model_run {run_id!r} (model_name={model_name!r}, active={active})")
    print(f"artifact_path={artifact_path}")
    print(f"metrics={metrics}")


if __name__ == "__main__":
    main()
