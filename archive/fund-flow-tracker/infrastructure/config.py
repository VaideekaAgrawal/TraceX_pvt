"""
System configuration — single source of truth for all tuneable parameters.
"""
import os
from dataclasses import dataclass, field
from typing import Dict

# OpenRouter AI integration
OPENROUTER_API_KEY: str = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL: str = os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini")


@dataclass
class DetectionConfig:
    """Thresholds and parameters for fraud detectors."""
    # Structuring
    ctr_threshold: float = 1_000_000          # ₹10 lakh CTR reporting limit
    structuring_lower: float = 900_000        # ₹9 lakh lower bound
    structuring_upper: float = 999_999        # Just below threshold
    structuring_min_count: int = 3            # Min transactions to flag

    # Layering
    layering_min_hops: int = 3
    layering_time_window_minutes: int = 120
    layering_amount_preservation_ratio: float = 0.7
    layering_extended_window_minutes: int = 43200  # 30-day window for multi-day chains (STACK)
    layering_extended_min_hops: int = 4           # Stricter filter for extended window

    # Fan-out / Fan-in (hub-and-spoke AML patterns)
    fan_out_min_degree: int = 3                   # Min unique counterparties; IBM patterns go to 3+
    fan_out_time_window_days: int = 30            # Sliding window; IBM HI-Small spans 30 days

    # Round-trip
    round_trip_max_cycle_length: int = 12      # IBM CYCLE patterns go up to 12 hops
    round_trip_max_cycles: int = 2000          # More budget for longer cycles
    round_trip_amount_return_ratio: float = 0.85
    round_trip_batch_window_hours: int = 72

    # Dormancy
    dormancy_threshold_days: int = 180
    dormancy_burst_min_txns: int = 5
    dormancy_multiplier: float = 10.0  # Burst > 10× historical average

    # Profile mismatch
    profile_mismatch_z_threshold: float = 3.0
    profile_baseline_days: int = 90

    # Isolation Forest
    if_contamination: float = 0.05
    if_n_estimators: int = 200

    # XGBoost — best config: capped_spw (exp v2, 2026-05-18)
    # Results: PR-AUC=0.64, Precision=0.778, Recall=0.609, F1=0.683, CV AUC=0.933
    xgb_n_estimators: int = 500
    xgb_max_depth: int = 6
    xgb_learning_rate: float = 0.03
    xgb_min_child_weight: int = 5
    xgb_subsample: float = 0.8
    xgb_colsample_bytree: float = 0.7
    xgb_gamma: float = 2.0
    xgb_reg_alpha: float = 0.5
    xgb_reg_lambda: float = 2.0
    xgb_scale_pos_weight: float = 15.0   # Capped (was auto ~80 causing 4.9% precision)
    xgb_early_stopping_rounds: int = 50
    xgb_optimal_threshold: float = 0.5   # Updated post-training via PR curve on val set
    xgb_label_mode: str = "source_only"  # Only source accounts of laundering txns labeled +

    # Ensemble weights
    ensemble_weights: Dict[str, float] = field(default_factory=lambda: {
        "layering": 0.20,
        "round_trip": 0.25,
        "structuring": 0.20,
        "dormancy": 0.15,
        "profile": 0.20,
    })


@dataclass
class GraphConfig:
    """Graph engine parameters."""
    max_renderable_nodes: int = 100
    ego_default_radius: int = 2
    chain_time_window_minutes: int = 30
    chain_min_hops: int = 3
    rwr_restart_prob: float = 0.15
    rwr_num_steps: int = 5000
    centrality_sample_k: int = 500


@dataclass
class HealthConfig:
    """Health monitoring parameters."""
    synthetic_ping_interval_sec: int = 600    # Every 10 minutes
    graph_parity_check_interval_sec: int = 300  # Every 5 minutes
    confidence_gate_threshold: float = 0.6
    dlq_alert_threshold: int = 50


@dataclass
class SystemConfig:
    """Top-level system configuration."""
    detection: DetectionConfig = field(default_factory=DetectionConfig)
    graph: GraphConfig = field(default_factory=GraphConfig)
    health: HealthConfig = field(default_factory=HealthConfig)
    data_dir: str = "data"
    log_level: str = "INFO"


# Module-level singleton
config = SystemConfig()
