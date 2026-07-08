"""
Ensemble Scoring — combines all 5 detectors + unsupervised IF + supervised XGBoost.

The alert risk score is a weighted ensemble. Weights are calibrated:
- Single detector flag → lower score
- Multiple detectors agreeing → higher score (mimics experienced investigator triage)

Also includes:
- Isolation Forest (unsupervised anomaly detection — no labels needed)
- XGBoost (supervised — trained on real labelled data, NOT circular)
  - Uses CUDA GPU (RTX 3060) via tree_method='gpu_hist' when available
- Role classification (Source / Mule / Sink / Normal)
"""
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.metrics import (
    classification_report, confusion_matrix, f1_score,
    precision_score, recall_score, roc_auc_score,
)
from sklearn.preprocessing import StandardScaler
import xgboost as xgb

from infrastructure.config import config
from services.common.models import DetectionResult, EnsembleScore
from services.detection.features import safe_ratio

logger = logging.getLogger(__name__)


def _detect_gpu() -> bool:
    """Check if CUDA GPU is available for XGBoost."""
    try:
        import subprocess
        result = subprocess.run(["nvidia-smi"], capture_output=True, timeout=5)
        if result.returncode == 0:
            logger.info("🎮 NVIDIA GPU detected — will use CUDA for XGBoost")
            return True
    except Exception:
        pass
    # Fallback: try xgboost GPU directly
    try:
        test_dmat = xgb.DMatrix(np.array([[1, 2], [3, 4]]), label=[0, 1])
        params = {"tree_method": "hist", "device": "cuda", "max_depth": 2, "verbosity": 0}
        xgb.train(params, test_dmat, num_boost_round=1)
        logger.info("🎮 XGBoost CUDA verified — GPU acceleration enabled")
        return True
    except Exception as e:
        logger.warning("GPU not available for XGBoost: %s. Falling back to CPU.", e)
        return False


_GPU_AVAILABLE = _detect_gpu()


class AnomalyDetector:
    """Unsupervised anomaly detection via Isolation Forest."""

    def __init__(self, contamination: float = None, n_estimators: int = None):
        cfg = config.detection
        self.model = IsolationForest(
            contamination=contamination or cfg.if_contamination,
            n_estimators=n_estimators or cfg.if_n_estimators,
            random_state=42, n_jobs=-1,
        )
        self.scaler = StandardScaler()
        self._fitted = False

    def fit_predict(self, features_df: pd.DataFrame) -> pd.DataFrame:
        logger.info("  ├─ IsolationForest: fitting on %d accounts × %d features...",
                    len(features_df), len(features_df.columns))
        t0 = time.time()

        X = np.nan_to_num(features_df.values.astype(float), nan=0.0, posinf=1e10, neginf=-1e10)
        X_scaled = self.scaler.fit_transform(X)
        self.model.fit(X_scaled)
        self._fitted = True

        raw = self.model.score_samples(X_scaled)
        mn, mx = raw.min(), raw.max()
        scores = (1 - (raw - mn) / (mx - mn)) * 100 if mx - mn > 0 else np.zeros(len(raw))
        preds = self.model.predict(X_scaled)

        elapsed = time.time() - t0
        n_anomalies = int((preds == -1).sum())
        logger.info("  ├─ IsolationForest: done in %.1fs — %d anomalies flagged (%.1f%%)",
                    elapsed, n_anomalies, 100 * n_anomalies / max(len(preds), 1))

        return pd.DataFrame({
            "account_id": features_df.index,
            "anomaly_score": scores,
            "is_anomaly": (preds == -1).astype(int),
        })


class FraudClassifier:
    """Supervised fraud classification via XGBoost — uses CUDA GPU when available."""

    def __init__(self):
        self.model = None
        self.scaler = StandardScaler()
        self.feature_names: List[str] = []
        self.metrics: Dict = {}
        self._fitted = False
        self.use_gpu = _GPU_AVAILABLE
        self.optimal_threshold: float = 0.5   # Updated post-training via PR curve on val set

    def train(self, features_df: pd.DataFrame, labels: pd.Series,
              transactions_df: pd.DataFrame = None,
              test_size: float = 0.15) -> Dict:
        """Train with temporal split, capped spw, early stopping, threshold optimisation.

        Winning config from experiment v2 (capped_spw):
        - Temporal 70/15/15 split to prevent data leakage
        - scale_pos_weight capped (default 15, not auto ~80)
        - early_stopping_rounds=50 to prevent overfitting
        - PR-curve threshold optimisation on validation set
        """
        from sklearn.metrics import precision_recall_curve

        self.feature_names = list(features_df.columns)
        cfg = config.detection

        # Quick sanity: ensure there are enough positive examples to stratify/split
        try:
            total_pos = int(labels.sum()) if labels is not None else 0
        except Exception:
            total_pos = 0
        if total_pos < 2:
            logger.warning("  ├─ XGBoost: not enough positive labels to train (pos=%d) — skipping training", total_pos)
            self.metrics = {"precision": 0, "recall": 0, "f1": 0, "auc_roc": 0.5, "train_size": 0, "val_size": 0, "test_size": 0, "positive_rate": 0}
            return self.metrics

        # ── Temporal split when transaction timestamps available ──────────────
        if transactions_df is not None and "timestamp" in transactions_df.columns:
            logger.info("  ├─ XGBoost: using temporal split (70/15/15)")
            txns = transactions_df.copy()
            txns["timestamp"] = pd.to_datetime(txns["timestamp"], errors="coerce")
            txns = txns.sort_values("timestamp")
            acc_col = "source_account" if "source_account" in txns.columns else txns.columns[1]
            last_ts = txns.groupby(acc_col)["timestamp"].max()
            common = features_df.index.intersection(last_ts.index).intersection(labels.index)
            order = last_ts.loc[common].sort_values().index

            n = len(order)
            n_tr  = int(n * 0.70)
            n_val = int(n * 0.15)
            tr_idx  = order[:n_tr]
            val_idx = order[n_tr:n_tr + n_val]
            te_idx  = order[n_tr + n_val:]

            X_tr  = features_df.loc[tr_idx].values.astype(float)
            X_val = features_df.loc[val_idx].values.astype(float)
            X_te  = features_df.loc[te_idx].values.astype(float)
            y_tr  = labels.loc[tr_idx].values.astype(int)
            y_val = labels.loc[val_idx].values.astype(int)
            y_te  = labels.loc[te_idx].values.astype(int)
        else:
            logger.info("  ├─ XGBoost: using stratified random split (no timestamps)")
            from sklearn.model_selection import train_test_split
            common = features_df.index.intersection(labels.index)
            X_all = features_df.loc[common].values.astype(float)
            y_all = labels.loc[common].values.astype(int)
            val_size = test_size
            X_temp, X_te, y_temp, y_te = train_test_split(
                X_all, y_all, test_size=test_size, random_state=42, stratify=y_all
            )
            ratio = val_size / (1.0 - test_size)
            X_tr, X_val, y_tr, y_val = train_test_split(
                X_temp, y_temp, test_size=ratio, random_state=42, stratify=y_temp
            )

        X_tr  = np.nan_to_num(X_tr,  nan=0.0, posinf=1e10, neginf=-1e10)
        X_val = np.nan_to_num(X_val, nan=0.0, posinf=1e10, neginf=-1e10)
        X_te  = np.nan_to_num(X_te,  nan=0.0, posinf=1e10, neginf=-1e10)

        n_pos = int(y_tr.sum())
        n_neg = len(y_tr) - n_pos
        n_total = len(y_tr) + len(y_val) + len(y_te)
        logger.info("  ├─ XGBoost: %d samples total | train=%d (pos=%d, %.2f%%)",
                    n_total, len(y_tr), n_pos, 100 * n_pos / max(len(y_tr), 1))

        if len(np.unique(y_tr)) < 2:
            logger.warning("  ├─ XGBoost: only one class present — skipping training")
            self.metrics = {"precision": 0, "recall": 0, "f1": 0, "auc_roc": 0.5}
            return self.metrics

        X_tr_s  = self.scaler.fit_transform(X_tr)
        X_val_s = self.scaler.transform(X_val)
        X_te_s  = self.scaler.transform(X_te)

        logger.info("  ├─ XGBoost: train=%d, val=%d, test=%d", len(y_tr), len(y_val), len(y_te))

        cfg = config.detection
        spw = cfg.xgb_scale_pos_weight

        # GPU configuration for RTX 3060 (XGBoost 3.x: tree_method=hist + device=cuda)
        if self.use_gpu:
            logger.info("  ├─ XGBoost: 🎮 Using CUDA GPU (RTX 3060) — device=cuda")
            tree_method = "hist"
            device = "cuda"
        else:
            logger.info("  ├─ XGBoost: Using CPU — device=cpu")
            tree_method = "hist"
            device = "cpu"

        t0 = time.time()

        self.model = xgb.XGBClassifier(
            n_estimators=cfg.xgb_n_estimators,
            max_depth=cfg.xgb_max_depth,
            learning_rate=cfg.xgb_learning_rate,
            min_child_weight=cfg.xgb_min_child_weight,
            subsample=cfg.xgb_subsample,
            colsample_bytree=cfg.xgb_colsample_bytree,
            gamma=cfg.xgb_gamma,
            reg_alpha=cfg.xgb_reg_alpha,
            reg_lambda=cfg.xgb_reg_lambda,
            scale_pos_weight=spw, eval_metric="aucpr",
            early_stopping_rounds=cfg.xgb_early_stopping_rounds,
            tree_method=tree_method, device=device,
            random_state=42, n_jobs=-1,
        )

        logger.info("  ├─ XGBoost: Training up to %d estimators (depth=%d, lr=%.3f, spw=%.1f)...",
                    cfg.xgb_n_estimators, cfg.xgb_max_depth, cfg.xgb_learning_rate, spw)

        self.model.fit(
            X_tr_s, y_tr,
            eval_set=[(X_val_s, y_val)],
            verbose=50,
        )
        self._fitted = True
        elapsed = time.time() - t0
        best_iter = getattr(self.model, "best_iteration", cfg.xgb_n_estimators)
        logger.info("  ├─ XGBoost: ✅ Done in %.1fs on %s | Best iteration: %d",
                    elapsed, "GPU" if self.use_gpu else "CPU", best_iter)

        # ── Threshold optimisation on validation set (PR curve) ───────────────
        val_probs = self.model.predict_proba(X_val_s)[:, 1]
        if len(np.unique(y_val)) > 1:
            from sklearn.metrics import precision_recall_curve
            prec_arr, rec_arr, thr_arr = precision_recall_curve(y_val, val_probs)
            prec_arr, rec_arr = prec_arr[:-1], rec_arr[:-1]
            f1s = 2 * prec_arr * rec_arr / (prec_arr + rec_arr + 1e-9)
            best_idx = int(np.argmax(f1s))
            self.optimal_threshold = float(thr_arr[best_idx])
            logger.info("  ├─ Threshold optimised on val set: %.4f (P=%.3f R=%.3f F1=%.3f)",
                        self.optimal_threshold, prec_arr[best_idx], rec_arr[best_idx], f1s[best_idx])
        else:
            self.optimal_threshold = 0.5

        # ── Evaluate on test set at optimised threshold ───────────────────────
        y_prob = self.model.predict_proba(X_te_s)[:, 1]
        y_pred = (y_prob >= self.optimal_threshold).astype(int)
        y_pred_default = self.model.predict(X_te_s)

        self.metrics = {
            "precision": float(precision_score(y_te, y_pred, zero_division=0)),
            "recall": float(recall_score(y_te, y_pred, zero_division=0)),
            "f1": float(f1_score(y_te, y_pred, zero_division=0)),
            "precision_default": float(precision_score(y_te, y_pred_default, zero_division=0)),
            "recall_default": float(recall_score(y_te, y_pred_default, zero_division=0)),
            "auc_roc": float(roc_auc_score(y_te, y_prob)) if len(np.unique(y_te)) > 1 else 0.0,
            "confusion_matrix": confusion_matrix(y_te, y_pred).tolist(),
            "train_size": len(y_tr), "val_size": len(y_val), "test_size": len(y_te),
            "positive_rate": float(y_tr.mean()),
            "training_time_sec": round(elapsed, 1),
            "device": "GPU (CUDA)" if self.use_gpu else "CPU",
            "optimal_threshold": self.optimal_threshold,
            "best_iteration": best_iter,
        }
        logger.info("  ├─ XGBoost METRICS (opt thresh=%.4f): Precision=%.3f  Recall=%.3f  F1=%.3f  AUC=%.3f",
                    self.optimal_threshold, self.metrics["precision"], self.metrics["recall"],
                    self.metrics["f1"], self.metrics["auc_roc"])
        logger.info("  └─ Confusion Matrix: %s", self.metrics["confusion_matrix"])

        # Record to monitoring
        try:
            from services.monitoring import monitor
            monitor.record_training(self.metrics)
        except Exception:
            pass

        return self.metrics

    def predict(self, features_df: pd.DataFrame) -> pd.DataFrame:
        if not self._fitted or self.model is None:
            return pd.DataFrame({
                "account_id": features_df.index,
                "fraud_prob": 0.0,
                "fraud_pred": 0,
            })
        X = np.nan_to_num(features_df.values.astype(float), nan=0.0, posinf=1e10, neginf=-1e10)
        X_s = self.scaler.transform(X)
        probs = self.model.predict_proba(X_s)[:, 1]
        preds = (probs >= self.optimal_threshold).astype(int)
        return pd.DataFrame({
            "account_id": features_df.index,
            "fraud_prob": probs,
            "fraud_pred": preds,
        })

    def get_feature_importance(self) -> Dict[str, float]:
        if not self._fitted or self.model is None:
            return {}
        return dict(zip(self.feature_names, self.model.feature_importances_.tolist()))


class RoleClassifier:
    """Classify accounts by role: Source, Mule, Sink, Normal."""

    def classify_all(self, graph_engine) -> Dict[str, Dict]:
        G = graph_engine.G
        ratios = {}
        for node in G.nodes():
            in_flow = sum(d.get("amount", 0) for _, _, d in G.in_edges(node, data=True))
            out_flow = sum(d.get("amount", 0) for _, _, d in G.out_edges(node, data=True))
            total = in_flow + out_flow
            ratios[node] = {
                "in_ratio": safe_ratio(in_flow, total),
                "out_ratio": safe_ratio(out_flow, total),
                "in_degree": G.in_degree(node),
                "out_degree": G.out_degree(node),
                "total_flow": total,
                "in_flow": in_flow,
                "out_flow": out_flow,
            }

        if not ratios:
            return {}

        out_ratios = [r["out_ratio"] for r in ratios.values()]
        in_ratios = [r["in_ratio"] for r in ratios.values()]
        p75_out = np.percentile(out_ratios, 75) if out_ratios else 0.7
        p75_in = np.percentile(in_ratios, 75) if in_ratios else 0.7

        roles = {}
        for node, r in ratios.items():
            if r["total_flow"] == 0:
                role, conf = "NORMAL", 0.5
            elif r["out_ratio"] > p75_out and r["in_ratio"] < 0.3:
                role, conf = "SOURCE", min(r["out_ratio"] * 1.2, 1.0)
            elif r["in_ratio"] > p75_in and r["out_ratio"] < 0.3:
                role, conf = "SINK", min(r["in_ratio"] * 1.2, 1.0)
            elif 0.3 <= r["in_ratio"] <= 0.7 and r["in_degree"] >= 2 and r["out_degree"] >= 2:
                role, conf = "MULE", 1.0 - abs(r["in_ratio"] - 0.5)
            else:
                role, conf = "NORMAL", 0.6

            roles[node] = {
                "role": role, "confidence": round(conf, 3),
                "in_flow": round(r["in_flow"], 2), "out_flow": round(r["out_flow"], 2),
                "in_degree": r["in_degree"], "out_degree": r["out_degree"],
            }
        return roles


class EnsembleScorer:
    """Combine all detection signals into a composite risk score."""

    def compute_all(self,
                    features_df: pd.DataFrame,
                    anomaly_results: pd.DataFrame,
                    fraud_results: pd.DataFrame,
                    detection_results: Dict[str, List[DetectionResult]],
                    graph_engine) -> Dict[str, float]:
        """Compute composite risk scores for all accounts."""
        import numpy as np

        centrality = graph_engine.compute_centrality()
        pr = centrality["pagerank"]
        bc = centrality["betweenness"]

        # Build per-account detection flags
        det_flags = self.build_flags(detection_results)

        anomaly_map = dict(zip(anomaly_results["account_id"], anomaly_results["anomaly_score"]))
        fraud_map = dict(zip(fraud_results["account_id"], fraud_results["fraud_prob"]))
        # Binary fraud prediction (above optimal threshold). We gate ml_score on this
        # rather than raw probability because the PR-curve threshold is very aggressive
        # (precision=1.000 requires threshold ≈ 0.95+). Clean accounts can have raw
        # fraud_p of 0.80-0.94 yet still be correctly classified as clean. Using raw
        # probability would inflate their ml_score despite correct classification.
        fraud_pred_map = {row["account_id"]: bool(row.get("fraud_pred", 0))
                          for _, row in fraud_results.iterrows()}

        # Precompute sorted centrality arrays for percentile lookup
        pr_sorted = np.sort(np.array(list(pr.values()), dtype=float))
        bc_sorted = np.sort(np.array(list(bc.values()), dtype=float))
        n_nodes = max(len(pr_sorted), 1)

        pattern_weights = {
            "layering": 25, "round_trip": 30,
            "structuring": 20, "dormancy": 20,
            "profile_mismatch": 15, "fan_out": 22, "fan_in": 22,
        }

        scores = {}
        for acc in features_df.index:
            anomaly_s = anomaly_map.get(acc, 0)
            fraud_p = fraud_map.get(acc, 0)
            is_fraud_pred = fraud_pred_map.get(acc, False)

            # Gate ml_score on binary prediction — NOT raw probability. The optimal
            # threshold is derived from the PR curve and is typically very high (0.9+)
            # for precision-preserving configs. Raw fraud_p for clean accounts can be
            # 0.80-0.94, giving ml_score=24-28 even though XGBoost correctly classifies
            # them as clean. Gating on the binary flag prevents this inflation.
            if is_fraud_pred:
                ml_score = fraud_p * 100 * 0.3   # high-confidence fraud: use probability
            else:
                ml_score = 0.0                     # below threshold: no ML contribution

            flags = det_flags.get(acc, {})
            pattern_score = sum(pattern_weights.get(p, 10) for p, flagged in flags.items() if flagged)
            # 0.55 multiplier (was 0.40): pattern-only FN fraud accounts need enough weight
            # to score meaningfully even when XGBoost misses them (XGBoost Recall=0.65).
            pattern_score = min(pattern_score, 100) * 0.55

            # Centrality: percentile-based, only amplifies when patterns are detected.
            # Raw absolute PageRank/betweenness is graph-density-dependent and causes
            # score inversion when background accounts form a denser subgraph than fraud
            # clusters. Percentile normalises this; conditioning on patterns prevents
            # high-degree clean accounts from being falsely elevated.
            if flags:
                pr_pct = float(np.searchsorted(pr_sorted, pr.get(acc, 0), side="right")) / n_nodes
                bc_pct = float(np.searchsorted(bc_sorted, bc.get(acc, 0), side="right")) / n_nodes
                # Top 50% of centrality adds up to 25 pts each axis
                graph_score = (max(0.0, pr_pct - 0.5) * 50 +
                               max(0.0, bc_pct - 0.5) * 50) * 0.3
            else:
                graph_score = 0.0

            # Multi-signal convergence bonus: when patterns AND XGBoost probability > 0.5
            # agree, reward the corroboration.
            # Gate on fraud_p > 0.5 (not is_fraud_pred) so FN accounts with high-ish XGBoost
            # probability (0.5–0.94, below the strict PR-curve threshold) still get credit
            # for corroborating evidence. Clean accounts have no pattern flags → safe gate.
            if flags and fraud_p > 0.5:
                convergence = (fraud_p - 0.5) / 0.5   # scales 0→1 for prob 0.5→1.0
                convergence_bonus = convergence * 15   # up to 15 extra points
            else:
                convergence_bonus = 0.0

            scores[acc] = round(min(ml_score + pattern_score + graph_score + convergence_bonus, 100), 2)

        return scores

    def compute_confidence(self, account_id: str,
                           detection_flags: Dict[str, bool],
                           anomaly_score: float,
                           fraud_prob: float,
                           pagerank: float,
                           betweenness: float) -> Tuple[str, int, List[str]]:
        """Compute confidence level from independent indicator count."""
        indicators = []
        if fraud_prob > 0.5:
            indicators.append("XGBoost fraud classifier")
        for det_type, flagged in detection_flags.items():
            if flagged:
                indicators.append(f"Pattern: {det_type}")
        if pagerank > 0.005:
            indicators.append("High PageRank centrality")
        if betweenness > 0.01:
            indicators.append("High betweenness centrality")

        count = len(indicators)
        level = ("Very Strong" if count >= 4 else "Strong" if count >= 3 else
                 "Moderate" if count >= 2 else "Weak" if count >= 1 else "None")
        return level, count, indicators

    def compute_priority(self, risk_score: float, confidence: str,
                         amount: float, accounts: int) -> str:
        ps = 0
        if risk_score >= 76: ps += 40
        elif risk_score >= 51: ps += 25
        elif risk_score >= 26: ps += 10

        conf_map = {"Very Strong": 30, "Strong": 20, "Moderate": 10, "Weak": 5}
        ps += conf_map.get(confidence, 0)

        if amount >= 10_000_000: ps += 20
        elif amount >= 1_000_000: ps += 10
        if accounts >= 5: ps += 10

        # Calibrated thresholds — ensures meaningful spread across P1-P4:
        # P1: CRITICAL + Very Strong + significant amount (score ~90+)
        # P2: CRITICAL + Strong, or HIGH + Very Strong (score ~60-89)
        # P3: HIGH + Moderate, or MEDIUM + Strong (score ~30-59)
        # P4: LOW / MEDIUM with weak signals (score <30)
        if ps >= 88: return "P1"
        if ps >= 58: return "P2"
        if ps >= 28: return "P3"
        return "P4"

    @staticmethod
    def build_flags(det_results: Dict[str, List[DetectionResult]]) -> Dict[str, Dict[str, bool]]:
        flags: Dict[str, Dict[str, bool]] = {}
        for det_type, results in det_results.items():
            for r in results:
                for acc in r.account_ids:
                    flags.setdefault(acc, {})[det_type] = True
        return flags
