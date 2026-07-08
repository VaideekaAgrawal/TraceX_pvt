"""
Helper utilities for TraceX — formatting, color mapping, safe math.
"""
import numpy as np
import pandas as pd
from utils.constants import RISK_LEVELS, RISK_COLORS


def safe_ratio(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Safe division avoiding ZeroDivisionError."""
    if denominator == 0 or np.isnan(denominator):
        return default
    return numerator / denominator


def channel_entropy(channel_counts: dict) -> float:
    """Shannon entropy of channel distribution."""
    if len(channel_counts) <= 1:
        return 0.0
    total = sum(channel_counts.values())
    if total == 0:
        return 0.0
    probs = [count / total for count in channel_counts.values() if count > 0]
    return -sum(p * np.log2(p) for p in probs if p > 0)


def get_risk_level(score: float) -> str:
    """Map numeric risk score to risk level string."""
    for level, (low, high) in RISK_LEVELS.items():
        if low <= score <= high:
            return level
    return "CRITICAL" if score > 75 else "LOW"


def get_risk_color(score: float) -> str:
    """Map numeric risk score to hex color."""
    level = get_risk_level(score)
    return RISK_COLORS.get(level, "#95a5a6")


def format_inr(amount: float) -> str:
    """Format amount in Indian Rupee notation with commas."""
    if amount >= 1e7:
        return f"₹{amount / 1e7:.2f} Cr"
    if amount >= 1e5:
        return f"₹{amount / 1e5:.2f} L"
    if amount >= 1e3:
        return f"₹{amount / 1e3:.1f} K"
    return f"₹{amount:,.0f}"


def sanitize_text(text: str) -> str:
    """Remove or replace characters that can break PDF generation."""
    replacements = {
        "₹": "INR ",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "--",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text.encode("latin-1", "replace").decode("latin-1")


def gini_coefficient(values: np.ndarray) -> float:
    """Compute the Gini coefficient of an array of values."""
    if len(values) == 0:
        return 0.0
    sorted_vals = np.sort(values)
    n = len(sorted_vals)
    index = np.arange(1, n + 1)
    return (2 * np.sum(index * sorted_vals) / (n * np.sum(sorted_vals)) - (n + 1) / n) if np.sum(sorted_vals) > 0 else 0.0


def time_window_counts(timestamps: pd.Series, window: str = "10min") -> pd.Series:
    """Count transactions in rolling time windows."""
    if timestamps.empty:
        return pd.Series(dtype=int)
    ts = pd.to_datetime(timestamps).sort_values()
    return ts.groupby(ts.dt.floor(window)).size()
