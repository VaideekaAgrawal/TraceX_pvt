"""
Canonical data models — shared across all services.
Every service speaks these types; no raw dicts in inter-service communication.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


# ═══════════════════════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════════════════════

class Channel(str, Enum):
    UPI = "UPI"
    NEFT = "NEFT"
    RTGS = "RTGS"
    IMPS = "IMPS"
    NET_BANKING = "net_banking"
    MOBILE_APP = "mobile_app"
    ATM = "ATM"
    BRANCH_CASH = "branch_cash"
    CHEQUE = "cheque"
    UNKNOWN = "unknown"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AccountRole(str, Enum):
    SOURCE = "SOURCE"
    MULE = "MULE"
    SINK = "SINK"
    NORMAL = "NORMAL"


class DetectionType(str, Enum):
    LAYERING = "layering"
    ROUND_TRIP = "round_trip"
    STRUCTURING = "structuring"
    DORMANCY = "dormancy"
    PROFILE_MISMATCH = "profile_mismatch"


class CaseStatus(str, Enum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    ESCALATED = "ESCALATED"
    CLOSED_TRUE_POSITIVE = "CLOSED_TP"
    CLOSED_FALSE_POSITIVE = "CLOSED_FP"


class Priority(str, Enum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class ConfidenceLevel(str, Enum):
    NONE = "None"
    WEAK = "Weak"
    MODERATE = "Moderate"
    STRONG = "Strong"
    VERY_STRONG = "Very Strong"


# ═══════════════════════════════════════════════════════════════════════════
# Core data models
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class Transaction:
    """Canonical transaction record — the atomic unit of the system."""
    txn_id: str
    timestamp: datetime
    source_account: str
    dest_account: str
    amount: float
    channel: str = "unknown"
    txn_type: str = "transfer"
    currency: str = "INR"
    is_laundering: int = 0
    from_bank: str = ""
    to_bank: str = ""
    reference_id: str = ""
    trace_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["timestamp"] = self.timestamp.isoformat() if isinstance(self.timestamp, datetime) else str(self.timestamp)
        return d


@dataclass
class Account:
    """Account entity."""
    account_id: str
    account_type: str = "savings"
    branch_city: str = ""
    occupation: str = ""
    income_bracket: str = "medium"
    declared_annual_income: float = 0.0
    kyc_tier: str = "full"
    opening_date: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ═══════════════════════════════════════════════════════════════════════════
# Detection models
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class DetectionResult:
    """Output of a single detector for a single account/group."""
    detection_type: str
    account_ids: List[str]
    score: float                # 0.0 – 1.0 confidence
    severity: str = "MEDIUM"    # LOW / MEDIUM / HIGH / CRITICAL
    details: Dict[str, Any] = field(default_factory=dict)
    indicators: List[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DetectionSummary:
    """Public snapshot of a completed detection pipeline run — the one
    object Investigation/Evidence/API code should read instead of reaching
    into DetectionService's internal attributes (risk_scores,
    detection_results, ensemble internals) or raw DataFrames directly."""
    risk_scores: Dict[str, float] = field(default_factory=dict)
    roles: Dict[str, Any] = field(default_factory=dict)
    detection_results: Dict[str, List["DetectionResult"]] = field(default_factory=dict)
    detection_flags: Dict[str, Dict[str, bool]] = field(default_factory=dict)
    anomaly_scores: Dict[str, float] = field(default_factory=dict)
    fraud_probabilities: Dict[str, float] = field(default_factory=dict)
    feature_importance: Dict[str, float] = field(default_factory=dict)
    centrality: Dict[str, Dict[str, float]] = field(default_factory=dict)
    pipeline_metrics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EnsembleScore:
    """Aggregated risk score from all detectors."""
    account_id: str
    composite_score: float      # 0 – 100
    risk_level: str
    confidence: str
    indicator_count: int
    detections: List[DetectionResult] = field(default_factory=list)
    feature_importances: Dict[str, float] = field(default_factory=dict)
    priority: str = "P4"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d


# ═══════════════════════════════════════════════════════════════════════════
# Investigation models
# ═══════════════════════════════════════════════════════════════════════════

def make_deterministic_alert_id(account_ids: List[str], detection_type: str, date_str: str) -> str:
    """Same (accounts, pattern, date) always produces the same alert_id, so
    re-detecting an already-known pattern refreshes its existing DB row
    (updating last_seen_at/risk_score) instead of creating a duplicate.
    account_ids is sorted first so the same group in a different order
    still lands on the same id. Shared by the full-pipeline path and the
    realtime lightweight-detector path so both can safely write into the
    same alerts table without id collisions producing nonsensical
    overwrites of unrelated alerts."""
    content_key = f"{','.join(sorted(str(a) for a in account_ids))}-{detection_type}-{date_str}"
    return f"ALT-{hashlib.sha256(content_key.encode()).hexdigest()[:12].upper()}"


@dataclass
class Alert:
    """System-generated alert for investigator review."""
    alert_id: str
    account_ids: List[str]
    detection_type: str
    score: float
    severity: str
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    status: str = "open"
    assigned_to: str = ""
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Case:
    """Investigation case — groups related alerts."""
    case_id: str
    alert_ids: List[str] = field(default_factory=list)
    account_ids: List[str] = field(default_factory=list)
    status: str = CaseStatus.OPEN.value
    priority: str = Priority.P3.value
    typology: str = ""
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    notes: str = ""
    evidence_hash: str = ""
    resolution: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EvidencePack:
    """FIU-IND compliant evidence package."""
    case_id: str
    str_reference: str
    pdf_bytes: bytes = b""
    json_payload: str = ""
    json_hash: str = ""
    generated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def compute_hash(self):
        """Compute SHA-256 hash of JSON payload for tamper detection (CP-08)."""
        self.json_hash = hashlib.sha256(self.json_payload.encode()).hexdigest()
        return self.json_hash


# ═══════════════════════════════════════════════════════════════════════════
# Graph models
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class GraphStats:
    """Graph-level statistics."""
    num_nodes: int = 0
    num_edges: int = 0
    num_components: int = 0
    density: float = 0.0
    avg_in_degree: float = 0.0
    avg_out_degree: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
