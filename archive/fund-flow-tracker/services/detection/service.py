"""
Detection Service — orchestrates all 5 detectors + ML pipeline.

Responsibilities:
- Run all detectors against the current graph
- Manage Isolation Forest + XGBoost pipeline
- Produce ensemble risk scores
- Publish detection results to event bus
- Enforce confidence gate (CP-05)
- Log all progress visibly for training monitoring
"""
import logging
import time
from typing import Any, Dict, List, Optional

import pandas as pd

from infrastructure.config import config
from infrastructure.event_bus import bus, Topics
from infrastructure.health import health
from services.common.models import DetectionResult, DetectionSummary
from services.detection.features import FeatureExtractor
from services.detection.layering import LayeringDetector
from services.detection.round_trip import RoundTripDetector
from services.detection.structuring import StructuringDetector
from services.detection.dormancy import DormancyDetector
from services.detection.profile import ProfileMismatchDetector
from services.detection.fan_out import FanOutFanInDetector
from services.detection.ensemble import (
    AnomalyDetector, FraudClassifier, RoleClassifier, EnsembleScorer,
)
from services.detection.rule_engine import RuleEngine

logger = logging.getLogger(__name__)

_SERVICE = "detection"


class DetectionService:
    """Orchestrates all detection and scoring pipelines."""

    def __init__(self):
        # Kept for direct unit-testing of individual detectors; the main
        # pipeline (see run_full_pipeline step 4) goes through
        # self.rule_engine instead, which sources params from the DB-backed
        # detection_rules table rather than calling these directly.
        self.layering = LayeringDetector()
        self.round_trip = RoundTripDetector()
        self.structuring = StructuringDetector()
        self.dormancy = DormancyDetector()
        self.profile = ProfileMismatchDetector()
        self.fan_out_detector = FanOutFanInDetector()
        self.rule_engine = RuleEngine()

        self.anomaly_detector = AnomalyDetector()
        self.fraud_classifier = FraudClassifier()
        self.role_classifier = RoleClassifier()
        self.ensemble = EnsembleScorer()
        self.feature_extractor: Optional[FeatureExtractor] = None

        # Cached results
        self.features_df: Optional[pd.DataFrame] = None
        self.anomaly_results: Optional[pd.DataFrame] = None
        self.fraud_results: Optional[pd.DataFrame] = None
        self.fraud_metrics: Dict = {}
        self.detection_results: Dict[str, List[DetectionResult]] = {}
        self.roles: Dict = {}
        self.risk_scores: Dict[str, float] = {}

        health.register_service(_SERVICE)

    def run_full_pipeline(self, graph_service, accounts_df: pd.DataFrame,
                          transactions_df: pd.DataFrame) -> Dict[str, Any]:
        """
        Run the complete detection pipeline with visible progress:
        1. Feature extraction
        2. Unsupervised anomaly detection (Isolation Forest)
        3. Supervised classification (XGBoost on real labels — GPU CUDA)
        4. Pattern detection (5 detectors)
        5. Role classification
        6. Ensemble scoring
        """
        try:
            pipeline_start = time.time()
            graph_engine = graph_service.graph

            logger.info("=" * 70)
            logger.info("🚀 DETECTION PIPELINE STARTING")
            logger.info("   Accounts: %d | Transactions: %d | GPU: %s",
                        len(accounts_df), len(transactions_df),
                        "CUDA" if self.fraud_classifier.use_gpu else "CPU")
            logger.info("=" * 70)

            # ── 1. Feature extraction ──
            t0 = time.time()
            logger.info("┌─ STEP 1/6: Feature Extraction")
            self.feature_extractor = FeatureExtractor(graph_engine, accounts_df, transactions_df)
            self.features_df = self.feature_extractor.extract_all()
            logger.info("└─ STEP 1/6: ✅ %d accounts × %d features (%.1fs)",
                        len(self.features_df), len(self.features_df.columns), time.time() - t0)

            # Data contract: validate features
            try:
                from services.validation.contracts import DataContractValidator
                from services.monitoring import monitor as _monitor
                validator = DataContractValidator()
                feat_result = validator.validate_features(self.features_df.values, list(self.features_df.columns))
                if not feat_result.passed:
                    logger.warning("DATA CONTRACT: Feature validation issues: %s", feat_result.violations)
                _monitor.record_data_quality(
                    len(feat_result.violations), len(feat_result.warnings), len(self.features_df)
                )
            except Exception as e:
                logger.debug("Data contract check skipped: %s", e)

            # ── 2. Isolation Forest ──
            t0 = time.time()
            logger.info("┌─ STEP 2/6: Isolation Forest (unsupervised)")
            self.anomaly_results = self.anomaly_detector.fit_predict(self.features_df)
            n_anom = int(self.anomaly_results["is_anomaly"].sum())
            logger.info("└─ STEP 2/6: ✅ %d anomalies detected (%.1fs)", n_anom, time.time() - t0)

            # ── 3. XGBoost (train on real labels, NOT circular) ──
            t0 = time.time()
            logger.info("┌─ STEP 3/6: XGBoost Fraud Classifier (supervised, REAL labels)")
            labels = self._build_labels(transactions_df, self.features_df)
            n_pos = int(labels.sum())
            n_neg = len(labels) - n_pos
            logger.info("  ├─ Labels: %d positive (fraud), %d negative (clean)", n_pos, n_neg)

            if n_pos > 0 and n_neg > 0:
                self.fraud_metrics = self.fraud_classifier.train(self.features_df, labels)
                self.fraud_results = self.fraud_classifier.predict(self.features_df)
                logger.info("└─ STEP 3/6: ✅ Training complete (%.1fs)", time.time() - t0)
            else:
                logger.warning("└─ STEP 3/6: ⚠️ Skipped — no valid labels (pos=%d, neg=%d)", n_pos, n_neg)
                self.fraud_metrics = {}
                self.fraud_results = pd.DataFrame({
                    "account_id": self.features_df.index,
                    "fraud_prob": 0.0,
                    "fraud_pred": 0,
                })

            # ── 4. Pattern detection (Rule Engine — DB-backed rules, replacing
            #        the hardcoded 6-detector-instance list) ──
            t0 = time.time()
            logger.info("┌─ STEP 4/6: Pattern Detection (Rule Engine)")
            raw_results = self.rule_engine.run_all(graph_engine, accounts_df, transactions_df)

            # Cap each detection type at top 200 by score — prevents memory/perf blowup on large datasets
            _MAX_PER_TYPE = 200
            def _cap(results: List[DetectionResult]) -> List[DetectionResult]:
                if len(results) <= _MAX_PER_TYPE:
                    return results
                return sorted(results, key=lambda r: r.score, reverse=True)[:_MAX_PER_TYPE]

            self.detection_results = {det_type: _cap(results) for det_type, results in raw_results.items()}
            total_det = sum(len(v) for v in self.detection_results.values())
            logger.info("└─ STEP 4/6: ✅ Total %d detections across %d types (capped at %d each, %.1fs)",
                        total_det, len(self.detection_results), _MAX_PER_TYPE, time.time() - t0)
            health.increment("detections_run")

            # ── 5. Role classification ──
            t0 = time.time()
            logger.info("┌─ STEP 5/6: Role Classification")
            self.roles = self.role_classifier.classify_all(graph_engine)
            role_counts = {}
            for r in self.roles.values():
                role_counts[r["role"]] = role_counts.get(r["role"], 0) + 1
            logger.info("└─ STEP 5/6: ✅ %s (%.1fs)", role_counts, time.time() - t0)

            # ── 6. Ensemble scoring ──
            t0 = time.time()
            logger.info("┌─ STEP 6/6: Ensemble Risk Scoring")
            self.risk_scores = self.ensemble.compute_all(
                self.features_df, self.anomaly_results,
                self.fraud_results, self.detection_results,
                graph_engine,
            )

            # ── CP-05: Confidence gate ──
            low_conf_count = sum(
                1 for score in self.risk_scores.values()
                if 20 < score < 50  # Ambiguous zone
            )
            health.cp05_confidence_gate(low_conf_count, len(self.risk_scores))

            risk_dist = {
                "critical": sum(1 for s in self.risk_scores.values() if s >= 76),
                "high": sum(1 for s in self.risk_scores.values() if 51 <= s < 76),
                "medium": sum(1 for s in self.risk_scores.values() if 26 <= s < 51),
                "low": sum(1 for s in self.risk_scores.values() if s < 26),
            }
            logger.info("└─ STEP 6/6: ✅ Risk distribution: %s (%.1fs)", risk_dist, time.time() - t0)

            health.heartbeat(_SERVICE, "healthy")

            # Publish results
            bus.publish(Topics.DETECTION_RESULT, {
                "total_detections": total_det,
                "risk_scores_count": len(self.risk_scores),
            }, source_service=_SERVICE)

            total_time = time.time() - pipeline_start
            summary = {
                "accounts_analysed": len(self.features_df),
                "features_extracted": len(self.features_df.columns),
                "anomalies_flagged": n_anom,
                "fraud_metrics": self.fraud_metrics,
                "detection_counts": {k: len(v) for k, v in self.detection_results.items()},
                "roles_classified": len(self.roles),
                "risk_distribution": risk_dist,
                "total_pipeline_time_sec": round(total_time, 1),
                "device": "GPU (CUDA)" if self.fraud_classifier.use_gpu else "CPU",
            }

            logger.info("=" * 70)
            logger.info("🏁 DETECTION PIPELINE COMPLETE — %.1fs total", total_time)
            logger.info("   Anomalies: %d | Detections: %d | Avg Risk: %.1f",
                        n_anom, total_det,
                        sum(self.risk_scores.values()) / max(len(self.risk_scores), 1))
            if self.fraud_metrics:
                logger.info("   ML Metrics: F1=%.3f | AUC=%.3f | Precision=%.3f | Recall=%.3f",
                            self.fraud_metrics.get("f1", 0),
                            self.fraud_metrics.get("auc_roc", 0),
                            self.fraud_metrics.get("precision", 0),
                            self.fraud_metrics.get("recall", 0))
            logger.info("=" * 70)
            return summary

        except Exception as exc:
            health.record_error(_SERVICE, str(exc))
            logger.error("❌ DETECTION PIPELINE FAILED: %s", exc, exc_info=True)
            raise

    def get_summary(self, graph_service=None) -> DetectionSummary:
        """Public snapshot of the last completed run_full_pipeline() call —
        the one object Investigation/Evidence code should consume instead
        of reaching into risk_scores/detection_results/ensemble directly."""
        anomaly_scores: Dict[str, float] = {}
        if self.anomaly_results is not None:
            anomaly_scores = dict(zip(self.anomaly_results["account_id"], self.anomaly_results["anomaly_score"]))
        fraud_probs: Dict[str, float] = {}
        if self.fraud_results is not None:
            fraud_probs = dict(zip(self.fraud_results["account_id"], self.fraud_results["fraud_prob"]))
        centrality = graph_service.compute_centrality() if graph_service is not None else {}

        return DetectionSummary(
            risk_scores=dict(self.risk_scores),
            roles=dict(self.roles),
            detection_results=self.detection_results,
            detection_flags=self.ensemble.build_flags(self.detection_results),
            anomaly_scores=anomaly_scores,
            fraud_probabilities=fraud_probs,
            feature_importance=self.fraud_classifier.get_feature_importance(),
            centrality=centrality,
            pipeline_metrics=dict(self.fraud_metrics),
        )

    def get_account_detail(self, account_id: str, accounts_df: pd.DataFrame,
                           transactions_df: pd.DataFrame, graph_service) -> Dict[str, Any]:
        """Consolidates the per-account risk/confidence/priority computation
        that /api/accounts/{id} and /api/anomaly's queue used to each
        duplicate inline — including /api/accounts/{id} reaching directly
        into EnsembleScorer's (formerly private) flag-building method.
        Returns the raw scored values; the API layer still owns presentation
        concerns like risk_level bucketing/coloring and rounding."""
        score = self.risk_scores.get(account_id, 0)
        role_info = self.roles.get(account_id, {"role": "UNKNOWN", "confidence": 0})

        anom_score = 0.0
        if self.anomaly_results is not None:
            ar = self.anomaly_results[self.anomaly_results["account_id"] == account_id]
            anom_score = float(ar["anomaly_score"].iloc[0]) if len(ar) > 0 else 0.0

        fraud_prob = 0.0
        if self.fraud_results is not None:
            fr = self.fraud_results[self.fraud_results["account_id"] == account_id]
            fraud_prob = float(fr["fraud_prob"].iloc[0]) if len(fr) > 0 else 0.0

        centrality = graph_service.compute_centrality()
        det_flags = self.ensemble.build_flags(self.detection_results).get(account_id, {})
        conf_level, conf_count, indicators = self.ensemble.compute_confidence(
            account_id, det_flags, anom_score, fraud_prob,
            centrality["pagerank"].get(account_id, 0),
            centrality["betweenness"].get(account_id, 0),
        )

        acc_txns = transactions_df[
            (transactions_df["source_account"] == account_id) | (transactions_df["dest_account"] == account_id)
        ]
        total_amount = float(acc_txns["amount"].sum())
        n_cp = len(set(acc_txns["source_account"]) | set(acc_txns["dest_account"])) - 1
        priority = self.ensemble.compute_priority(score, conf_level, total_amount, max(n_cp, 1))

        return {
            "risk_score": score,
            "role": role_info["role"],
            "role_confidence": role_info.get("confidence", 0),
            "anomaly_score": anom_score,
            "fraud_probability": fraud_prob,
            "confidence": {"level": conf_level, "count": conf_count, "indicators": indicators},
            "priority": priority,
            "total_amount": total_amount,
            "counterparties": n_cp,
        }

    def get_all_account_summaries(self, accounts_df: pd.DataFrame,
                                  transactions_df: pd.DataFrame, graph_service) -> List[Dict[str, Any]]:
        """Vectorized equivalent of get_account_detail() for every scored
        account at once, sorted by risk descending — used by /api/anomaly's
        investigation queue. Computes centrality and detection flags once
        (not per account), matching the perf discipline the old inline
        route logic already had."""
        anom_score_map = (
            self.anomaly_results.set_index("account_id")["anomaly_score"].to_dict()
            if self.anomaly_results is not None and not self.anomaly_results.empty else {}
        )
        fraud_prob_map = (
            self.fraud_results.set_index("account_id")["fraud_prob"].to_dict()
            if self.fraud_results is not None and not self.fraud_results.empty else {}
        )
        centrality = graph_service.compute_centrality()
        all_det_flags = self.ensemble.build_flags(self.detection_results)
        branch_city_map = (
            dict(zip(accounts_df["account_id"], accounts_df.get("branch_city", "")))
            if accounts_df is not None else {}
        )

        summaries = []
        for acc_id, score in sorted(self.risk_scores.items(), key=lambda x: x[1], reverse=True):
            role_info = self.roles.get(acc_id, {"role": "NORMAL", "confidence": 0})
            anom_score = anom_score_map.get(acc_id, 0.0)
            fraud_prob = fraud_prob_map.get(acc_id, 0.0)

            det_flags = all_det_flags.get(acc_id, {})
            conf_level, conf_count, indicators = self.ensemble.compute_confidence(
                acc_id, det_flags, anom_score, fraud_prob,
                centrality["pagerank"].get(acc_id, 0),
                centrality["betweenness"].get(acc_id, 0),
            )
            total_amount = 0.0
            if transactions_df is not None:
                acc_txns = transactions_df[
                    (transactions_df["source_account"] == acc_id) | (transactions_df["dest_account"] == acc_id)
                ]
                total_amount = float(acc_txns["amount"].sum())
            priority = self.ensemble.compute_priority(score, conf_level, total_amount, 1)

            summaries.append({
                "account_id": acc_id,
                "risk_score": score,
                "role": role_info["role"],
                "priority": priority,
                "confidence_level": conf_level,
                "confidence_count": conf_count,
                "indicators": indicators,
                "anomaly_score": anom_score,
                "fraud_probability": fraud_prob,
                "total_amount": total_amount,
                "branch_city": branch_city_map.get(acc_id, ""),
            })
        return summaries

    @staticmethod
    def _build_labels(transactions_df: pd.DataFrame, features_df: pd.DataFrame) -> pd.Series:
        """Build fraud labels from is_laundering column — no circular training."""
        if "is_laundering" not in transactions_df.columns:
            return pd.Series(0, index=features_df.index)

        fraud_txns = transactions_df[transactions_df["is_laundering"] == 1]
        if len(fraud_txns) == 0:
            return pd.Series(0, index=features_df.index)

        fraud_accs = set(fraud_txns["source_account"].unique())
        # Source-only labeling: only flag initiating accounts of laundering transactions.
        # Including destination accounts adds label noise (many are innocent recipients)
        # and was shown to reduce precision from 77.8% to 4.9% — see experiment_v2 results.
        return pd.Series(
            [1 if acc in fraud_accs else 0 for acc in features_df.index],
            index=features_df.index,
        )

    def get_all_patterns(self) -> Dict[str, Any]:
        """Return pattern results in the legacy dict format for backwards compat."""
        result = {}
        for det_type, detections in self.detection_results.items():
            if det_type == "structuring":
                classic = [d.details for d in detections if d.details.get("sub_type") == "classic"]
                split = [d.details for d in detections if d.details.get("sub_type") == "split"]
                result["structuring"] = {"classic": classic, "split": split}
            else:
                result[det_type] = [d.details for d in detections]

        # Add fan_in / fan_out from graph for backwards compat
        result.setdefault("fan_in", [])
        result.setdefault("fan_out", [])
        result.setdefault("layering", [])
        result.setdefault("round_tripping", result.get("round_trip", []))
        result.setdefault("dormant_activation", result.get("dormancy", []))
        return result

    def get_detection_summary(self) -> Dict[str, int]:
        return {k: len(v) for k, v in self.detection_results.items()}
