from __future__ import annotations

import pandas as pd

from detection.detectors.round_trip import RoundTripDetector
from detection.features import FeatureExtractor
from detection.graph.networkx_store import NetworkXGraphStore
from detection.scoring.ensemble import (
    AnomalyDetector,
    EnsembleScorer,
    FraudClassifier,
    RoleClassifier,
)


def test_anomaly_detector_fit_predict_shape(synthetic_dataset) -> None:
    accounts_df, transactions_df = synthetic_dataset
    store = NetworkXGraphStore(accounts_df, transactions_df)
    features_df = FeatureExtractor(store, accounts_df, transactions_df).extract_all()

    result = AnomalyDetector().fit_predict(features_df)
    assert set(result.columns) == {"account_id", "anomaly_score", "is_anomaly"}
    assert len(result) == len(features_df)
    assert result["anomaly_score"].between(0, 100).all()
    assert set(result["is_anomaly"].unique()) <= {0, 1}


def test_fraud_classifier_train_on_separable_data_learns_something(synthetic_dataset) -> None:
    accounts_df, transactions_df = synthetic_dataset
    store = NetworkXGraphStore(accounts_df, transactions_df)
    features_df = FeatureExtractor(store, accounts_df, transactions_df).extract_all()

    from detection.scoring.training import _build_labels

    labels = _build_labels(transactions_df, features_df)
    clf = FraudClassifier()
    metrics = clf.train(features_df, labels, transactions_df)

    assert metrics["train_size"] > 0
    assert metrics["auc_roc"] > 0.5  # meaningfully better than a coin flip
    assert 0.0 <= metrics["precision"] <= 1.0
    assert 0.0 <= metrics["recall"] <= 1.0

    predictions = clf.predict(features_df)
    assert set(predictions.columns) == {"account_id", "fraud_prob", "fraud_pred"}
    assert predictions["fraud_prob"].between(0, 1).all()

    importances = clf.get_feature_importance()
    assert set(importances.keys()) == set(FeatureExtractor._FEATURE_COLS)


def test_fraud_classifier_predict_before_train_returns_zeros() -> None:
    features_df = pd.DataFrame(
        {"f1": [1.0, 2.0]}, index=pd.Index(["A", "B"], name="account_id")
    )
    clf = FraudClassifier()
    predictions = clf.predict(features_df)
    assert (predictions["fraud_prob"] == 0.0).all()
    assert (predictions["fraud_pred"] == 0).all()


def test_fraud_classifier_train_skips_with_too_few_positives(synthetic_dataset) -> None:
    accounts_df, transactions_df = synthetic_dataset
    store = NetworkXGraphStore(accounts_df, transactions_df)
    features_df = FeatureExtractor(store, accounts_df, transactions_df).extract_all()

    all_clean_labels = pd.Series(0, index=features_df.index)
    clf = FraudClassifier()
    metrics = clf.train(features_df, all_clean_labels, transactions_df)
    assert metrics["train_size"] == 0
    assert clf._fitted is False


def test_role_classifier_assigns_roles(synthetic_dataset) -> None:
    accounts_df, transactions_df = synthetic_dataset
    store = NetworkXGraphStore(accounts_df, transactions_df)
    roles = RoleClassifier().classify_all(store)

    assert len(roles) == len(accounts_df)
    for info in roles.values():
        assert info["role"] in {"SOURCE", "MULE", "SINK", "NORMAL"}
        assert 0.0 <= info["confidence"] <= 1.0


def test_role_classifier_empty_graph_returns_empty() -> None:
    accounts_df = pd.DataFrame({"account_id": []})
    transactions_df = pd.DataFrame(
        columns=["source_account", "dest_account", "amount", "timestamp"]
    )
    store = NetworkXGraphStore(accounts_df, transactions_df)
    assert RoleClassifier().classify_all(store) == {}


def test_ensemble_scorer_compute_priority_thresholds() -> None:
    scorer = EnsembleScorer()
    assert scorer.compute_priority(90, "Very Strong", 20_000_000, 6) == "P1"
    assert scorer.compute_priority(10, "Weak", 1_000, 1) == "P4"


def test_ensemble_scorer_compute_confidence_levels() -> None:
    scorer = EnsembleScorer()
    level, count, indicators = scorer.compute_confidence(
        "ACC0",
        {"layering": True, "round_trip": True},
        anomaly_score=0.0,
        fraud_prob=0.9,
        pagerank=0.01,
        betweenness=0.02,
    )
    # fraud + 2 patterns + pagerank + betweenness = 5 independent indicators.
    assert count == 5
    assert level == "Very Strong"
    assert "XGBoost fraud classifier" in indicators


def test_ensemble_scorer_build_flags() -> None:
    txns = pd.DataFrame([
        {"source_account": "A", "dest_account": "B", "amount": 100.0,
         "timestamp": pd.Timestamp("2026-01-01"), "channel": "UPI"},
        {"source_account": "B", "dest_account": "C", "amount": 90.0,
         "timestamp": pd.Timestamp("2026-01-01 00:10"), "channel": "UPI"},
        {"source_account": "C", "dest_account": "A", "amount": 85.0,
         "timestamp": pd.Timestamp("2026-01-01 00:20"), "channel": "UPI"},
    ])
    store = NetworkXGraphStore(pd.DataFrame({"account_id": ["A", "B", "C"]}), txns)
    results = RoundTripDetector().detect(store, txns)
    flags = EnsembleScorer.build_flags({"round_trip": results})
    assert flags["A"]["round_trip"] is True
    assert flags["B"]["round_trip"] is True


def test_ensemble_scorer_compute_all_produces_scores_in_range(synthetic_dataset) -> None:
    accounts_df, transactions_df = synthetic_dataset
    store = NetworkXGraphStore(accounts_df, transactions_df)
    features_df = FeatureExtractor(store, accounts_df, transactions_df).extract_all()

    anomaly_results = AnomalyDetector().fit_predict(features_df)
    from detection.scoring.training import _build_labels

    labels = _build_labels(transactions_df, features_df)
    clf = FraudClassifier()
    clf.train(features_df, labels, transactions_df)
    fraud_results = clf.predict(features_df)

    cycle_results = RoundTripDetector().detect(store, transactions_df)
    scores = EnsembleScorer().compute_all(
        features_df, anomaly_results, fraud_results,
        {"round_trip": cycle_results}, store,
    )
    assert set(scores.keys()) == set(features_df.index)
    for s in scores.values():
        assert 0.0 <= s <= 100.0
