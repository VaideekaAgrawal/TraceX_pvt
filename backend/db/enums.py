"""
Enums shared by the ORM layer (`db/models/`) and, later, Pydantic request/
response schemas — single source of truth for every controlled vocabulary in
`docs/DATA_SCHEMA.md` §2.

Each enum is a `str` subclass so:
  - it serializes as its plain string value in JSON/Pydantic without a custom
    encoder,
  - SQLAlchemy's `Enum` type (see `db/models/base.py::sa_enum`) can persist it
    as `TEXT` + CHECK constraint on SQLite and a native `ENUM` on Postgres
    (doc §0 logical→physical type mapping), and
  - equality/comparison against plain strings (e.g. from a CSV parse) works
    without an explicit `.value` unwrap.

Member names are written to equal their string values exactly (including
case) so `Enum(SomeEnum)`'s default storage (which persists `.name`) and
`.value` never diverge — no `values_callable` indirection needed.
"""
from __future__ import annotations

from enum import StrEnum


class Channel(StrEnum):
    """Payment channel/rail. Maps CSV `Payment Format` -> this."""

    UPI = "UPI"
    NEFT = "NEFT"
    RTGS = "RTGS"
    IMPS = "IMPS"
    net_banking = "net_banking"
    mobile_app = "mobile_app"
    ATM = "ATM"
    branch_cash = "branch_cash"
    cheque = "cheque"
    unknown = "unknown"


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class Priority(StrEnum):
    """P1 = most urgent."""

    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class AccountRole(StrEnum):
    """Per-case role, not global."""

    SOURCE = "SOURCE"
    MULE = "MULE"
    SINK = "SINK"
    NORMAL = "NORMAL"


class DetectionType(StrEnum):
    """Extend as new detectors are added (Phase 3+)."""

    layering = "layering"
    round_trip = "round_trip"
    structuring = "structuring"
    dormancy = "dormancy"
    profile_mismatch = "profile_mismatch"


class CaseStatus(StrEnum):
    """Replaces the old flat enum; matches ROADMAP Phase 4 FSM."""

    NEW = "NEW"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    AWAITING_REVIEW = "AWAITING_REVIEW"
    ESCALATED = "ESCALATED"
    CLOSED_TP = "CLOSED_TP"
    CLOSED_FP = "CLOSED_FP"
    MONITORING = "MONITORING"


class CaseLevel(StrEnum):
    """Triage (L1) vs deep investigation (L2)."""

    L1 = "L1"
    L2 = "L2"


class CaseResolution(StrEnum):
    """Set on close; drives the feedback loop.

    Note: `docs/DATA_SCHEMA.md` §2 lists a trailing `""` value alongside the
    four named ones, meant to represent "not yet resolved." That state is
    already representable by SQL NULL on every nullable column that uses this
    enum (`cases.resolution`) — Python enum members must be valid identifiers
    and can't be named `""`, and adding a synthetic sentinel member (e.g.
    `UNSET = ""`) would create two different ways to express "no resolution"
    (NULL vs `""`) in the same column. Judgment call: omit the empty-string
    member and rely on NULL for "unresolved" everywhere this enum is used.
    """

    FALSE_POSITIVE = "FALSE_POSITIVE"
    TRUE_POSITIVE_SAR = "TRUE_POSITIVE_SAR"
    ENHANCED_MONITORING = "ENHANCED_MONITORING"
    ESCALATED_COMPLIANCE = "ESCALATED_COMPLIANCE"


class UserRole(StrEnum):
    """Two roles only (RBAC decision) — do not add a third."""

    INVESTIGATOR = "INVESTIGATOR"
    ADMIN_COMPLIANCE = "ADMIN_COMPLIANCE"


class KycStatus(StrEnum):
    VERIFIED = "VERIFIED"
    PENDING = "PENDING"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"


class EddStatus(StrEnum):
    NOT_REQUIRED = "NOT_REQUIRED"
    REQUIRED = "REQUIRED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"


class EntityType(StrEnum):
    INDIVIDUAL = "INDIVIDUAL"
    BUSINESS = "BUSINESS"


class AccountStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DORMANT = "DORMANT"
    CLOSED = "CLOSED"
    FROZEN = "FROZEN"


class EvidenceType(StrEnum):
    TRANSACTION = "TRANSACTION"
    ACCOUNT = "ACCOUNT"
    GRAPH_SNAPSHOT = "GRAPH_SNAPSHOT"
    DOCUMENT = "DOCUMENT"
    PATTERN = "PATTERN"
    NOTE_REF = "NOTE_REF"


class ActorType(StrEnum):
    """`audit_log.actor_type`."""

    INVESTIGATOR = "INVESTIGATOR"
    ADMIN = "ADMIN"
    SYSTEM = "SYSTEM"
    AI = "AI"


class AiAgent(StrEnum):
    RECOMMENDATION = "RECOMMENDATION"
    COPILOT = "COPILOT"


class ReportType(StrEnum):
    SAR = "SAR"
    STR = "STR"


class ReportStatus(StrEnum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    SUBMITTED = "SUBMITTED"


class WatchEntityType(StrEnum):
    CUSTOMER = "CUSTOMER"
    ACCOUNT = "ACCOUNT"
    DEVICE = "DEVICE"
    MERCHANT = "MERCHANT"
    COMPANY = "COMPANY"


class NoteSource(StrEnum):
    """Who authored a note — copilot can write notes (decision)."""

    INVESTIGATOR = "INVESTIGATOR"
    COPILOT = "COPILOT"
