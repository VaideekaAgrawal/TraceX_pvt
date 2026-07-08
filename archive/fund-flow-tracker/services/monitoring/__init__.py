"""
Monitoring & Observability — metrics collection and alerting rules.

Provides:
- Real-time pipeline metrics (model performance, prediction distribution, data quality)
- Drift detection (compare live stats to training baseline)
- Alerting rules with severity levels
- Metrics exposed via /api/metrics endpoint

Baseline values are loaded from experiments/results_v2.json.
"""
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

RESULTS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "experiments", "results_v2.json"
)


@dataclass
class Alert:
    """A triggered alert."""
    severity: str  # P1, P2, P3
    rule: str
    message: str
    timestamp: float = field(default_factory=time.time)
    acknowledged: bool = False


class MetricsCollector:
    """Collects and serves pipeline metrics for observability."""

    def __init__(self):
        self.metrics: Dict[str, float] = {}
        self.alerts: List[Alert] = []
        self.baseline: Dict[str, float] = {}
        self._load_baseline()

    def _load_baseline(self):
        """Load training baseline from experiment results."""
        if os.path.exists(RESULTS_PATH):
            try:
                with open(RESULTS_PATH, "r") as f:
                    data = json.load(f)
                # Use capped_spw experiment as baseline
                for exp in data.get("experiments", []):
                    if exp["name"] == "capped_spw":
                        self.baseline = {
                            "auc_roc": exp.get("auc_roc", 0),
                            "pr_auc": exp.get("pr_auc", 0),
                            "precision": exp.get("precision_opt", 0),
                            "recall": exp.get("recall_opt", 0),
                            "f1": exp.get("f1_opt", 0),
                            "positive_rate_train": exp.get("n_pos_train", 0) / max(exp.get("train_size", 1), 1),
                            "optimal_threshold": exp.get("opt_threshold", 0.5),
                        }
                        break
                cv = data.get("cross_validation", {})
                if cv:
                    self.baseline["cv_auc_mean"] = cv.get("auc_mean", 0)
                    self.baseline["cv_auc_std"] = cv.get("auc_std", 0)
                logger.info("MONITORING: Loaded baseline metrics from experiments/results_v2.json")
            except Exception as e:
                logger.warning("MONITORING: Failed to load baseline: %s", e)

    def record_training(self, metrics: Dict):
        """Record metrics after a training run."""
        self.metrics["model_auc_roc"] = metrics.get("auc_roc", 0)
        self.metrics["model_precision"] = metrics.get("precision", 0)
        self.metrics["model_recall"] = metrics.get("recall", 0)
        self.metrics["model_f1"] = metrics.get("f1", 0)
        self.metrics["model_threshold"] = metrics.get("optimal_threshold", 0.5)
        self.metrics["model_train_size"] = metrics.get("train_size", 0)
        self.metrics["model_test_size"] = metrics.get("test_size", 0)
        self.metrics["model_positive_rate"] = metrics.get("positive_rate", 0)
        self.metrics["model_training_time_sec"] = metrics.get("training_time_sec", 0)
        self.metrics["model_device"] = 1 if "GPU" in str(metrics.get("device", "")) else 0
        self.metrics["last_training_timestamp"] = time.time()

        # Check for regressions vs baseline
        self._check_regression("auc_roc", metrics.get("auc_roc", 0), threshold=0.05)
        self._check_regression("precision", metrics.get("precision", 0), threshold=0.1)

    def record_inference(self, n_predictions: int, positive_rate: float, mean_prob: float):
        """Record inference-time metrics."""
        self.metrics["inference_count"] = self.metrics.get("inference_count", 0) + n_predictions
        self.metrics["inference_positive_rate"] = positive_rate
        self.metrics["inference_mean_probability"] = mean_prob
        self.metrics["last_inference_timestamp"] = time.time()

        # Alert on positive rate drift
        baseline_rate = self.baseline.get("positive_rate_train", 0)
        if baseline_rate > 0 and positive_rate > 0:
            drift = abs(positive_rate - baseline_rate) / baseline_rate
            self.metrics["positive_rate_drift_pct"] = round(drift * 100, 2)
            if drift > 0.5:  # >50% deviation
                self._trigger_alert(
                    "P1", "POSITIVE_RATE_DRIFT",
                    f"Live positive rate ({positive_rate:.4f}) deviates {drift:.0%} from baseline ({baseline_rate:.4f})"
                )

    def record_data_quality(self, violations: int, warnings: int, total_rows: int):
        """Record data quality metrics."""
        self.metrics["data_schema_violations"] = violations
        self.metrics["data_warnings"] = warnings
        self.metrics["data_total_rows"] = total_rows
        self.metrics["last_validation_timestamp"] = time.time()

        if violations > 0:
            self._trigger_alert(
                "P2", "DATA_SCHEMA_VIOLATION",
                f"{violations} critical data contract violations in {total_rows} rows"
            )

    def record_prediction_distribution(self, probabilities):
        """Record prediction distribution histogram."""
        import numpy as np
        hist, _ = np.histogram(probabilities, bins=10, range=(0, 1))
        self.metrics["prediction_hist"] = hist.tolist()
        self.metrics["prediction_mean"] = float(np.mean(probabilities))
        self.metrics["prediction_std"] = float(np.std(probabilities))
        self.metrics["prediction_p95"] = float(np.percentile(probabilities, 95))

    def _check_regression(self, metric_name: str, value: float, threshold: float):
        """Check if metric regressed beyond threshold from baseline."""
        baseline_val = self.baseline.get(metric_name, 0)
        if baseline_val > 0 and value > 0:
            drop = (baseline_val - value) / baseline_val
            if drop > threshold:
                self._trigger_alert(
                    "P1", f"METRIC_REGRESSION_{metric_name.upper()}",
                    f"{metric_name} dropped {drop:.1%} from baseline {baseline_val:.4f} → {value:.4f}"
                )

    def _trigger_alert(self, severity: str, rule: str, message: str):
        """Trigger an alert."""
        alert = Alert(severity=severity, rule=rule, message=message)
        self.alerts.append(alert)
        log_fn = logger.critical if severity == "P1" else logger.warning
        log_fn("🚨 ALERT [%s] %s: %s", severity, rule, message)

    def get_metrics(self) -> Dict:
        """Get all current metrics."""
        return {
            "metrics": self.metrics,
            "baseline": self.baseline,
            "alerts": [
                {"severity": a.severity, "rule": a.rule, "message": a.message,
                 "timestamp": a.timestamp, "acknowledged": a.acknowledged}
                for a in self.alerts[-50:]  # Last 50 alerts
            ],
            "alert_count": len(self.alerts),
            "unacknowledged_p1": sum(1 for a in self.alerts if a.severity == "P1" and not a.acknowledged),
        }

    def acknowledge_alert(self, index: int) -> bool:
        """Acknowledge an alert by index."""
        if 0 <= index < len(self.alerts):
            self.alerts[index].acknowledged = True
            return True
        return False


# Singleton instance
monitor = MetricsCollector()
