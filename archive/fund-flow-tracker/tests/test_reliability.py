"""
Unit tests for the TraceX pipeline reliability controls.

Tests cover:
1. Data contract validation (schema, nulls, ranges, labels)
2. Label leakage guards (source-only labeling)
3. Ensemble threshold behavior
4. Prediction sanity checks

Run with: pytest tests/test_reliability.py -v
"""
import sys
import os
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.validation.contracts import DataContractValidator


# ─── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def validator():
    return DataContractValidator()


@pytest.fixture
def valid_txns():
    """Minimal valid transaction dataframe."""
    return pd.DataFrame({
        "txn_id": [f"TXN_{i}" for i in range(100)],
        "source_account": [f"ACC_{i % 10}" for i in range(100)],
        "dest_account": [f"ACC_{(i + 5) % 10}" for i in range(100)],
        "amount": np.random.uniform(100, 50000, 100),
        "timestamp": pd.date_range("2025-01-01", periods=100, freq="h"),
        "channel": ["UPI"] * 50 + ["NEFT"] * 50,
        "is_laundering": [0] * 95 + [1] * 5,
    })


@pytest.fixture
def valid_accounts():
    """Minimal valid accounts dataframe."""
    return pd.DataFrame({
        "account_id": [f"ACC_{i}" for i in range(10)],
        "account_type": ["SAVINGS"] * 10,
        "branch_city": ["Mumbai"] * 5 + ["Delhi"] * 5,
        "occupation": ["Engineer"] * 10,
        "income_bracket": ["5-10L"] * 10,
        "declared_annual_income": [700000] * 10,
    })


# ─── Transaction Contract Tests ───────────────────────────────────────────

class TestTransactionContracts:
    def test_valid_passes(self, validator, valid_txns):
        result = validator.validate_transactions(valid_txns)
        assert result.passed is True
        assert len(result.violations) == 0

    def test_empty_fails(self, validator):
        result = validator.validate_transactions(pd.DataFrame())
        assert result.passed is False
        assert any("empty" in v["detail"].lower() for v in result.violations)

    def test_missing_column_fails(self, validator, valid_txns):
        df = valid_txns.drop(columns=["amount"])
        result = validator.validate_transactions(df)
        assert result.passed is False
        assert any("amount" in v["detail"] for v in result.violations)

    def test_excessive_nulls_fail(self, validator, valid_txns):
        df = valid_txns.copy()
        # Set >0.5% of amounts to NaN
        n_null = int(len(df) * 0.01) + 1
        df.loc[df.index[:n_null], "amount"] = np.nan
        result = validator.validate_transactions(df)
        assert result.passed is False

    def test_negative_amounts_flagged(self, validator, valid_txns):
        df = valid_txns.copy()
        n_neg = int(len(df) * 0.01) + 1
        df.loc[df.index[:n_neg], "amount"] = -100
        result = validator.validate_transactions(df)
        assert result.passed is False

    def test_extreme_amounts_flagged(self, validator, valid_txns):
        df = valid_txns.copy()
        n_ext = int(len(df) * 0.01) + 1
        df.loc[df.index[:n_ext], "amount"] = 2e12
        result = validator.validate_transactions(df)
        assert result.passed is False

    def test_self_transfers_warned(self, validator, valid_txns):
        df = valid_txns.copy()
        df.loc[0, "dest_account"] = df.loc[0, "source_account"]
        result = validator.validate_transactions(df)
        # Self-transfers are warnings, not errors
        assert any("self-transfer" in w["detail"].lower() for w in result.warnings)


# ─── Account Contract Tests ───────────────────────────────────────────────

class TestAccountContracts:
    def test_valid_passes(self, validator, valid_accounts):
        result = validator.validate_accounts(valid_accounts)
        assert result.passed is True

    def test_empty_fails(self, validator):
        result = validator.validate_accounts(pd.DataFrame())
        assert result.passed is False

    def test_duplicate_ids_fail(self, validator, valid_accounts):
        df = valid_accounts.copy()
        df.loc[1, "account_id"] = df.loc[0, "account_id"]
        result = validator.validate_accounts(df)
        assert result.passed is False


# ─── Label Contract Tests ─────────────────────────────────────────────────

class TestLabelContracts:
    def test_valid_labels(self, validator):
        labels = pd.Series([0] * 1000 + [1] * 5)
        result = validator.validate_labels(labels)
        assert result.passed is True
        assert result.stats["positive_rate"] == pytest.approx(5 / 1005, abs=1e-4)

    def test_no_positives_fail(self, validator):
        labels = pd.Series([0] * 1000)
        result = validator.validate_labels(labels)
        assert result.passed is False

    def test_too_many_positives_fail(self, validator):
        """If >10% positive rate, likely label leakage."""
        labels = pd.Series([0] * 500 + [1] * 200)
        result = validator.validate_labels(labels)
        # rate = 200/700 ≈ 28.6% > max 10%
        assert result.passed is False
        assert any("leakage" in v["detail"].lower() for v in result.violations)

    def test_empty_fails(self, validator):
        result = validator.validate_labels(pd.Series(dtype=int))
        assert result.passed is False


# ─── Feature Contract Tests ───────────────────────────────────────────────

class TestFeatureContracts:
    def test_valid_features(self, validator):
        df = pd.DataFrame(np.random.randn(100, 20), index=[f"ACC_{i}" for i in range(100)])
        result = validator.validate_features(df)
        assert result.passed is True

    def test_empty_rows_fail(self, validator):
        df = pd.DataFrame(columns=["f1", "f2"])
        result = validator.validate_features(df)
        assert result.passed is False

    def test_empty_cols_fail(self, validator):
        df = pd.DataFrame(index=["ACC_0", "ACC_1"])
        result = validator.validate_features(df)
        assert result.passed is False


# ─── Prediction Contract Tests ────────────────────────────────────────────

class TestPredictionContracts:
    def test_valid_predictions(self, validator):
        probs = np.random.uniform(0, 1, 100)
        result = validator.validate_predictions(probs)
        assert result.passed is True

    def test_nan_predictions_fail(self, validator):
        probs = np.array([0.1, 0.5, np.nan, 0.8])
        result = validator.validate_predictions(probs)
        assert result.passed is False

    def test_out_of_range_fail(self, validator):
        probs = np.array([0.1, 1.5, -0.2, 0.8])
        result = validator.validate_predictions(probs)
        assert result.passed is False

    def test_empty_fails(self, validator):
        result = validator.validate_predictions(np.array([]))
        assert result.passed is False


# ─── Label Leakage Guard Tests ────────────────────────────────────────────

class TestLabelLeakageGuard:
    """Tests that ensure source-only labeling is enforced."""

    def test_source_only_labels_no_destination(self, valid_txns):
        """_build_labels must only label source accounts of laundering txns."""
        from services.detection.service import DetectionService

        features_df = pd.DataFrame(
            index=[f"ACC_{i}" for i in range(10)],
            data={"f1": range(10)},
        )

        labels = DetectionService._build_labels(valid_txns, features_df)

        # Get actual fraud source accounts
        fraud_txns = valid_txns[valid_txns["is_laundering"] == 1]
        fraud_sources = set(fraud_txns["source_account"].unique())
        fraud_dests = set(fraud_txns["dest_account"].unique())

        # Labels should ONLY flag source accounts
        labeled_positive = set(labels[labels == 1].index)
        assert labeled_positive.issubset(fraud_sources), \
            f"Labels include non-source accounts: {labeled_positive - fraud_sources}"

        # Explicitly ensure destinations NOT in fraud_sources are NOT labeled
        innocent_dests = fraud_dests - fraud_sources
        for dest in innocent_dests:
            if dest in labels.index:
                assert labels[dest] == 0, \
                    f"Destination account {dest} was incorrectly labeled positive (LEAKAGE)"

    def test_no_laundering_column_returns_zeros(self, valid_accounts):
        """If no is_laundering column, all labels should be 0."""
        from services.detection.service import DetectionService

        txns = pd.DataFrame({"source_account": ["A"], "dest_account": ["B"], "amount": [100]})
        features = pd.DataFrame(index=["A", "B"], data={"f1": [1, 2]})
        labels = DetectionService._build_labels(txns, features)
        assert labels.sum() == 0


# ─── Ensemble Threshold Tests ─────────────────────────────────────────────

class TestEnsembleThreshold:
    """Test that FraudClassifier applies optimal threshold correctly."""

    def test_threshold_applied_in_predict(self):
        """Predictions must use optimal_threshold, not default 0.5."""
        from services.detection.ensemble import FraudClassifier
        from unittest.mock import MagicMock, patch

        clf = FraudClassifier()
        clf._fitted = True
        clf.optimal_threshold = 0.3  # Lower than default
        clf.feature_names = ["f1", "f2"]
        clf.scaler = MagicMock()
        clf.scaler.transform = lambda x: x

        # Mock model to return specific probabilities
        clf.model = MagicMock()
        clf.model.predict_proba = MagicMock(return_value=np.array([
            [0.6, 0.4],   # prob=0.4 > threshold 0.3 → should be 1
            [0.85, 0.15], # prob=0.15 < threshold 0.3 → should be 0
            [0.5, 0.5],   # prob=0.5 > threshold 0.3 → should be 1
        ]))

        features = pd.DataFrame({"f1": [1, 2, 3], "f2": [4, 5, 6]}, index=["A", "B", "C"])
        result = clf.predict(features)

        assert result.loc[result["account_id"] == "A", "fraud_pred"].iloc[0] == 1
        assert result.loc[result["account_id"] == "B", "fraud_pred"].iloc[0] == 0
        assert result.loc[result["account_id"] == "C", "fraud_pred"].iloc[0] == 1

    def test_unfitted_returns_zeros(self):
        """Unfitted classifier must return all-zero predictions safely."""
        from services.detection.ensemble import FraudClassifier

        clf = FraudClassifier()
        features = pd.DataFrame({"f1": [1, 2], "f2": [3, 4]}, index=["A", "B"])
        result = clf.predict(features)
        assert (result["fraud_pred"] == 0).all()
        assert (result["fraud_prob"] == 0.0).all()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
