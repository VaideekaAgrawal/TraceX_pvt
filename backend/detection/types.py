"""
`DetectionResult` — the one shared output type every pattern detector and
the Rule Engine (`backend/detection/rules/engine.py`) speaks, ported from
`archive/fund-flow-tracker/services/common/models.py::DetectionResult`
(dataclass shape unchanged; `timestamp` default switched from the archive's
naive `datetime.utcnow()` to a timezone-aware UTC ISO string, since this
repo's convention elsewhere is timezone-aware timestamps — a trivial,
behavior-preserving cleanup, not a detector-logic change).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class DetectionResult:
    """Output of a single detector for a single account/group.

    `detection_type` is a plain string (not the DB `DetectionType` enum) —
    detectors and the Rule Engine are pure functions with no DB dependency;
    mapping a `DetectionResult` onto an `alerts` row is Phase 4's job, not
    this phase's."""

    detection_type: str
    account_ids: list[str]
    score: float  # 0.0 - 1.0 confidence
    severity: str = "MEDIUM"  # LOW / MEDIUM / HIGH / CRITICAL
    details: dict[str, Any] = field(default_factory=dict)
    indicators: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
