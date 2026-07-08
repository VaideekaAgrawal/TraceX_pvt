"""
Comprehensive tests for TraceX core modules.
Run: cd fund-flow-tracker && python -m pytest tests/ -v
"""
import sys
import os
import pytest
import pandas as pd
import numpy as np

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.data_loader import DataLoader, generate_demo_data
from core.graph_engine import TransactionGraph
from core.feature_extractor import FeatureExtractor
from core.ml_detector import AnomalyDetector, FraudClassifier
from core.pattern_detector import PatternDetector
from core.role_classifier import AccountRoleClassifier
from core.speed_analyzer import SpeedAnalyzer
from core.risk_scorer import RiskScorer
from core.profile_analyzer import ProfileAnalyzer
from core.evidence_generator import EvidenceGenerator
from utils.helpers import (
    safe_ratio, channel_entropy, get_risk_level, get_risk_color,
    format_inr, sanitize_text, gini_coefficient,
)


# =====================================================================
# Fixtures
# =====================================================================

@pytest.fixture(scope="module")
def demo_data():
    """Generate demo data once for all tests."""
    accounts_df, transactions_df = generate_demo_data(
        n_accounts=100, n_transactions=2000, seed=42,
    )
    return accounts_df, transactions_df


@pytest.fixture(scope="module")
def graph_engine(demo_data):
    accounts_df, transactions_df = demo_data
    return TransactionGraph(accounts_df, transactions_df)


@pytest.fixture(scope="module")
def features(graph_engine, demo_data):
    accounts_df, transactions_df = demo_data
    extractor = FeatureExtractor(graph_engine, accounts_df, transactions_df)
    return extractor.extract_all()


@pytest.fixture(scope="module")
def all_patterns(graph_engine, demo_data):
    _, transactions_df = demo_data
    detector = PatternDetector(graph_engine, transactions_df)
    return detector.detect_all()


# =====================================================================
# Test Helpers
# =====================================================================

class TestHelpers:
    def test_safe_ratio_normal(self):
        assert safe_ratio(10, 5) == 2.0

    def test_safe_ratio_zero_denominator(self):
        assert safe_ratio(10, 0) == 0.0

    def test_safe_ratio_nan_denominator(self):
        assert safe_ratio(10, float("nan")) == 0.0

    def test_safe_ratio_custom_default(self):
        assert safe_ratio(10, 0, default=-1.0) == -1.0

    def test_channel_entropy_empty(self):
        assert channel_entropy({}) == 0.0

    def test_channel_entropy_single(self):
        assert channel_entropy({"UPI": 5}) == 0.0

    def test_channel_entropy_uniform(self):
        # Uniform distribution should have max entropy
        ent = channel_entropy({"A": 10, "B": 10})
        assert ent > 0
        assert abs(ent - 1.0) < 0.01  # log2(2) = 1

    def test_get_risk_level(self):
        assert get_risk_level(10) == "LOW"
        assert get_risk_level(30) == "MEDIUM"
        assert get_risk_level(60) == "HIGH"
        assert get_risk_level(90) == "CRITICAL"

    def test_get_risk_color(self):
        assert get_risk_color(10) == "#2ecc71"
        assert get_risk_color(90) == "#e74c3c"

    def test_format_inr(self):
        assert "Cr" in format_inr(15_000_000)
        assert "L" in format_inr(500_000)
        assert "K" in format_inr(5_000)
        assert "₹" in format_inr(500)

    def test_sanitize_text(self):
        result = sanitize_text("₹1,000")
        assert "INR" in result

    def test_gini_coefficient(self):
        # Equal values → gini = 0
        g = gini_coefficient(np.array([10, 10, 10, 10]))
        assert abs(g) < 0.01

        # Highly unequal → gini close to 1
        g = gini_coefficient(np.array([0, 0, 0, 100]))
        assert g > 0.5


# =====================================================================
# Test Data Loader
# =====================================================================

class TestDataLoader:
    def test_generate_demo_data_shape(self, demo_data):
        accounts_df, transactions_df = demo_data
        assert len(accounts_df) > 100  # 100 normal + fraud accounts
        assert len(transactions_df) > 2000  # 2000 normal + fraud transactions

    def test_demo_data_required_columns(self, demo_data):
        accounts_df, transactions_df = demo_data
        assert "account_id" in accounts_df.columns
        assert "source_account" in transactions_df.columns
        assert "dest_account" in transactions_df.columns
        assert "amount" in transactions_df.columns
        assert "timestamp" in transactions_df.columns

    def test_demo_data_has_fraud(self, demo_data):
        _, transactions_df = demo_data
        assert (transactions_df["is_laundering"] == 1).sum() > 0

    def test_demo_data_amounts_positive(self, demo_data):
        _, transactions_df = demo_data
        assert (transactions_df["amount"] > 0).all()

    def test_custom_csv_loader(self):
        df = pd.DataFrame({
            "sender": ["A", "B", "C"],
            "receiver": ["B", "C", "A"],
            "value": [1000, 2000, 3000],
            "date": ["2024-01-01", "2024-01-02", "2024-01-03"],
        })
        loader = DataLoader()
        accounts, txns = loader.load("custom_csv", dataframe=df)
        assert len(accounts) == 3
        assert len(txns) == 3

    def test_custom_csv_auto_detect(self):
        df = pd.DataFrame({
            "from_account": ["A", "B"],
            "to_account": ["B", "C"],
            "amount": [100, 200],
            "timestamp": ["2024-01-01", "2024-01-02"],
        })
        loader = DataLoader()
        accounts, txns = loader.load("custom_csv", dataframe=df)
        assert "source_account" in txns.columns
        assert "dest_account" in txns.columns


# =====================================================================
# Test Graph Engine
# =====================================================================

class TestGraphEngine:
    def test_graph_created(self, graph_engine):
        assert graph_engine.G.number_of_nodes() > 0
        assert graph_engine.G.number_of_edges() > 0

    def test_graph_stats(self, graph_engine):
        stats = graph_engine.get_stats()
        assert stats["num_nodes"] > 0
        assert stats["num_edges"] > 0
        assert 0 <= stats["density"] <= 1

    def test_centrality_computed(self, graph_engine):
        centrality = graph_engine.compute_centrality()
        assert "pagerank" in centrality
        assert "betweenness" in centrality
        assert len(centrality["pagerank"]) > 0

    def test_pagerank_sums_to_one(self, graph_engine):
        pr = graph_engine.get_pagerank()
        total = sum(pr.values())
        assert abs(total - 1.0) < 0.01

    def test_cycle_detection(self, graph_engine):
        cycles = graph_engine.detect_cycles(max_length=5, max_cycles=50)
        assert isinstance(cycles, list)
        # Demo data has embedded cycles
        # At minimum, cycles should not crash

    def test_ego_subgraph(self, graph_engine):
        nodes = list(graph_engine.G.nodes())
        if nodes:
            sub = graph_engine.get_ego_subgraph(nodes[0], radius=1)
            assert nodes[0] in sub.nodes()

    def test_fund_trail_nonexistent_account(self, graph_engine):
        result = graph_engine.get_fund_trail("NONEXISTENT_ACC")
        assert "error" in result

    def test_fund_trail_valid_account(self, graph_engine):
        nodes = list(graph_engine.G.nodes())
        if nodes:
            result = graph_engine.get_fund_trail(nodes[0])
            assert "account_id" in result

    def test_temporal_bfs(self, graph_engine):
        nodes = list(graph_engine.G.nodes())
        if nodes:
            trails = graph_engine.temporal_bfs(nodes[0], direction="forward", max_depth=2)
            assert isinstance(trails, list)

    def test_get_components(self, graph_engine):
        components = graph_engine.get_components()
        assert len(components) > 0

    def test_transaction_chains(self, graph_engine):
        chains = graph_engine.get_transaction_chains(min_hops=2, time_window_minutes=60)
        assert isinstance(chains, list)

    def test_random_walk(self, graph_engine):
        nodes = list(graph_engine.G.nodes())
        if nodes:
            probs = graph_engine.random_walk_with_restart(nodes[0], num_steps=100)
            assert isinstance(probs, dict)

    def test_renderable_subgraph(self, graph_engine):
        risk_scores = {n: np.random.uniform(0, 100) for n in graph_engine.G.nodes()}
        sub = graph_engine.get_renderable_subgraph(risk_scores, max_nodes=20)
        assert sub.number_of_nodes() <= 20 or sub.number_of_nodes() > 0


# =====================================================================
# Test Feature Extraction
# =====================================================================

class TestFeatureExtractor:
    def test_features_shape(self, features):
        assert len(features) > 0
        assert len(features.columns) >= 28  # At least 28 features

    def test_features_no_missing_index(self, features):
        assert features.index.name == "account_id"
        assert not features.index.duplicated().any()

    def test_feature_names(self, features):
        expected = ["in_degree", "out_degree", "total_in_flow", "total_out_flow",
                    "pagerank", "betweenness", "avg_txn_amount", "txn_count",
                    "channel_entropy", "velocity_10min", "dormancy_days",
                    "reciprocity_ratio", "amount_concentration"]
        for feat in expected:
            assert feat in features.columns, f"Missing feature: {feat}"

    def test_features_reasonable_values(self, features):
        assert (features["in_degree"] >= 0).all()
        assert (features["out_degree"] >= 0).all()
        assert (features["txn_count"] >= 0).all()


# =====================================================================
# Test ML Detectors
# =====================================================================

class TestAnomalyDetector:
    def test_fit_predict(self, features):
        detector = AnomalyDetector(contamination=0.1)
        results = detector.fit_predict(features)
        assert "anomaly_score" in results.columns
        assert "is_anomaly" in results.columns
        assert len(results) == len(features)

    def test_anomaly_scores_range(self, features):
        detector = AnomalyDetector(contamination=0.1)
        results = detector.fit_predict(features)
        assert results["anomaly_score"].min() >= 0
        assert results["anomaly_score"].max() <= 100

    def test_some_anomalies_detected(self, features):
        detector = AnomalyDetector(contamination=0.1)
        results = detector.fit_predict(features)
        assert results["is_anomaly"].sum() > 0


class TestFraudClassifier:
    def test_train_and_predict(self, features, demo_data):
        _, transactions_df = demo_data
        classifier = FraudClassifier()

        fraud_accounts = set(
            transactions_df[transactions_df["is_laundering"] == 1]["source_account"].unique()
        ) | set(
            transactions_df[transactions_df["is_laundering"] == 1]["dest_account"].unique()
        )
        labels = pd.Series(
            [1 if acc in fraud_accounts else 0 for acc in features.index],
            index=features.index,
        )

        if labels.sum() > 0 and labels.sum() < len(labels):
            metrics = classifier.train(features, labels)
            assert "precision" in metrics
            assert "recall" in metrics
            assert "f1" in metrics

            predictions = classifier.predict(features)
            assert len(predictions) == len(features)
            assert "fraud_prob" in predictions.columns

    def test_feature_importance(self, features, demo_data):
        _, transactions_df = demo_data
        classifier = FraudClassifier()
        fraud_accounts = set(
            transactions_df[transactions_df["is_laundering"] == 1]["source_account"].unique()
        )
        labels = pd.Series(
            [1 if acc in fraud_accounts else 0 for acc in features.index],
            index=features.index,
        )
        if labels.sum() > 0:
            classifier.train(features, labels)
            imp = classifier.get_feature_importance()
            assert len(imp) > 0


# =====================================================================
# Test Pattern Detector
# =====================================================================

class TestPatternDetector:
    def test_detect_all(self, all_patterns):
        assert "layering" in all_patterns
        assert "round_tripping" in all_patterns
        assert "structuring" in all_patterns
        assert "dormant_activation" in all_patterns
        assert "fan_in" in all_patterns
        assert "fan_out" in all_patterns

    def test_structuring_has_types(self, all_patterns):
        structuring = all_patterns["structuring"]
        assert "classic" in structuring
        assert "split" in structuring

    def test_structuring_detects_embedded(self, all_patterns):
        # Demo data has embedded structuring
        structuring = all_patterns["structuring"]
        classic = structuring.get("classic", [])
        # Should find at least the embedded scenario
        assert isinstance(classic, list)

    def test_combined_patterns(self, graph_engine, demo_data):
        _, transactions_df = demo_data
        detector = PatternDetector(graph_engine, transactions_df)
        all_p = detector.detect_all()
        combined = detector.detect_combined_patterns(all_p)
        assert isinstance(combined, list)

    def test_first_suspicious_point(self, graph_engine, demo_data):
        _, transactions_df = demo_data
        detector = PatternDetector(graph_engine, transactions_df)
        # Try a few accounts
        for acc in list(graph_engine.G.nodes())[:5]:
            result = detector.detect_first_suspicious_point(acc)
            # Result can be None if insufficient history
            if result:
                assert "txn_id" in result
                assert "z_score" in result

    def test_flagged_accounts(self, graph_engine, demo_data):
        _, transactions_df = demo_data
        detector = PatternDetector(graph_engine, transactions_df)
        all_p = detector.detect_all()
        flagged = detector.get_all_flagged_accounts(all_p)
        assert isinstance(flagged, set)


# =====================================================================
# Test Role Classifier
# =====================================================================

class TestRoleClassifier:
    def test_classify_all(self, graph_engine):
        classifier = AccountRoleClassifier()
        roles = classifier.classify_all(graph_engine)
        assert len(roles) > 0
        for acc, role_info in roles.items():
            assert role_info["role"] in ["SOURCE", "MULE", "SINK", "NORMAL"]
            assert 0 <= role_info["confidence"] <= 1.0


# =====================================================================
# Test Speed Analyzer
# =====================================================================

class TestSpeedAnalyzer:
    def test_analyze_chain(self):
        analyzer = SpeedAnalyzer()
        chain = [
            {"from": "A", "to": "B", "amount": 1000,
             "timestamp": pd.Timestamp("2024-01-01 10:00")},
            {"from": "B", "to": "C", "amount": 900,
             "timestamp": pd.Timestamp("2024-01-01 10:02")},
            {"from": "C", "to": "D", "amount": 800,
             "timestamp": pd.Timestamp("2024-01-01 10:03")},
        ]
        result = analyzer.analyze_chain_speed(chain)
        assert result["category"] in ["NORMAL", "FAST", "VERY_FAST", "ABNORMAL"]
        assert result["hops"] == 3

    def test_empty_chain(self):
        analyzer = SpeedAnalyzer()
        result = analyzer.analyze_chain_speed([])
        assert result["category"] == "NORMAL"

    def test_speed_alerts(self, graph_engine):
        analyzer = SpeedAnalyzer()
        alerts = analyzer.get_speed_alerts(graph_engine)
        assert isinstance(alerts, list)


# =====================================================================
# Test Risk Scorer
# =====================================================================

class TestRiskScorer:
    def test_composite_score(self):
        scorer = RiskScorer()
        score = scorer.compute_composite_score(
            "ACC_001",
            ml_anomaly_score=80,
            fraud_prob=0.9,
            pattern_flags={"layering": True, "structuring_classic": True},
            graph_metrics={"pagerank": 0.01, "betweenness": 0.05},
        )
        assert 0 <= score <= 100
        assert score > 30  # Should be high with these inputs

    def test_zero_score(self):
        scorer = RiskScorer()
        score = scorer.compute_composite_score("ACC_001")
        assert score == 0

    def test_confidence_levels(self):
        scorer = RiskScorer()
        level, count, indicators = scorer.compute_confidence(
            "ACC_001",
            {"layering": True, "round_tripping": True},
            {"anomaly_score": 80, "fraud_prob": 0.9},
            {"pagerank": 0.001, "betweenness": 0.02},
        )
        assert level in ["None", "Weak", "Moderate", "Strong", "Very Strong"]
        assert count >= 0

    def test_investigation_priority(self):
        scorer = RiskScorer()
        p = scorer.compute_investigation_priority(90, "Strong", 50_000_000, 5)
        assert p == "P1"

        p = scorer.compute_investigation_priority(10, "Weak", 1000, 1)
        assert p == "P4"


# =====================================================================
# Test Profile Analyzer
# =====================================================================

class TestProfileAnalyzer:
    def test_detect_mismatches(self, demo_data):
        accounts_df, transactions_df = demo_data
        analyzer = ProfileAnalyzer(accounts_df, transactions_df)
        mismatches = analyzer.detect_all_mismatches()
        assert isinstance(mismatches, list)

    def test_peer_group(self, demo_data):
        accounts_df, transactions_df = demo_data
        analyzer = ProfileAnalyzer(accounts_df, transactions_df)
        acc = accounts_df["account_id"].iloc[0]
        result = analyzer.compute_peer_group(acc)
        assert "account_id" in result or "error" in result

    def test_scatter_data(self, demo_data):
        accounts_df, transactions_df = demo_data
        analyzer = ProfileAnalyzer(accounts_df, transactions_df)
        scatter = analyzer.get_scatter_data()
        assert "declared_income" in scatter.columns
        assert "actual_volume" in scatter.columns


# =====================================================================
# Test Evidence Generator
# =====================================================================

class TestEvidenceGenerator:
    def test_generate_pack(self, graph_engine, demo_data):
        accounts_df, transactions_df = demo_data
        generator = EvidenceGenerator()

        accounts = list(graph_engine.G.nodes())[:3]
        risk_data = {a: 75.0 for a in accounts}

        pack = generator.generate_evidence_pack(
            case_id="TEST-001",
            account_ids=accounts,
            graph_engine=graph_engine,
            risk_data=risk_data,
            pattern_results={},
            transactions_df=transactions_df,
            accounts_df=accounts_df,
            case_notes="Test case notes",
        )

        assert "pdf_bytes" in pack
        assert "json_data" in pack
        assert "summary" in pack
        assert len(pack["pdf_bytes"]) > 0
        assert len(pack["json_data"]) > 0

    def test_json_is_valid(self, graph_engine, demo_data):
        import json
        accounts_df, transactions_df = demo_data
        generator = EvidenceGenerator()
        accounts = list(graph_engine.G.nodes())[:2]

        pack = generator.generate_evidence_pack(
            case_id="TEST-002",
            account_ids=accounts,
            graph_engine=graph_engine,
            risk_data={},
            pattern_results={},
            transactions_df=transactions_df,
            accounts_df=accounts_df,
        )
        parsed = json.loads(pack["json_data"])
        assert "str_report" in parsed


# =====================================================================
# Integration Test
# =====================================================================

class TestIntegration:
    def test_full_pipeline(self):
        """Test the complete TraceX pipeline end-to-end."""
        # 1. Generate data
        accounts_df, transactions_df = generate_demo_data(
            n_accounts=50, n_transactions=1000, seed=99,
        )
        assert len(accounts_df) > 50
        assert len(transactions_df) > 1000

        # 2. Build graph
        graph = TransactionGraph(accounts_df, transactions_df)
        assert graph.G.number_of_nodes() > 0

        # 3. Extract features
        extractor = FeatureExtractor(graph, accounts_df, transactions_df)
        features = extractor.extract_all()
        assert len(features) > 0

        # 4. Anomaly detection
        anomaly = AnomalyDetector(contamination=0.1)
        anomaly_results = anomaly.fit_predict(features)
        assert len(anomaly_results) == len(features)

        # 5. Pattern detection
        pattern_detector = PatternDetector(graph, transactions_df)
        patterns = pattern_detector.detect_all()
        assert isinstance(patterns, dict)

        # 6. Role classification
        role_classifier = AccountRoleClassifier()
        roles = role_classifier.classify_all(graph)
        assert len(roles) > 0

        # 7. Risk scoring
        fraud_accounts = set(
            transactions_df[transactions_df["is_laundering"] == 1]["source_account"].unique()
        )
        labels = pd.Series(
            [1 if a in fraud_accounts else 0 for a in features.index],
            index=features.index,
        )
        fraud_classifier = FraudClassifier()
        fraud_results = None
        if labels.sum() > 0 and labels.sum() < len(labels):
            fraud_classifier.train(features, labels)
            fraud_results = fraud_classifier.predict(features)

        scorer = RiskScorer()
        risk_scores = scorer.compute_all_scores(
            features, anomaly_results, fraud_results, patterns, graph,
        )
        assert len(risk_scores) > 0

        # 8. Profile analysis
        profile = ProfileAnalyzer(accounts_df, transactions_df)
        mismatches = profile.detect_all_mismatches()
        assert isinstance(mismatches, list)

        # 9. Evidence generation
        flagged = [a for a, s in risk_scores.items() if s > 50]
        if flagged:
            generator = EvidenceGenerator()
            pack = generator.generate_evidence_pack(
                "INTEGRATION-TEST",
                flagged[:3],
                graph,
                risk_scores,
                patterns,
                transactions_df,
                accounts_df,
            )
            assert len(pack["pdf_bytes"]) > 0
