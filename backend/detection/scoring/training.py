"""
`train_and_persist()` — the orchestration ROADMAP Phase 3 exists to add:
train the ML ensemble once against real data and persist the resulting
artifact, instead of the archive's "retrains from scratch every pipeline
run" landmine (`archive/SALVAGE.md`).

Owns the "exactly one active `model_run` per `model_name`" invariant as a
promote step on top of `ModelRunRepository`'s plain CRUD — the repository's
own docstring says this is deliberately not enforced at that layer.

`load_active_model()` is the load-side counterpart to `train_and_persist`'s
save side (code-review finding, Phase 4: `scripts/run_detection_pipeline.py`
was inlining `joblib.load(...)` + unpacking the bundle dict directly,
duplicating knowledge of the artifact's shape that only this module should
own) -- both functions agree on the joblib bundle's key names in exactly one
place now.
"""
from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any

import joblib
import pandas as pd
from sqlalchemy.orm import Session

from db.enums import ActorType
from db.models.base import utcnow
from db.models.detection import ModelRun
from db.repositories.detection import ModelRunRepository
from detection.config import DEFAULT_DETECTION_CONFIG, DetectionConfig
from detection.features import FeatureExtractor
from detection.graph.networkx_store import NetworkXGraphStore
from detection.scoring.ensemble import AnomalyDetector, FraudClassifier


def _build_labels(transactions_df: pd.DataFrame, features_df: pd.DataFrame) -> pd.Series:
    """Build fraud labels from `is_laundering` -- no circular training.

    Source-only labeling: only the initiating account of a laundering
    transaction is labeled positive. Including destination accounts adds
    label noise (many are innocent recipients) and was shown in the
    archive's own tuning experiment to drop precision from 77.8% to 4.9%
    (`DetectionConfig.xgb_label_mode = "source_only"`, descriptive-only --
    this is the one and only labeling path, ported unchanged from
    `archive/fund-flow-tracker/services/detection/service.py::
    DetectionService._build_labels`)."""
    if "is_laundering" not in transactions_df.columns or transactions_df.empty:
        return pd.Series(0, index=features_df.index)

    fraud_txns = transactions_df[transactions_df["is_laundering"] == 1]
    if len(fraud_txns) == 0:
        return pd.Series(0, index=features_df.index)

    fraud_accs = set(fraud_txns["source_account"].unique())
    return pd.Series(
        [1 if acc in fraud_accs else 0 for acc in features_df.index],
        index=features_df.index,
    )


def _dataset_hash(accounts_df: pd.DataFrame, transactions_df: pd.DataFrame) -> str:
    """Cheap, deterministic training-set provenance fingerprint -- not a
    cryptographic guarantee, just enough to tell two training runs apart
    (`model_runs.dataset_hash`, doc §3.2)."""
    digest = hashlib.sha256()
    digest.update(str(len(accounts_df)).encode())
    digest.update(str(len(transactions_df)).encode())
    if "txn_id" in transactions_df.columns and not transactions_df.empty:
        ids = "|".join(sorted(transactions_df["txn_id"].astype(str)))
        digest.update(ids.encode())
    return digest.hexdigest()


def train_and_persist(
    session: Session,
    *,
    accounts_df: pd.DataFrame,
    transactions_df: pd.DataFrame,
    model_artifact_dir: Path,
    model_name: str = "ensemble_v1",
    config: DetectionConfig | None = None,
    actor_type: ActorType = ActorType.SYSTEM,
    actor_id: str | None = None,
) -> ModelRun:
    """Train `AnomalyDetector` + `FraudClassifier` once, serialize both
    (joblib) under `model_artifact_dir`, and -- only once serialization has
    actually succeeded -- create the new `model_runs` row and promote it to
    `active=True`, flipping any prior active row(s) for the same
    `model_name` to `active=False` (the invariant `ModelRunRepository`
    itself deliberately doesn't enforce)."""
    cfg = config or DEFAULT_DETECTION_CONFIG

    graph_store = NetworkXGraphStore(accounts_df, transactions_df)
    features_df = FeatureExtractor(graph_store, accounts_df, transactions_df).extract_all()

    anomaly_detector = AnomalyDetector(cfg)
    anomaly_results = anomaly_detector.fit_predict(features_df)
    n_anomalies = int(anomaly_results["is_anomaly"].sum()) if not anomaly_results.empty else 0

    labels = _build_labels(transactions_df, features_df)
    fraud_classifier = FraudClassifier(cfg)
    fraud_metrics = fraud_classifier.train(features_df, labels, transactions_df)

    run_id = f"RUN-{uuid.uuid4().hex[:16].upper()}"
    model_artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = model_artifact_dir / f"{run_id}.joblib"

    # Serialize first -- a failure here must not leave a model_runs row
    # pointing at a nonexistent artifact.
    joblib.dump(
        {
            "anomaly_detector": anomaly_detector,
            "fraud_classifier": fraud_classifier,
            "feature_names": list(features_df.columns),
            "trained_at": utcnow().isoformat(),
        },
        artifact_path,
    )

    metrics = {
        "anomaly_count": n_anomalies,
        "anomaly_rate": n_anomalies / max(len(anomaly_results), 1),
        **fraud_metrics,
    }

    # A single commit at the end, after create + demote + promote, all of
    # which only flush internally (`BaseRepository._create`/`_update`) --
    # the artifact-serialization-succeeded guarantee is already established
    # above (joblib.dump before any DB write), so splitting this into two
    # commits protected nothing while opening a crash window: if the
    # process died between two separate commits, the new run could be left
    # permanently active=False with no recovery path anywhere in the
    # codebase. One commit means either the whole promote (create + demote
    # + activate) lands atomically, or none of it does.
    repo = ModelRunRepository(session)
    run = repo.create(
        run_id=run_id,
        model_name=model_name,
        model_type="ensemble",
        version=utcnow().strftime("%Y%m%d%H%M%S"),
        trained_at=utcnow(),
        dataset_hash=_dataset_hash(accounts_df, transactions_df),
        metrics=metrics,
        feature_importance=fraud_classifier.get_feature_importance(),
        artifact_path=str(artifact_path),
        active=False,
        actor_type=actor_type,
        actor_id=actor_id,
    )

    # Promote: demote any prior active run(s) for this model_name (defends
    # against more than one somehow already being active, not just the
    # expected single row `get_active_for_model` would return), then
    # activate the new one. Separate updates (not a single "swap") so the
    # audit_log records the demotion(s) and the promotion as distinct,
    # attributable events.
    prior_active_runs = [r for r in repo.list_active() if r.model_name == model_name]
    for prior in prior_active_runs:
        if prior.run_id != run.run_id:
            repo.update(prior.run_id, active=False, actor_type=actor_type, actor_id=actor_id)
    run = repo.update(run.run_id, active=True, actor_type=actor_type, actor_id=actor_id)
    session.commit()

    return run


def load_active_model(model_run: ModelRun) -> dict[str, Any]:
    """Load the joblib artifact `train_and_persist` wrote for `model_run`.
    Returns the full bundle dict (`anomaly_detector`, `fraud_classifier`,
    `feature_names`, `trained_at`) exactly as `train_and_persist` wrote it —
    callers pick the keys they need (e.g. `scripts/run_detection_pipeline.py`
    only needs `fraud_classifier`, to score without retraining)."""
    if model_run.artifact_path is None:
        raise ValueError(f"model_run {model_run.run_id!r} has no artifact_path")
    return joblib.load(model_run.artifact_path)
