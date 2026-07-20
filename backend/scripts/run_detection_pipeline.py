"""
End-to-end detection -> alerts -> AI-ranked queue -> case-creation
orchestrator -- the CLI verification surface for ROADMAP Phase 4 (no HTTP
routes exist yet; mirrors `scripts/train_detection_model.py`'s CLI-script
precedent, Phase 3).

Stages:
  1. Score every account touched by the ingested transactions: the
     persisted, never-retrained-on-boot `FraudClassifier` loaded from the
     active `model_runs` row's artifact (`.predict()`, no retrain) + a
     freshly-fit `AnomalyDetector`. Only fitting IsolationForest fresh each
     run is archive-faithful, not a new landmine: IsolationForest's
     `contamination`-relative scoring is inherently population-relative,
     and the archive's own full pipeline (`archive/fund-flow-tracker/
     services/detection/service.py::run_full_pipeline`, STEP 2/6) refit it
     every run too -- "trained once, persisted, reused" applied only to the
     supervised XGBoost classifier there (and here).
  2. Seed the built-in Rule Engine rules if missing
     (`detection.rules.seed.seed_builtin_rules`, idempotent) and run every
     enabled rule (`RuleEngine.run_all`).
  3. Compute composite ensemble risk scores (`EnsembleScorer.compute_all`)
     and generate/refresh alerts (`investigation.alerts.
     generate_alerts_from_detection`).
  4. Rank the unassigned alert queue via the RL bandit
     (`investigation.prioritization.rank_alert_queue`) and auto-create +
     auto-assign cases for the top N of the ranked queue
     (`investigation.cases.create_case_from_alert`, which itself calls
     `investigation.assignment.auto_assign`).

Usage (from `backend/`):

    python scripts/run_detection_pipeline.py [--model-name ensemble_v1] \\
        [--top-n-to-case 20]
"""
from __future__ import annotations

import argparse
import logging

from db.enums import ActorType
from db.repositories.detection import AlertRepository, ModelRunRepository
from db.session import SessionLocal
from detection.data import accounts_touched_by, load_accounts_df, load_transactions_df
from detection.features import FeatureExtractor
from detection.graph.networkx_store import NetworkXGraphStore
from detection.rules.engine import RuleEngine
from detection.rules.seed import seed_builtin_rules
from detection.scoring.ensemble import AnomalyDetector, EnsembleScorer
from detection.scoring.training import load_active_model
from investigation.alerts import generate_alerts_from_detection
from investigation.assignment import compute_workload
from investigation.cases import create_case_from_alert
from investigation.network_risk import compute_network_risk
from investigation.prioritization import rank_alert_queue

logger = logging.getLogger(__name__)

_ACTOR_ID = "run-detection-pipeline-cli"


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(
        description="Run detection -> alerts -> AI-ranked queue -> case creation "
        "against the configured DB (foundation.config database_url)."
    )
    parser.add_argument("--model-name", default="ensemble_v1")
    parser.add_argument(
        "--top-n-to-case", type=int, default=20,
        help="How many of the ranked unassigned-alert queue to auto-case-create.",
    )
    args = parser.parse_args(argv)

    session = SessionLocal()
    try:
        model_repo = ModelRunRepository(session)
        active_run = model_repo.get_active_for_model(args.model_name)
        if active_run is None:
            raise RuntimeError(
                f"no active model_run for model_name={args.model_name!r} -- "
                "run scripts/train_detection_model.py first"
            )
        bundle = load_active_model(active_run)
        fraud_classifier = bundle["fraud_classifier"]

        transactions_df = load_transactions_df(session)
        accounts_df = load_accounts_df(session, accounts_touched_by(transactions_df))
        print(f"loaded {len(accounts_df)} accounts, {len(transactions_df)} transactions")

        graph_store = NetworkXGraphStore(accounts_df, transactions_df)
        features_df = FeatureExtractor(graph_store, accounts_df, transactions_df).extract_all()

        anomaly_results = AnomalyDetector().fit_predict(features_df)
        fraud_results = fraud_classifier.predict(features_df)

        seeded = seed_builtin_rules(session, actor_type=ActorType.SYSTEM, actor_id=_ACTOR_ID)
        session.commit()
        print(f"seeded {len(seeded)} new builtin rule(s) (idempotent)")

        rule_results = RuleEngine(session).run_all(graph_store, accounts_df, transactions_df)
        total_detections = sum(len(v) for v in rule_results.values())
        print(f"rule engine: {total_detections} detection(s) across {len(rule_results)} type(s)")

        ensemble_scores = EnsembleScorer().compute_all(
            features_df, anomaly_results, fraud_results, rule_results, graph_store
        )

        alerts = generate_alerts_from_detection(
            session,
            ensemble_scores,
            rule_results,
            active_run.run_id,
            actor_type=ActorType.SYSTEM,
            actor_id=_ACTOR_ID,
        )
        session.commit()
        print(f"generated/refreshed {len(alerts)} alert(s)")

        alert_repo = AlertRepository(session)
        unassigned = alert_repo.list_unassigned(limit=1000)
        ranked = rank_alert_queue(session, unassigned)
        print(f"ranked queue: {len(ranked)} unassigned alert(s)")

        # Computed once and maintained in Python across the loop below
        # (`auto_assign`'s `workload` param, forwarded via
        # `create_case_from_alert`) instead of re-running the full
        # investigator-workload aggregate query once per case (code-review
        # finding, Phase 4: confirmed redundant -- the same query re-ran
        # `top_n_to_case` times in one real pipeline run when only the
        # just-assigned investigator's count changed between iterations).
        workload = compute_workload(session)

        # One case per flagged account. An account can trip several alerts (a
        # layering chain and a profile mismatch, or overlapping sub-chains); making
        # a separate case for each means an investigator sees the same entity five
        # times over. Case the highest-ranked alert per account and stop there —
        # the rest stay as open alerts on the dashboard, linkable later.
        created_cases: list[tuple[str, str | None, object]] = []
        cased_accounts: set[str] = set()
        for alert in ranked:
            if len(created_cases) >= args.top_n_to_case:
                break
            if alert.primary_account_id in cased_accounts:
                continue
            cased_accounts.add(alert.primary_account_id)
            alert_repo.mark_opened(alert.alert_id, actor_type=ActorType.SYSTEM, actor_id=_ACTOR_ID)
            case = create_case_from_alert(
                session, alert, actor_type=ActorType.SYSTEM, actor_id=_ACTOR_ID,
                workload=workload,
            )
            created_cases.append((case.case_id, case.assigned_to, case.sla_due_at))
        session.commit()
        print(f"created {len(created_cases)} case(s) from the top of the ranked queue")

        # Compute the network-risk score for every created case up front, rather
        # than lazily on first view. A case that opens with a blank network-risk
        # panel reads as "the feature is broken" — and for a multi-account case
        # (mule ring, layering chain, cycle) the score is one of the most telling
        # signals an investigator has. Cheap: each case's linked-account set is
        # small. Single-account cases correctly score low (no network to score).
        for case_id, _assigned_to, _sla in created_cases:
            compute_network_risk(
                session, case_id, actor_type=ActorType.SYSTEM, actor_id=_ACTOR_ID
            )
        session.commit()
        print(f"computed network-risk score for {len(created_cases)} case(s)")

        for case_id, assigned_to, sla_due_at in created_cases:
            print(f"  {case_id} -> assigned_to={assigned_to} sla_due_at={sla_due_at}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
