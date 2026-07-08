"""
Data Contract Enforcement — validates data at ingestion and feature extraction.

Prevents silent pipeline failures by enforcing:
- Schema contracts (required columns, types, ranges)
- Null/NaN limits
- Amount plausibility checks
- Unique key constraints
- Positive rate sanity checks for labels
- Feature shape/finite value checks post-extraction

All violations are logged with severity. Critical violations abort the pipeline.
"""
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of a contract validation run."""
    passed: bool
    violations: List[Dict[str, str]] = field(default_factory=list)
    warnings: List[Dict[str, str]] = field(default_factory=list)
    stats: Dict[str, float] = field(default_factory=dict)

    def add_violation(self, rule: str, detail: str, severity: str = "ERROR"):
        entry = {"rule": rule, "detail": detail, "severity": severity}
        if severity == "ERROR":
            self.violations.append(entry)
            self.passed = False
        else:
            self.warnings.append(entry)
        logger.log(
            logging.ERROR if severity == "ERROR" else logging.WARNING,
            "DATA CONTRACT [%s] %s: %s", severity, rule, detail,
        )


class DataContractValidator:
    """Validates raw transaction data and accounts against strict contracts."""

    # Maximum fraction of rows with critical invariant violations before abort
    CRITICAL_VIOLATION_THRESHOLD = 0.005  # 0.5%

    # Expected transaction columns (IBM AML format)
    REQUIRED_TXN_COLUMNS = [
        "source_account", "dest_account", "amount", "timestamp",
    ]
    REQUIRED_ACC_COLUMNS = ["account_id"]

    # Amount plausibility
    MIN_AMOUNT = 0.0
    MAX_AMOUNT = 1e12  # ₹1 trillion single-txn cap

    def validate_transactions(self, txns: pd.DataFrame) -> ValidationResult:
        """Validate transaction dataframe against contracts."""
        result = ValidationResult(passed=True)
        n = len(txns)
        result.stats["total_rows"] = n

        if n == 0:
            result.add_violation("NON_EMPTY", "Transaction dataframe is empty")
            return result

        # 1. Required columns
        for col in self.REQUIRED_TXN_COLUMNS:
            if col not in txns.columns:
                result.add_violation("SCHEMA", f"Missing required column: {col}")

        if not result.passed:
            return result  # Can't continue without schema

        # 2. Null checks
        for col in self.REQUIRED_TXN_COLUMNS:
            null_count = int(txns[col].isna().sum())
            null_pct = null_count / n
            result.stats[f"null_pct_{col}"] = round(null_pct, 4)
            if null_pct > self.CRITICAL_VIOLATION_THRESHOLD:
                result.add_violation(
                    "NULLS", f"{col}: {null_count} nulls ({null_pct:.2%}) exceeds {self.CRITICAL_VIOLATION_THRESHOLD:.2%} threshold"
                )
            elif null_count > 0:
                result.add_violation(
                    "NULLS", f"{col}: {null_count} nulls ({null_pct:.2%})", severity="WARNING"
                )

        # 3. Amount plausibility
        amounts = txns["amount"]
        neg_count = int((amounts < self.MIN_AMOUNT).sum())
        extreme_count = int((amounts > self.MAX_AMOUNT).sum())
        neg_pct = neg_count / n
        extreme_pct = extreme_count / n

        result.stats["negative_amounts"] = neg_count
        result.stats["extreme_amounts"] = extreme_count
        result.stats["mean_amount"] = round(float(amounts.mean()), 2)
        result.stats["median_amount"] = round(float(amounts.median()), 2)

        if neg_pct > self.CRITICAL_VIOLATION_THRESHOLD:
            result.add_violation("AMOUNT_RANGE", f"{neg_count} negative amounts ({neg_pct:.2%})")
        elif neg_count > 0:
            result.add_violation("AMOUNT_RANGE", f"{neg_count} negative amounts", severity="WARNING")

        if extreme_pct > self.CRITICAL_VIOLATION_THRESHOLD:
            result.add_violation("AMOUNT_RANGE", f"{extreme_count} extreme amounts > {self.MAX_AMOUNT:.0e}")

        # 4. Unique key constraint — txn_id if present
        if "txn_id" in txns.columns:
            dup_count = int(txns["txn_id"].duplicated().sum())
            if dup_count > 0:
                result.add_violation("UNIQUE_KEY", f"{dup_count} duplicate txn_ids", severity="WARNING")

        # 5. Self-transfer check
        self_transfer = int((txns["source_account"] == txns["dest_account"]).sum())
        if self_transfer > 0:
            result.stats["self_transfers"] = self_transfer
            result.add_violation(
                "SELF_TRANSFER", f"{self_transfer} self-transfers detected", severity="WARNING"
            )

        # 6. Timestamp parseable
        ts = pd.to_datetime(txns["timestamp"], errors="coerce")
        unparseable = int(ts.isna().sum()) - int(txns["timestamp"].isna().sum())
        if unparseable > n * self.CRITICAL_VIOLATION_THRESHOLD:
            result.add_violation("TIMESTAMP", f"{unparseable} unparseable timestamps")

        logger.info("DATA CONTRACT: transactions validated — %d rows, passed=%s, violations=%d, warnings=%d",
                    n, result.passed, len(result.violations), len(result.warnings))
        return result

    def validate_accounts(self, accounts: pd.DataFrame) -> ValidationResult:
        """Validate accounts dataframe."""
        result = ValidationResult(passed=True)
        n = len(accounts)
        result.stats["total_accounts"] = n

        if n == 0:
            result.add_violation("NON_EMPTY", "Accounts dataframe is empty")
            return result

        for col in self.REQUIRED_ACC_COLUMNS:
            if col not in accounts.columns:
                result.add_violation("SCHEMA", f"Missing required column: {col}")

        if not result.passed:
            return result

        # Unique account_id
        dup_count = int(accounts["account_id"].duplicated().sum())
        if dup_count > 0:
            result.add_violation("UNIQUE_KEY", f"{dup_count} duplicate account_ids")

        # Null account_ids
        null_ids = int(accounts["account_id"].isna().sum())
        if null_ids > 0:
            result.add_violation("NULLS", f"{null_ids} null account_ids")

        logger.info("DATA CONTRACT: accounts validated — %d rows, passed=%s", n, result.passed)
        return result

    def validate_labels(self, labels: pd.Series, min_positive_rate: float = 0.0001,
                        max_positive_rate: float = 0.1) -> ValidationResult:
        """Validate label distribution to catch leakage or mislabeling."""
        result = ValidationResult(passed=True)
        n = len(labels)
        if n == 0:
            result.add_violation("NON_EMPTY", "Labels series is empty")
            return result

        pos = int(labels.sum())
        rate = pos / n
        result.stats["n_labels"] = n
        result.stats["n_positive"] = pos
        result.stats["positive_rate"] = round(rate, 6)

        if pos == 0:
            result.add_violation("LABEL_DISTRIBUTION", "No positive labels — model cannot train")
        elif rate < min_positive_rate:
            result.add_violation(
                "LABEL_DISTRIBUTION",
                f"Positive rate {rate:.4%} below minimum {min_positive_rate:.4%}",
                severity="WARNING"
            )
        elif rate > max_positive_rate:
            result.add_violation(
                "LABEL_DISTRIBUTION",
                f"Positive rate {rate:.4%} exceeds max {max_positive_rate:.4%} — possible label leakage",
            )

        logger.info("DATA CONTRACT: labels validated — n=%d, pos=%d (%.4f%%)", n, pos, rate * 100)
        return result

    def validate_features(self, features_df: pd.DataFrame) -> ValidationResult:
        """Validate extracted features for shape, NaN, and finite values."""
        result = ValidationResult(passed=True)
        n_rows, n_cols = features_df.shape
        result.stats["n_accounts"] = n_rows
        result.stats["n_features"] = n_cols

        if n_rows == 0:
            result.add_violation("NON_EMPTY", "Feature dataframe has zero rows")
            return result

        if n_cols == 0:
            result.add_violation("NON_EMPTY", "Feature dataframe has zero columns")
            return result

        # NaN check
        nan_count = int(features_df.isna().sum().sum())
        nan_pct = nan_count / (n_rows * n_cols)
        result.stats["nan_count"] = nan_count
        result.stats["nan_pct"] = round(nan_pct, 4)
        if nan_pct > 0.1:
            result.add_violation(
                "FEATURE_QUALITY", f"{nan_pct:.1%} NaN values in features — too many",
                severity="WARNING"
            )

        # Inf check
        numeric = features_df.select_dtypes(include=[np.number])
        inf_count = int(np.isinf(numeric.values).sum())
        if inf_count > 0:
            result.add_violation(
                "FEATURE_QUALITY", f"{inf_count} infinite values in features", severity="WARNING"
            )
            result.stats["inf_count"] = inf_count

        # Constant columns (zero variance — useless features)
        const_cols = [col for col in features_df.columns if features_df[col].nunique() <= 1]
        if const_cols:
            result.stats["constant_features"] = len(const_cols)
            result.add_violation(
                "FEATURE_QUALITY", f"{len(const_cols)} constant features: {const_cols[:5]}",
                severity="WARNING"
            )

        logger.info("DATA CONTRACT: features validated — %d accounts × %d features, passed=%s",
                    n_rows, n_cols, result.passed)
        return result

    def validate_predictions(self, probabilities: np.ndarray) -> ValidationResult:
        """Validate model output probabilities are sane."""
        result = ValidationResult(passed=True)
        n = len(probabilities)
        result.stats["n_predictions"] = n

        if n == 0:
            result.add_violation("NON_EMPTY", "Empty prediction array")
            return result

        # Finite check
        non_finite = int((~np.isfinite(probabilities)).sum())
        if non_finite > 0:
            result.add_violation("PREDICTION_QUALITY", f"{non_finite} non-finite predictions")

        # Range check [0, 1]
        out_of_range = int(((probabilities < 0) | (probabilities > 1)).sum())
        if out_of_range > 0:
            result.add_violation("PREDICTION_RANGE", f"{out_of_range} predictions outside [0,1]")

        # Distribution sanity
        pos_rate = float((probabilities > 0.5).mean())
        result.stats["predicted_positive_rate"] = round(pos_rate, 4)
        if pos_rate > 0.5:
            result.add_violation(
                "PREDICTION_DISTRIBUTION",
                f"Predicted positive rate {pos_rate:.1%} > 50% — model may be miscalibrated",
                severity="WARNING"
            )

        return result
