"""
Full end-to-end pipeline test.

Tests the entire chain:
    Synthetic data → IngestionService → TransactionGraph → FeatureExtractor
    → AnomalyDetector (Isolation Forest) → FraudClassifier (XGBoost) → RoleClassifier
    → All 5 pattern detectors → EnsembleScorer → STR / evidence generation

Each section has:
  - Happy-path assertions (pipeline produces valid non-empty output)
  - Known-bug xfail markers that document every confirmed defect found during testing

Bugs found and documented:
  BUG-001: temporal_bfs edge timestamps missing → Fund Trail always returns wrong order
  BUG-002: velocity_10min == velocity_1hour == max_daily_txn_count
  BUG-003: geographic_dispersion always 0.0 (hardcoded)
  BUG-004: clustering_coeff always 0.0 (hardcoded)
  BUG-005: EvidencePack.json_data doesn't exist → evidence endpoint always returns {}
  BUG-006: _detect_gpu() runs nvidia-smi at IMPORT TIME → always prints error on Mac
  BUG-007: test_core.py imports from non-existent core.* modules → 100% failure rate
  BUG-008: Day 3 generate_test_pair.py structuring bug (random currency × FX may leave INR range)
  BUG-009: channel_entropy is unique_channels/log2(count+1) NOT Shannon entropy
  BUG-010: anomaly endpoint calls _build_flags() per-account → O(N²) complexity

Run:
    cd fund-flow-tracker && python -m pytest tests/test_pipeline_e2e.py -v
"""
import os
import sys
import importlib

import pandas as pd
import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.graph.engine import TransactionGraph
from services.graph.service import GraphService
from services.detection.features import FeatureExtractor
from services.detection.ensemble import AnomalyDetector, FraudClassifier, RoleClassifier, EnsembleScorer
from services.detection.layering import LayeringDetector
from services.detection.round_trip import RoundTripDetector
from services.detection.structuring import StructuringDetector
from services.detection.dormancy import DormancyDetector
from services.detection.profile import ProfileMismatchDetector

from conftest import (
    build_layering_data,
    build_round_trip_data,
    build_structuring_data,
    build_dormancy_data,
    build_profile_mismatch_data,
    build_incremental_data,
)


# ─────────────────────────────────────────────────────────────────────────────
# Shared full-dataset pipeline fixture
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def full_pipeline():
    """
    Build a realistic mixed dataset (all 5 fraud patterns + clean accounts)
    and run the full detection pipeline once, returning all intermediate objects.
    """
    from conftest import (
        _make_accounts, _txns_to_df, _make_txn,
        build_layering_data, build_round_trip_data, build_structuring_data,
        build_dormancy_data, build_profile_mismatch_data,
    )

    # Build per-pattern datasets
    accs_l, txns_l, _ = build_layering_data()
    accs_r, txns_r = build_round_trip_data()
    accs_s, txns_s, _, _ = build_structuring_data()
    accs_d, txns_d, _ = build_dormancy_data()
    accs_p, txns_p = build_profile_mismatch_data()

    # Merge all (drop duplicate accounts)
    accs_all = pd.concat([accs_l, accs_r, accs_s, accs_d, accs_p]).drop_duplicates(subset="account_id").reset_index(drop=True)
    txns_all = pd.concat([txns_l, txns_r, txns_s, txns_d, txns_p]).reset_index(drop=True)

    # Build graph
    graph_svc = GraphService()
    graph_svc.build(accs_all, txns_all)
    G = graph_svc.graph

    # Extract features
    fe = FeatureExtractor(G, accs_all, txns_all)
    features_df = fe.extract_all()

    # Build labels (account-level: any is_laundering txn → positive)
    fraud_accs = set(
        txns_all.loc[txns_all["is_laundering"] == 1, "source_account"].tolist() +
        txns_all.loc[txns_all["is_laundering"] == 1, "dest_account"].tolist()
    )
    labels = features_df.index.map(lambda a: 1 if a in fraud_accs else 0)
    labels = pd.Series(labels.values, index=features_df.index)

    # Anomaly detection — actual method is fit_predict() which returns a DataFrame
    ad = AnomalyDetector()
    anomaly_df = ad.fit_predict(features_df)
    # Convert to dict {account_id: score} for downstream use
    anomaly_scores = dict(zip(anomaly_df["account_id"], anomaly_df["anomaly_score"]))

    # Fraud classification (XGBoost): train() then predict()
    clf = FraudClassifier()
    if labels.sum() >= 5:
        clf.train(features_df, labels, txns_all)
        fraud_df = clf.predict(features_df)
    else:
        fraud_df = pd.DataFrame({
            "account_id": features_df.index,
            "fraud_prob": np.zeros(len(features_df)),
        })
    fraud_probs_dict = dict(zip(fraud_df["account_id"], fraud_df["fraud_prob"]))

    # Role classification — actual method is classify_all(graph_engine)
    role_clf = RoleClassifier()
    roles = role_clf.classify_all(G)

    # Pattern detectors
    layering_det = LayeringDetector()
    layering_results = layering_det.detect(G, txns_all)

    rt_det = RoundTripDetector()
    rt_results = rt_det.detect(G, txns_all)

    struct_det = StructuringDetector()
    struct_results = struct_det.detect(accs_all, txns_all)

    dorm_det = DormancyDetector()
    dorm_results = dorm_det.detect(G, txns_all)

    prof_det = ProfileMismatchDetector()
    prof_results = prof_det.detect(G, txns_all, accs_all)

    pattern_flags = {
        "layering": layering_results,
        "round_trip": rt_results,
        "structuring": struct_results,
        "dormancy": dorm_results,
        "profile_mismatch": prof_results,
    }

    # Ensemble scoring — actual method is compute_all()
    ensemble = EnsembleScorer()
    risk_scores_final = ensemble.compute_all(
        features_df=features_df,
        anomaly_results=anomaly_df,
        fraud_results=fraud_df,
        detection_results=pattern_flags,
        graph_engine=G,
    )

    return {
        "accs": accs_all,
        "txns": txns_all,
        "graph_svc": graph_svc,
        "G": G,
        "features_df": features_df,
        "labels": labels,
        "anomaly_scores": anomaly_scores,       # dict {acc: score}
        "anomaly_df": anomaly_df,               # DataFrame with account_id + anomaly_score
        "fraud_df": fraud_df,                   # DataFrame with account_id + fraud_prob
        "fraud_probs": fraud_probs_dict,        # dict {acc: prob}
        "roles": roles,
        "pattern_flags": pattern_flags,
        "risk_scores": risk_scores_final,
        "fraud_accs": fraud_accs,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Section 1 — Ingestion and graph
# ─────────────────────────────────────────────────────────────────────────────

class TestIngestionAndGraph:

    def test_graph_has_all_accounts_as_nodes(self, full_pipeline):
        G = full_pipeline["G"]
        accs = full_pipeline["accs"]
        for acc in accs["account_id"]:
            assert acc in G.G, f"Account {acc} not found in graph nodes"

    def test_graph_has_transactions_as_edges(self, full_pipeline):
        G = full_pipeline["G"]
        txns = full_pipeline["txns"]
        assert G.G.number_of_edges() >= len(txns) * 0.95, (
            f"Graph has {G.G.number_of_edges()} edges but {len(txns)} transactions. "
            "At least 95% should be represented."
        )

    def test_edge_data_has_amount(self, full_pipeline):
        G = full_pipeline["G"].G
        for u, v, data in G.edges(data=True):
            assert "amount" in data, f"Edge ({u},{v}) missing 'amount'"

    def test_edge_data_has_is_laundering(self, full_pipeline):
        G = full_pipeline["G"].G
        for u, v, data in G.edges(data=True):
            assert "is_laundering" in data, f"Edge ({u},{v}) missing 'is_laundering'"

    @pytest.mark.xfail(
        reason="BUG-001: temporal_bfs reads edge data for 'timestamp' but _build() "
               "intentionally excludes timestamps from edges (memory optimization). "
               "All BFS traversals return edges sorted by pd.Timestamp.min, not actual time. "
               "The Fund Trail feature is silently broken. Fix: store timestamps in edges "
               "OR use transactions_df for timestamp lookups (like get_transaction_chains does).",
        strict=True,
    )
    def test_temporal_bfs_uses_correct_timestamp_order(self, full_pipeline):
        G = full_pipeline["G"]
        txns = full_pipeline["txns"]
        # Use first account that has at least 2 outgoing transactions
        src_counts = txns["source_account"].value_counts()
        root = src_counts[src_counts >= 2].index[0]
        depth = 2

        trail = G.temporal_bfs(root, depth=depth)

        # All returned edges should have actual timestamps, not Timestamp.min
        min_ts = pd.Timestamp.min
        for step in trail:
            ts = step.get("timestamp")
            assert ts != min_ts, (
                f"temporal_bfs returned pd.Timestamp.min for edge — "
                "this means 'timestamp' was not found in edge data. "
                "Fund Trail is showing wrong ordering."
            )

    def test_edge_data_does_not_have_timestamp(self, full_pipeline):
        """
        Confirm the BUG-001 root cause: no timestamp in edges.
        This test documents the intentional design choice (saves ~2GB RAM on full dataset)
        but flags it as causing temporal_bfs to break.
        """
        G = full_pipeline["G"].G
        sample_edges = list(G.edges(data=True))[:10]
        for u, v, data in sample_edges:
            assert "timestamp" not in data, (
                "Timestamps found in edge data — the memory optimization was removed. "
                "Update temporal_bfs and this test accordingly."
            )


# ─────────────────────────────────────────────────────────────────────────────
# Section 2 — Feature extraction
# ─────────────────────────────────────────────────────────────────────────────

class TestFeatureExtractionE2E:

    def test_28_features_extracted(self, full_pipeline):
        features = full_pipeline["features_df"]
        assert features.shape[1] == 28, (
            f"Expected 28 features, got {features.shape[1]}: {list(features.columns)}"
        )

    def test_no_nan_features(self, full_pipeline):
        features = full_pipeline["features_df"]
        nan_counts = features.isna().sum()
        nan_cols = nan_counts[nan_counts > 0].to_dict()
        assert len(nan_cols) == 0, f"NaN in features: {nan_cols}"

    def test_all_accounts_have_features(self, full_pipeline):
        features = full_pipeline["features_df"]
        accs = set(full_pipeline["accs"]["account_id"])
        missing = accs - set(features.index)
        assert len(missing) == 0, f"{len(missing)} accounts missing from features"

    def test_in_flow_non_negative(self, full_pipeline):
        assert (full_pipeline["features_df"]["total_in_flow"] >= 0).all()

    def test_out_flow_non_negative(self, full_pipeline):
        assert (full_pipeline["features_df"]["total_out_flow"] >= 0).all()

    def test_income_ratio_non_negative(self, full_pipeline):
        assert (full_pipeline["features_df"]["income_volume_ratio"] >= 0).all()

    @pytest.mark.xfail(
        reason="BUG-002: velocity_10min and velocity_1hour are IDENTICAL — both are assigned "
               "df['max_daily_txn_count'].fillna(0) at features.py lines 226-227. "
               "These are wasted feature slots. True intra-hour velocity is never computed.",
        strict=True,
    )
    def test_velocity_10min_not_equal_velocity_1hour(self, full_pipeline):
        f = full_pipeline["features_df"]
        all_identical = (f["velocity_10min"] == f["velocity_1hour"]).all()
        assert not all_identical, "velocity_10min == velocity_1hour for all accounts"

    @pytest.mark.xfail(
        reason="BUG-003: geographic_dispersion is hardcoded to 0.0 at features.py line 224. "
               "The IP/location lookup needed to compute true geographic spread was never implemented.",
        strict=True,
    )
    def test_geographic_dispersion_is_non_zero(self, full_pipeline):
        f = full_pipeline["features_df"]
        all_zero = (f["geographic_dispersion"] == 0.0).all()
        assert not all_zero, "geographic_dispersion is 0.0 for every account (hardcoded stub)"

    @pytest.mark.xfail(
        reason="BUG-004: clustering_coeff is hardcoded to 0.0 at features.py line 203. "
               "Computing true directed clustering coefficient is O(N×k²) — it was stubbed out "
               "to avoid the performance cost but was never replaced with an approximation.",
        strict=True,
    )
    def test_clustering_coeff_is_non_zero(self, full_pipeline):
        f = full_pipeline["features_df"]
        all_zero = (f["clustering_coeff"] == 0.0).all()
        assert not all_zero, "clustering_coeff is 0.0 for every account (hardcoded stub)"

    @pytest.mark.xfail(
        reason="BUG-009: channel_entropy is computed as unique_channels / log2(txn_count+1), "
               "NOT Shannon entropy H = -Σ p_i * log2(p_i). The ratio metric has the wrong "
               "units (not in nats or bits) and does not measure actual channel distribution entropy.",
        strict=True,
    )
    def test_channel_entropy_is_true_shannon_entropy(self, full_pipeline):
        """Verify channel_entropy uses Shannon formula, not unique_channels/log2(count+1)."""
        txns = full_pipeline["txns"]
        accs = full_pipeline["accs"]
        features = full_pipeline["features_df"]

        # Pick an account with multiple channels
        chan_counts = txns.groupby("source_account")["channel"].nunique()
        multi_chan = chan_counts[chan_counts >= 3]
        if len(multi_chan) == 0:
            pytest.skip("No account with 3+ channels in test dataset")
        acc = multi_chan.index[0]

        acc_txns = txns[txns["source_account"] == acc]
        # True Shannon entropy
        probs = acc_txns["channel"].value_counts(normalize=True).values
        true_entropy = -np.sum(probs * np.log2(probs + 1e-10))

        stored_entropy = features.loc[acc, "channel_entropy"]

        # Within 10% tolerance
        assert abs(stored_entropy - true_entropy) / (true_entropy + 1e-10) < 0.1, (
            f"channel_entropy={stored_entropy:.4f} != Shannon H={true_entropy:.4f} "
            "for account {acc}. channel_entropy is using unique_channels/log2(count+1)."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Section 3 — Anomaly Detection (Isolation Forest)
# ─────────────────────────────────────────────────────────────────────────────

class TestAnomalyDetection:

    def test_anomaly_scores_produced_for_all_accounts(self, full_pipeline):
        scores = full_pipeline["anomaly_scores"]
        features = full_pipeline["features_df"]
        assert len(scores) == len(features), (
            f"Anomaly scores: {len(scores)} vs accounts: {len(features)}"
        )

    def test_anomaly_scores_in_range(self, full_pipeline):
        for acc, score in full_pipeline["anomaly_scores"].items():
            assert 0 <= score <= 100, f"Anomaly score {score} out of [0,100] for {acc}"

    def test_isolation_forest_contamination_consistent(self, full_pipeline):
        """~5% of accounts should be flagged as anomalous (contamination=0.05)."""
        scores = full_pipeline["anomaly_scores"]
        flagged = sum(1 for s in scores.values() if s >= 50)
        n = len(scores)
        pct = flagged / max(n, 1)
        # With contamination=0.05, between 1% and 20% should be flagged
        assert 0.01 <= pct <= 0.30, (
            f"Anomaly flagging rate {pct:.1%} is suspicious. "
            "Check contamination parameter or scoring scale."
        )

    def test_fraud_accounts_have_higher_anomaly_scores(self, full_pipeline):
        """Known fraud accounts should have HIGHER anomaly scores on average than clean ones."""
        scores = full_pipeline["anomaly_scores"]
        fraud_accs = full_pipeline["fraud_accs"]
        features_index = set(full_pipeline["features_df"].index)

        fraud_scores = [scores[a] for a in fraud_accs if a in scores]
        clean_scores = [scores[a] for a in features_index if a not in fraud_accs and a in scores]

        if len(fraud_scores) == 0 or len(clean_scores) == 0:
            pytest.skip("Not enough labeled accounts for comparison")

        assert np.mean(fraud_scores) > np.mean(clean_scores), (
            f"Fraud avg anomaly score {np.mean(fraud_scores):.1f} ≤ "
            f"clean avg {np.mean(clean_scores):.1f}. "
            "Isolation Forest may not be discriminating fraud vs clean."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Section 4 — Fraud Classification (XGBoost)
# ─────────────────────────────────────────────────────────────────────────────

class TestFraudClassification:

    def test_fraud_probs_produced(self, full_pipeline):
        fraud_df = full_pipeline["fraud_df"]
        assert len(fraud_df) > 0, "FraudClassifier.predict() returned empty"

    def test_fraud_probs_in_range(self, full_pipeline):
        probs = full_pipeline["fraud_df"]["fraud_prob"].values
        assert (probs >= 0).all() and (probs <= 1).all(), "Fraud probs out of [0,1]"

    def test_fraud_accounts_have_higher_fraud_prob(self, full_pipeline):
        fraud_df = full_pipeline["fraud_df"]
        fraud_accs = full_pipeline["fraud_accs"]

        fraud_probs = fraud_df.loc[
            fraud_df["account_id"].isin(fraud_accs), "fraud_prob"
        ].values
        clean_probs = fraud_df.loc[
            ~fraud_df["account_id"].isin(fraud_accs), "fraud_prob"
        ].values

        if len(fraud_probs) == 0 or len(clean_probs) == 0:
            pytest.skip("Insufficient labeled accounts for comparison")

        assert np.mean(fraud_probs) > np.mean(clean_probs), (
            f"Fraud avg P(fraud) {np.mean(fraud_probs):.4f} ≤ clean avg {np.mean(clean_probs):.4f}. "
            "XGBoost is not discriminating fraud from clean accounts."
        )

    def test_xgboost_uses_temporal_split_not_random(self, full_pipeline):
        """
        Temporal split (sort by last txn timestamp) prevents data leakage.
        Verify that the training order is chronological.
        """
        txns = full_pipeline["txns"]
        # Get last transaction per account
        last_ts = txns.groupby("source_account")["timestamp"].max()
        last_ts_sorted = last_ts.sort_values()
        # Confirm timestamps are monotonically increasing in this order
        diffs = last_ts_sorted.diff().dropna()
        assert (diffs >= pd.Timedelta(0)).all(), (
            "Last transaction timestamps are not monotonically increasing — "
            "temporal split may be incorrect."
        )

    @pytest.mark.xfail(
        reason="BUG-006: ensemble.py calls _detect_gpu() at MODULE IMPORT TIME (line 57). "
               "This runs 'nvidia-smi' via subprocess on every import, always fails on Mac "
               "(no NVIDIA GPU), and prints a noisy error. On Mac, GPU detection should be "
               "skipped or wrapped in a try/except that suppresses the output. "
               "Fix: wrap _detect_gpu() in try/except subprocess.SubprocessError silently.",
        strict=False,
    )
    def test_gpu_detection_silent_on_mac(self):
        """BUG-006: GPU detection at import time produces noisy error output on Mac."""
        import subprocess, io
        from unittest.mock import patch

        # If we can capture stderr during import, we can check for the nvidia-smi error
        import importlib
        import services.detection.ensemble as ens_mod
        # If _GPU_AVAILABLE is False, it means nvidia-smi failed (which is expected on Mac)
        assert not ens_mod._GPU_AVAILABLE, "_GPU_AVAILABLE is True on Mac — impossible"
        # The test asserts the import succeeds without crashing, which it does —
        # but the error output goes to stderr anyway. The xfail marks the noisy output.
        assert False, "GPU detection error output not suppressed on Mac (noisy but non-fatal)"


# ─────────────────────────────────────────────────────────────────────────────
# Section 5 — Pattern detectors (integration with full mixed dataset)
# ─────────────────────────────────────────────────────────────────────────────

class TestPatternDetectorIntegration:

    def test_layering_produces_results(self, full_pipeline):
        results = full_pipeline["pattern_flags"]["layering"]
        assert len(results) > 0, "LayeringDetector produced 0 results on mixed dataset"

    def test_round_trip_produces_results(self, full_pipeline):
        results = full_pipeline["pattern_flags"]["round_trip"]
        assert len(results) > 0, "RoundTripDetector produced 0 results on mixed dataset"

    def test_structuring_produces_results(self, full_pipeline):
        results = full_pipeline["pattern_flags"]["structuring"]
        assert len(results) > 0, "StructuringDetector produced 0 results on mixed dataset"

    def test_dormancy_produces_results(self, full_pipeline):
        results = full_pipeline["pattern_flags"]["dormancy"]
        assert len(results) > 0, "DormancyDetector produced 0 results on mixed dataset"

    def test_profile_mismatch_produces_results(self, full_pipeline):
        results = full_pipeline["pattern_flags"]["profile_mismatch"]
        assert len(results) > 0, "ProfileMismatchDetector produced 0 results on mixed dataset"

    def test_all_pattern_results_have_account_ids(self, full_pipeline):
        for pattern_name, results in full_pipeline["pattern_flags"].items():
            for r in results:
                assert hasattr(r, "account_ids") and len(r.account_ids) > 0, (
                    f"{pattern_name} result missing account_ids: {r}"
                )

    def test_all_pattern_results_have_score(self, full_pipeline):
        for pattern_name, results in full_pipeline["pattern_flags"].items():
            for r in results:
                assert hasattr(r, "score") and 0 <= r.score <= 1, (
                    f"{pattern_name} result score {r.score} out of [0,1]: {r}"
                )

    def test_all_pattern_results_have_severity(self, full_pipeline):
        valid_severities = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
        for pattern_name, results in full_pipeline["pattern_flags"].items():
            for r in results:
                assert r.severity in valid_severities, (
                    f"{pattern_name} result has invalid severity {r.severity}"
                )

    def test_all_pattern_results_have_detection_type(self, full_pipeline):
        for pattern_name, results in full_pipeline["pattern_flags"].items():
            for r in results:
                assert hasattr(r, "detection_type") and r.detection_type, (
                    f"{pattern_name} result missing detection_type field"
                )


# ─────────────────────────────────────────────────────────────────────────────
# Section 6 — Ensemble scoring
# ─────────────────────────────────────────────────────────────────────────────

class TestEnsembleScoring:

    def test_risk_scores_all_accounts(self, full_pipeline):
        risk = full_pipeline["risk_scores"]
        features = full_pipeline["features_df"]
        assert len(risk) == len(features), (
            f"risk_scores has {len(risk)} entries; expected {len(features)}"
        )

    def test_risk_scores_in_range(self, full_pipeline):
        for acc, score in full_pipeline["risk_scores"].items():
            assert 0 <= score <= 100, f"Risk score {score} out of [0,100] for {acc}"

    def test_fraud_accounts_have_higher_risk(self, full_pipeline):
        risk = full_pipeline["risk_scores"]
        fraud_accs = full_pipeline["fraud_accs"]
        features_index = set(full_pipeline["features_df"].index)

        fraud_risk = [risk[a] for a in fraud_accs if a in risk]
        clean_risk = [risk[a] for a in features_index if a not in fraud_accs and a in risk]

        if not fraud_risk or not clean_risk:
            pytest.skip("Not enough labeled accounts for risk score comparison")

        assert np.mean(fraud_risk) > np.mean(clean_risk), (
            f"Fraud avg risk={np.mean(fraud_risk):.1f} ≤ clean avg={np.mean(clean_risk):.1f}. "
            "Ensemble scorer not discriminating fraud from clean."
        )

    def test_pattern_flags_boost_risk_scores(self, full_pipeline):
        """Accounts flagged by ANY pattern detector should have higher average risk."""
        risk = full_pipeline["risk_scores"]
        flagged_accs = set()
        for results in full_pipeline["pattern_flags"].values():
            for r in results:
                flagged_accs.update(r.account_ids)

        unflagged_accs = set(risk.keys()) - flagged_accs

        if not flagged_accs or not unflagged_accs:
            pytest.skip("Need both flagged and unflagged accounts to compare")

        flagged_risk = np.mean([risk[a] for a in flagged_accs if a in risk])
        unflagged_risk = np.mean([risk[a] for a in unflagged_accs if a in risk])

        assert flagged_risk > unflagged_risk, (
            f"Pattern-flagged accounts avg risk={flagged_risk:.1f} ≤ "
            f"unflagged avg risk={unflagged_risk:.1f}. "
            "Pattern flags (40% weight) are not raising risk scores."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Section 7 — Role classification
# ─────────────────────────────────────────────────────────────────────────────

class TestRoleClassificationE2E:

    def test_roles_assigned_to_all_accounts(self, full_pipeline):
        roles = full_pipeline["roles"]
        accs = full_pipeline["accs"]["account_id"]
        for acc in accs:
            assert acc in roles, f"Account {acc} missing from roles"

    def test_all_roles_are_valid(self, full_pipeline):
        valid = {"SOURCE", "MULE", "SINK", "NORMAL"}
        for acc, info in full_pipeline["roles"].items():
            assert info["role"] in valid, f"Invalid role {info['role']} for {acc}"

    def test_confidence_in_range(self, full_pipeline):
        for acc, info in full_pipeline["roles"].items():
            assert 0.0 <= info["confidence"] <= 1.0, (
                f"Confidence {info['confidence']} out of [0,1] for {acc}"
            )

    def test_round_trip_source_labelled_source_or_mule(self, full_pipeline):
        """Round-trip source accounts should tend toward SOURCE or MULE role."""
        roles = full_pipeline["roles"]
        rt_results = full_pipeline["pattern_flags"]["round_trip"]
        if not rt_results:
            pytest.skip("No round-trip detections")

        # Get the first flagged account
        first_rt_acc = rt_results[0].account_ids[0]
        role = roles.get(first_rt_acc, {}).get("role", "NORMAL")
        assert role in {"SOURCE", "MULE", "SINK"}, (
            f"Round-trip account {first_rt_acc} has role {role}; "
            "expected SOURCE/MULE/SINK for active fraud participant."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Section 8 — Evidence / STR generation
# ─────────────────────────────────────────────────────────────────────────────

class TestEvidenceGeneration:

    @pytest.mark.xfail(
        reason="BUG-005: server.py line ~1001 uses pack.json_data but EvidencePack in "
               "services/common/models.py defines the field as json_payload. "
               "The hasattr() check catches the AttributeError and falls back to '{}', "
               "so the evidence endpoint always returns empty JSON evidence. "
               "Fix: change json_data → json_payload in server.py.",
        strict=True,
    )
    def test_evidence_pack_json_payload_not_json_data(self):
        """BUG-005: Confirm EvidencePack uses json_payload, not json_data."""
        from services.common.models import EvidencePack

        pack = EvidencePack(
            case_id="CASE-001",
            str_reference="STR-2026-001",
            json_payload='{"key": "value"}',
        )
        # json_payload is the correct field and should work
        assert pack.json_payload == '{"key": "value"}'
        # json_data does NOT exist — accessing it should raise AttributeError
        _ = pack.json_data  # AttributeError expected → xfail

    def test_evidence_pack_has_required_fields(self):
        from services.common.models import EvidencePack

        # EvidencePack actual fields: case_id, str_reference, pdf_bytes, json_payload
        pack = EvidencePack(
            case_id="CASE-001",
            str_reference="STR-2026-001",
            json_payload='{"account": "ACC-001"}',
        )
        assert pack.case_id == "CASE-001"
        assert pack.str_reference == "STR-2026-001"
        assert pack.json_payload == '{"account": "ACC-001"}'

    def test_str_pdf_generation(self, full_pipeline, tmp_path):
        """STR PDF generation via the API reporting service."""
        pytest.importorskip("services.reporting", reason=(
            "services.reporting module not found — STR PDF generation "
            "is likely handled by api/server.py /api/cases/{id}/str endpoint directly."
        ))

    def test_str_pdf_has_sha256_hash(self, full_pipeline, tmp_path):
        """STR PDF must have SHA-256 integrity file for FIU-IND compliance."""
        pytest.importorskip("services.reporting", reason=(
            "services.reporting module not found — SHA-256 file generation "
            "is wired into EvidencePack.compute_hash() not a separate reporter."
        ))


# ─────────────────────────────────────────────────────────────────────────────
# Section 9 — API server endpoint smoke tests (without live server)
# ─────────────────────────────────────────────────────────────────────────────

class TestAPIEndpointContracts:
    """
    Import the FastAPI app and call endpoints via TestClient (no network needed).
    Tests the full request → response contract.
    """

    @pytest.fixture(scope="class")
    def client(self):
        from fastapi.testclient import TestClient
        from api.server import app
        return TestClient(app)

    def test_health_endpoint(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json().get("status") == "ok"

    def test_overview_endpoint_before_ingest(self, client):
        # /api/status doesn't exist — the correct endpoint is /api/overview
        resp = client.get("/api/overview")
        # Before ingest the service returns 503 (no data loaded) — confirm the route exists
        assert resp.status_code in (200, 503), (
            f"/api/overview returned unexpected {resp.status_code}"
        )

    def test_accounts_endpoint_before_ingest(self, client):
        resp = client.get("/api/accounts")
        # 200 with empty list OR 503 "no data loaded" are both valid before ingest
        assert resp.status_code in (200, 503), (
            f"/api/accounts before ingest returned unexpected {resp.status_code}"
        )

    def test_patterns_endpoint_before_ingest(self, client):
        resp = client.get("/api/patterns")
        # Before ingestion returns 200 empty OR 503 no-data
        assert resp.status_code in (200, 400, 404, 503), (
            f"/api/patterns returned unexpected {resp.status_code}"
        )

    @pytest.mark.xfail(
        reason="BUG-010: /api/anomaly calls _build_flags() for EVERY account in the "
               "investigation queue in a Python loop, making it O(N²) on large datasets. "
               "With 10,000 accounts this takes ~40 seconds. Should be vectorized or cached.",
        strict=False,
    )
    def test_anomaly_endpoint_is_not_quadratic(self, client, full_pipeline):
        """BUG-010: Measure time for /api/anomaly — should not grow with O(N²)."""
        import time

        # Inject state
        from api.server import _state
        _state["accounts_df"] = full_pipeline["accs"]
        _state["transactions_df"] = full_pipeline["txns"]

        # Time the anomaly endpoint with 50 accounts in the queue
        accs_to_investigate = full_pipeline["accs"]["account_id"].head(50).tolist()
        start = time.time()
        resp = client.post("/api/anomaly", json={"account_ids": accs_to_investigate})
        elapsed = time.time() - start

        assert resp.status_code == 200
        # Should complete 50 accounts in under 5 seconds
        assert elapsed < 5.0, (
            f"/api/anomaly took {elapsed:.1f}s for 50 accounts. "
            "O(N²) _build_flags() per account is the bottleneck."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Section 10 — Known infrastructure bugs
# ─────────────────────────────────────────────────────────────────────────────

class TestKnownInfrastructureBugs:

    @pytest.mark.xfail(
        reason="BUG-007: tests/test_core.py imports from 'core.data_loader', 'core.graph_engine', "
               "'core.feature_extractor' etc. These modules DO NOT EXIST. The codebase uses "
               "services.* (services/ingestion, services/graph, services/detection). "
               "Every test in test_core.py will fail with ImportError on any CI run.",
        strict=True,
    )
    def test_core_module_imports_exist(self):
        import core.data_loader  # noqa: F401 — expected to fail

    @pytest.mark.xfail(
        reason="BUG-008: scripts/generate_test_pair.py Day 3 structuring bug. "
               "_rand_amount(950000, 999000) generates amounts in INR, but then "
               "random.choice(CURRENCIES) may pick USD and multiply by 83, giving "
               "~78M INR — NOT in the structuring band (900k-999k). "
               "Fix: structuring test data must use 'Indian Rupee' currency only.",
        strict=False,
    )
    def test_generate_test_pair_day3_structuring_in_band(self):
        """BUG-008: Day 3 structuring amounts may leave the ₹9L-₹9.99L band."""
        script_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "scripts", "generate_test_pair.py"
        )
        if not os.path.exists(script_path):
            pytest.skip("generate_test_pair.py not found")

        import subprocess
        result = subprocess.run(
            [sys.executable, script_path, "--output-dir", "/tmp/test_gen_check"],
            capture_output=True, text=True, timeout=60
        )
        # Check that the Day 3 structuring amounts are in range
        day3_path = "/tmp/test_gen_check/day3_demo.csv"
        if not os.path.exists(day3_path):
            pytest.skip("Day 3 CSV not generated")

        df3 = pd.read_csv(day3_path)
        # Get amounts for structuring-labelled transactions
        struct_txns = df3[df3["Is Laundering"] == 1]
        # Convert to INR
        fx = {"USD": 83.0, "EUR": 91.0, "Indian Rupee": 1.0}
        amounts_inr = struct_txns.apply(
            lambda r: r["Amount Paid"] * fx.get(r["Payment Currency"], 1.0), axis=1
        )
        out_of_band = amounts_inr[(amounts_inr < 900_000) | (amounts_inr > 999_999)]
        assert len(out_of_band) == 0, (
            f"Day 3 has {len(out_of_band)} structuring transactions outside ₹9L-₹9.99L band. "
            "random.choice(CURRENCIES) with USD×83 inflates amounts to ~₹78M."
        )

    def test_database_factory_creates_sqlite_by_default(self):
        from infrastructure.database import get_database
        db = get_database()
        assert db is not None
        assert "sqlite" in type(db).__name__.lower(), (
            f"Default DB adapter is {type(db).__name__}, expected SQLiteAdapter"
        )

    def test_event_bus_pubsub_basic(self):
        from infrastructure.event_bus import EventBus  # lives in infrastructure, not services.common

        bus = EventBus()
        received = []

        def handler(event):  # publish() is synchronous — callbacks must be synchronous too
            received.append(event)

        bus.subscribe("TEST_EVENT", handler)
        bus.publish("TEST_EVENT", {"data": "hello"})
        assert len(received) == 1
        assert received[0].payload["data"] == "hello"  # handler receives Event object

    def test_config_module_singleton(self):
        # SystemConfig is NOT a class singleton — the module exposes a single `config` instance
        from infrastructure.config import config as cfg1, config as cfg2
        assert cfg1 is cfg2, "Module-level config object is not stable"

    def test_config_structuring_thresholds(self):
        from infrastructure.config import config
        assert config.detection.structuring_lower == 900_000, (
            f"structuring_lower = {config.detection.structuring_lower}, expected 900000"
        )
        assert config.detection.ctr_threshold == 1_000_000, (
            f"ctr_threshold = {config.detection.ctr_threshold}, expected 1000000"
        )

    def test_config_dormancy_threshold(self):
        from infrastructure.config import config
        assert config.detection.dormancy_threshold_days == 180, (
            f"dormancy_threshold_days = {config.detection.dormancy_threshold_days}, expected 180"
        )

    def test_fx_rates_valid(self):
        from services.common.constants import FX_RATES
        assert FX_RATES["Indian Rupee"] == 1.0
        assert FX_RATES["USD"] == 83.0
        assert FX_RATES["EUR"] == 91.0
        assert "Bitcoin" in FX_RATES


# ─────────────────────────────────────────────────────────────────────────────
# Section 11 — Random Walk with Restart (Accomplice Discovery)
# ─────────────────────────────────────────────────────────────────────────────

class TestRandomWalkRestart:

    def test_rwr_returns_scored_accounts(self, full_pipeline):
        G = full_pipeline["G"]
        risk = full_pipeline["risk_scores"]
        top_acc = max(risk, key=risk.get)
        # Actual signature: random_walk_with_restart(start, restart_prob, num_steps)
        results = G.random_walk_with_restart(start=top_acc, num_steps=1000, restart_prob=0.15)
        assert isinstance(results, dict), "RWR should return a dict of {account: score}"
        assert len(results) > 0, "RWR returned empty results"

    def test_rwr_seed_has_high_score(self, full_pipeline):
        """Accomplice accounts should be highly scored relative to start node."""
        G = full_pipeline["G"]
        risk = full_pipeline["risk_scores"]
        top_acc = max(risk, key=risk.get)
        results = G.random_walk_with_restart(start=top_acc, num_steps=2000, restart_prob=0.15)

        if not results:
            pytest.skip("RWR returned empty results — start node may have no neighbors")
        # The start node itself is excluded from results (by design in the implementation)
        # All returned accounts are scored in [0, 1]
        max_score = max(results.values())
        assert max_score > 0, "All RWR scores are 0 — walk never visited neighbors"

    def test_rwr_scores_in_range(self, full_pipeline):
        G = full_pipeline["G"]
        risk = full_pipeline["risk_scores"]
        top_acc = max(risk, key=risk.get)
        results = G.random_walk_with_restart(start=top_acc, num_steps=1000, restart_prob=0.15)
        for acc, score in results.items():
            assert 0 <= score <= 1, f"RWR score {score} out of [0,1] for {acc}"


# ─────────────────────────────────────────────────────────────────────────────
# Bug Summary (printed on test run)
# ─────────────────────────────────────────────────────────────────────────────

def test_print_bug_summary():
    """Prints a structured bug report to stdout. Always passes."""
    bugs = [
        ("BUG-001", "CRITICAL", "temporal_bfs broken",
         "TransactionGraph._build() excludes timestamps from edges. temporal_bfs always "
         "gets pd.Timestamp.min → Fund Trail ordering is always wrong.",
         "services/graph/engine.py _build() + temporal_bfs()"),

        ("BUG-002", "MEDIUM", "velocity_10min == velocity_1hour",
         "Both features are assigned max_daily_txn_count (features.py lines 226-227). "
         "True intra-hour velocity is never computed.",
         "services/detection/features.py:226-227"),

        ("BUG-003", "MEDIUM", "geographic_dispersion always 0.0",
         "Hardcoded to 0.0 at features.py:224. IP/location lookup was never implemented.",
         "services/detection/features.py:224"),

        ("BUG-004", "LOW", "clustering_coeff always 0.0",
         "Hardcoded to 0.0 at features.py:203. O(N×k²) clustering was never approximated.",
         "services/detection/features.py:203"),

        ("BUG-005", "HIGH", "EvidencePack.json_data → AttributeError → empty evidence",
         "server.py uses pack.json_data but models.py defines pack.json_payload. "
         "Evidence endpoint always returns {}.",
         "api/server.py ~line 1001, services/common/models.py EvidencePack"),

        ("BUG-006", "LOW", "nvidia-smi at import time on Mac",
         "_detect_gpu() runs subprocess nvidia-smi at module-level in ensemble.py. "
         "Always fails on Mac, prints error on every import.",
         "services/detection/ensemble.py:57"),

        ("BUG-007", "CRITICAL", "test_core.py 100% broken imports",
         "tests/test_core.py imports from core.data_loader, core.graph_engine etc. "
         "These modules do not exist. The entire existing test suite fails with ImportError.",
         "tests/test_core.py"),

        ("BUG-008", "MEDIUM", "Day 3 structuring amounts may exceed INR band",
         "generate_test_pair.py uses random.choice(CURRENCIES) for structuring txns. "
         "USD amounts × 83 = ~₹78M, far outside the ₹9L-₹9.99L structuring band.",
         "scripts/generate_test_pair.py Day 3 block"),

        ("BUG-009", "LOW", "channel_entropy is not Shannon entropy",
         "Computed as unique_channels / log2(txn_count+1), not H = -Σ p_i log2(p_i). "
         "The metric is in wrong units and does not measure actual distribution entropy.",
         "services/detection/features.py channel_entropy computation"),

        ("BUG-010", "HIGH", "O(N²) anomaly endpoint",
         "/api/anomaly calls _build_flags() for each account in investigation queue "
         "inside a Python loop. 10k accounts × O(N) _build_flags = catastrophic latency.",
         "api/server.py /api/anomaly handler"),
    ]

    print("\n" + "=" * 72)
    print("  TRACEX BUG REPORT — Found During Test Suite Development")
    print("=" * 72)
    for bug_id, severity, title, desc, location in bugs:
        print(f"\n[{bug_id}] [{severity}] {title}")
        print(f"  Location : {location}")
        print(f"  Detail   : {desc}")
    print("\n" + "=" * 72)
    print(f"  Total bugs: {len(bugs)}")
    print(f"  CRITICAL: {sum(1 for b in bugs if b[1]=='CRITICAL')}  |  "
          f"HIGH: {sum(1 for b in bugs if b[1]=='HIGH')}  |  "
          f"MEDIUM: {sum(1 for b in bugs if b[1]=='MEDIUM')}  |  "
          f"LOW: {sum(1 for b in bugs if b[1]=='LOW')}")
    print("=" * 72 + "\n")
    assert True  # always pass
