"""
Model Explainability — SHAP-based feature importance for XGBoost predictions.

Provides:
- Global feature importance (which features drive fraud detection)
- Local explanation (why THIS account was flagged)
- Regulatory-friendly reports for compliance
"""
import logging
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Optional SHAP import — gracefully degrade if not installed
try:
    import shap
    SHAP_AVAILABLE = True
except ImportError:
    SHAP_AVAILABLE = False
    logger.warning("SHAP not installed — explainability features disabled. Install with: pip install shap")


class ModelExplainer:
    """Explain XGBoost fraud predictions using SHAP values."""

    def __init__(self, model, feature_names: List[str]):
        self.model = model
        self.feature_names = feature_names
        self._explainer = None
        self._global_importance = None

    def _ensure_explainer(self, X_background: np.ndarray = None):
        """Initialize SHAP TreeExplainer with background data."""
        if not SHAP_AVAILABLE:
            return False
        if self._explainer is None:
            if X_background is not None:
                self._explainer = shap.TreeExplainer(self.model, X_background)
            else:
                self._explainer = shap.TreeExplainer(self.model)
        return True

    def explain_global(self, X: np.ndarray) -> Dict[str, float]:
        """
        Compute global feature importance using mean |SHAP values|.
        
        Returns dict mapping feature_name → importance score.
        """
        if not self._ensure_explainer():
            # Fallback to XGBoost built-in importance
            if hasattr(self.model, 'feature_importances_'):
                return dict(zip(self.feature_names, self.model.feature_importances_))
            return {}

        shap_values = self._explainer.shap_values(X)
        # For binary classification, shap_values may be a list
        if isinstance(shap_values, list):
            shap_values = shap_values[1]  # Positive class
        
        mean_abs = np.abs(shap_values).mean(axis=0)
        self._global_importance = dict(zip(self.feature_names, mean_abs))
        return self._global_importance

    def explain_account(self, account_features: np.ndarray, account_id: str) -> Dict[str, Any]:
        """
        Explain why a specific account was flagged.
        
        Returns:
            - risk_drivers: top features pushing score up
            - protective_factors: features keeping score down
            - shap_values: raw SHAP values for all features
        """
        if not self._ensure_explainer():
            return {"error": "SHAP not available", "account_id": account_id}

        if account_features.ndim == 1:
            account_features = account_features.reshape(1, -1)

        shap_values = self._explainer.shap_values(account_features)
        if isinstance(shap_values, list):
            shap_values = shap_values[1]
        
        values = shap_values[0]
        
        # Sort by absolute impact
        sorted_idx = np.argsort(np.abs(values))[::-1]
        
        # Top risk drivers (positive SHAP = increases fraud probability)
        risk_drivers = []
        protective_factors = []
        
        for idx in sorted_idx[:10]:  # Top 10 features
            feature_name = self.feature_names[idx]
            shap_val = values[idx]
            feature_val = account_features[0, idx]
            
            entry = {
                "feature": feature_name,
                "value": round(float(feature_val), 4),
                "impact": round(float(shap_val), 4),
            }
            
            if shap_val > 0:
                risk_drivers.append(entry)
            else:
                protective_factors.append(entry)

        return {
            "account_id": account_id,
            "risk_drivers": risk_drivers,
            "protective_factors": protective_factors,
            "shap_values": dict(zip(self.feature_names, values.tolist())),
        }

    def generate_explanation_report(self, account_id: str, 
                                    account_features: np.ndarray,
                                    risk_score: float) -> str:
        """
        Generate a human-readable explanation for compliance/audit.
        
        Example output:
        "Account ACC_12345 (Risk Score: 78.3) flagged primarily due to:
         1. velocity_24h (value: 47) — 15 transactions in 24 hours (impact: +0.23)
         2. counterparty_entropy (value: 0.12) — Low diversity in recipients (impact: +0.18)
         ..."
        """
        explanation = self.explain_account(account_features, account_id)
        
        if "error" in explanation:
            return f"Unable to explain: {explanation['error']}"
        
        lines = [
            f"Account {account_id} (Risk Score: {risk_score:.1f}) flagged primarily due to:",
            ""
        ]
        
        for i, driver in enumerate(explanation["risk_drivers"][:5], 1):
            feature = driver["feature"]
            value = driver["value"]
            impact = driver["impact"]
            
            # Human-readable feature descriptions
            descriptions = {
                "velocity_24h": f"{value:.0f} transactions in 24 hours",
                "counterparty_entropy": f"{'Low' if value < 1 else 'Normal'} diversity in counterparties",
                "night_ratio": f"{value*100:.0f}% transactions at night (10PM-6AM)",
                "structuring_count": f"{value:.0f} transactions near ₹10L threshold",
                "avg_amount": f"Average transaction ₹{value:,.0f}",
                "pagerank": f"High network centrality (hub account)",
                "betweenness": f"Account bridges many other accounts",
                "in_out_ratio": f"{'Receiving' if value > 1 else 'Sending'}-heavy account",
                "dormancy_days": f"Inactive for {value:.0f} days before burst",
                "income_volume_ratio": f"Transaction volume {value:.1f}× declared income",
            }
            
            desc = descriptions.get(feature, f"{feature}: {value}")
            lines.append(f"  {i}. {feature} — {desc} (impact: +{impact:.2f})")
        
        if explanation["protective_factors"]:
            lines.append("")
            lines.append("Factors reducing risk:")
            for factor in explanation["protective_factors"][:3]:
                lines.append(f"  - {factor['feature']} (impact: {factor['impact']:.2f})")
        
        return "\n".join(lines)


# Singleton for use across services
_explainer: Optional[ModelExplainer] = None


def get_explainer() -> Optional[ModelExplainer]:
    return _explainer


def set_explainer(model, feature_names: List[str]):
    global _explainer
    _explainer = ModelExplainer(model, feature_names)
    logger.info("Model explainer initialized with %d features", len(feature_names))
