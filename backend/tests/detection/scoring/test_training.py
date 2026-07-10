from __future__ import annotations

from pathlib import Path

import joblib
import pytest

from db.models.detection import ModelRun
from db.repositories.detection import ModelRunRepository
from detection.scoring.ensemble import AnomalyDetector, FraudClassifier
from detection.scoring.training import load_active_model, train_and_persist


def _get(repo: ModelRunRepository, run_id: str) -> ModelRun:
    run = repo.get(run_id)
    assert run is not None
    return run


def test_train_and_persist_creates_active_run_with_artifact(
    session, tmp_path: Path, synthetic_dataset
) -> None:
    accounts_df, transactions_df = synthetic_dataset
    run = train_and_persist(
        session,
        accounts_df=accounts_df,
        transactions_df=transactions_df,
        model_artifact_dir=tmp_path,
        model_name="ensemble_v1",
    )

    assert run.active is True
    assert run.model_name == "ensemble_v1"
    assert run.model_type == "ensemble"
    assert run.artifact_path is not None
    assert Path(run.artifact_path).exists()
    assert "auc_roc" in run.metrics
    assert "anomaly_count" in run.metrics
    assert run.feature_importance

    # Artifact round-trip: the serialized objects load back as the right types.
    loaded = joblib.load(run.artifact_path)
    assert isinstance(loaded["anomaly_detector"], AnomalyDetector)
    assert isinstance(loaded["fraud_classifier"], FraudClassifier)
    assert loaded["fraud_classifier"]._fitted is True


def test_train_and_persist_promote_invariant_across_two_runs(
    session, tmp_path: Path, synthetic_dataset
) -> None:
    accounts_df, transactions_df = synthetic_dataset
    repo = ModelRunRepository(session)

    run1 = train_and_persist(
        session,
        accounts_df=accounts_df,
        transactions_df=transactions_df,
        model_artifact_dir=tmp_path,
        model_name="ensemble_v1",
    )
    assert _get(repo, run1.run_id).active is True

    run2 = train_and_persist(
        session,
        accounts_df=accounts_df,
        transactions_df=transactions_df,
        model_artifact_dir=tmp_path,
        model_name="ensemble_v1",
    )

    # Exactly one active row for this model_name after the second run.
    active_runs = [r for r in repo.list_active() if r.model_name == "ensemble_v1"]
    assert len(active_runs) == 1
    assert active_runs[0].run_id == run2.run_id
    assert _get(repo, run1.run_id).active is False
    assert run1.run_id != run2.run_id


def test_train_and_persist_different_model_names_dont_interfere(
    session, tmp_path: Path, synthetic_dataset
) -> None:
    accounts_df, transactions_df = synthetic_dataset
    repo = ModelRunRepository(session)

    run_a = train_and_persist(
        session, accounts_df=accounts_df, transactions_df=transactions_df,
        model_artifact_dir=tmp_path, model_name="ensemble_v1",
    )
    run_b = train_and_persist(
        session, accounts_df=accounts_df, transactions_df=transactions_df,
        model_artifact_dir=tmp_path, model_name="ensemble_v2",
    )

    assert _get(repo, run_a.run_id).active is True
    assert _get(repo, run_b.run_id).active is True


def test_train_and_persist_dataset_hash_is_deterministic(
    session, tmp_path: Path, synthetic_dataset
) -> None:
    accounts_df, transactions_df = synthetic_dataset
    run1 = train_and_persist(
        session, accounts_df=accounts_df, transactions_df=transactions_df,
        model_artifact_dir=tmp_path / "r1", model_name="det1",
    )
    run2 = train_and_persist(
        session, accounts_df=accounts_df, transactions_df=transactions_df,
        model_artifact_dir=tmp_path / "r2", model_name="det2",
    )
    assert run1.dataset_hash == run2.dataset_hash


@pytest.mark.parametrize("model_name", ["m1"])
def test_train_and_persist_artifact_dir_is_created(
    session, tmp_path: Path, synthetic_dataset, model_name: str
) -> None:
    accounts_df, transactions_df = synthetic_dataset
    nested = tmp_path / "nested" / "artifacts"
    assert not nested.exists()
    train_and_persist(
        session, accounts_df=accounts_df, transactions_df=transactions_df,
        model_artifact_dir=nested, model_name=model_name,
    )
    assert nested.exists()


def test_load_active_model_returns_same_bundle_as_train_and_persist(
    session, tmp_path: Path, synthetic_dataset
) -> None:
    accounts_df, transactions_df = synthetic_dataset
    run = train_and_persist(
        session, accounts_df=accounts_df, transactions_df=transactions_df,
        model_artifact_dir=tmp_path, model_name="ensemble_v1",
    )

    bundle = load_active_model(run)
    assert isinstance(bundle["anomaly_detector"], AnomalyDetector)
    assert isinstance(bundle["fraud_classifier"], FraudClassifier)
    assert bundle["fraud_classifier"]._fitted is True
    assert bundle["feature_names"]


def test_load_active_model_raises_without_artifact_path() -> None:
    from db.models.base import utcnow

    run = ModelRun(
        run_id="RUN-NO-ARTIFACT",
        model_name="ensemble_v1",
        model_type="ensemble",
        version="0.1.0",
        trained_at=utcnow(),
        metrics={},
        artifact_path=None,
        active=False,
    )
    with pytest.raises(ValueError, match="no artifact_path"):
        load_active_model(run)
