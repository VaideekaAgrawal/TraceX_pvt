"""
Detection-domain tuning configuration — thresholds/hyperparameters for the
pattern detectors, ML ensemble, and graph engine.

Ported from `archive/fund-flow-tracker/infrastructure/config.py`'s
`DetectionConfig`/`GraphConfig` with every threshold field unchanged
(ROADMAP Phase 3). This is detection-domain tuning config, not app-wide
settings/secrets (that's `foundation/config.py`, which only carries the one
new `model_artifact_dir` field this phase needed) — it lives here instead.

Not ported: the archive's `ensemble_weights` dict on `DetectionConfig`.
Confirmed vestigial — `EnsembleScorer.compute_all` (`services/detection/
ensemble.py`) uses its own hardcoded `pattern_weights` and never reads
`ensemble_weights` at all. Porting a dead config field would misrepresent it
as live; see `backend/detection/scoring/ensemble.py::EnsembleScorer` for the
weights that actually drive scoring.

Module-level `DEFAULT_DETECTION_CONFIG`/`DEFAULT_GRAPH_CONFIG` singletons
exist so every detector/scorer constructor can omit the `config` argument
(the archive's own ergonomics: "omit `params` to get today's exact
configured behavior") while still allowing tests/the Rule Engine's
per-primitive `params` overrides to pass an explicit instance instead of
reaching into a hidden global.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DetectionConfig:
    """Thresholds and parameters for fraud detectors + the ML ensemble."""

    # Structuring
    ctr_threshold: float = 1_000_000  # CTR reporting limit
    structuring_lower: float = 900_000
    structuring_upper: float = 999_999
    structuring_min_count: int = 3

    # Layering
    layering_min_hops: int = 3
    layering_time_window_minutes: int = 120
    layering_amount_preservation_ratio: float = 0.7
    layering_extended_window_minutes: int = 43200  # 30-day window (STACK)
    layering_extended_min_hops: int = 4

    # Fan-out / Fan-in (hub-and-spoke AML patterns)
    fan_out_min_degree: int = 3
    fan_out_time_window_days: int = 30

    # Round-trip
    round_trip_max_cycle_length: int = 12
    round_trip_max_cycles: int = 2000
    round_trip_amount_return_ratio: float = 0.85
    round_trip_batch_window_hours: int = 72

    # Dormancy
    dormancy_threshold_days: int = 180
    dormancy_burst_min_txns: int = 5
    dormancy_multiplier: float = 10.0

    # Profile mismatch
    profile_mismatch_z_threshold: float = 3.0
    profile_baseline_days: int = 90

    # Isolation Forest
    if_contamination: float = 0.05
    if_n_estimators: int = 200

    # XGBoost — best config: capped_spw (exp v2, 2026-05-18)
    # Documented result: PR-AUC=0.64, Precision=0.778, Recall=0.609,
    # F1=0.683, CV AUC=0.933 (archive/SALVAGE.md).
    xgb_n_estimators: int = 500
    xgb_max_depth: int = 6
    xgb_learning_rate: float = 0.03
    xgb_min_child_weight: int = 5
    xgb_subsample: float = 0.8
    xgb_colsample_bytree: float = 0.7
    xgb_gamma: float = 2.0
    xgb_reg_alpha: float = 0.5
    xgb_reg_lambda: float = 2.0
    xgb_scale_pos_weight: float = 15.0  # Capped (auto-tune produced ~80 -> 4.9% precision)
    xgb_early_stopping_rounds: int = 50
    xgb_optimal_threshold: float = 0.5  # Overwritten post-training via PR curve on val set
    # Descriptive only — `_build_labels` in `scoring/training.py` hardcodes
    # source-only labeling exactly as the archive's `DetectionService.
    # _build_labels` did (behavioral-fidelity-over-cleanup: not re-wired
    # into a live branch, matching the archive as-is).
    xgb_label_mode: str = "source_only"


@dataclass(frozen=True)
class GraphConfig:
    """Graph engine parameters."""

    max_renderable_nodes: int = 100
    ego_default_radius: int = 2
    chain_time_window_minutes: int = 30
    chain_min_hops: int = 3
    rwr_restart_prob: float = 0.15
    rwr_num_steps: int = 5000
    centrality_sample_k: int = 500


DEFAULT_DETECTION_CONFIG = DetectionConfig()
DEFAULT_GRAPH_CONFIG = GraphConfig()
