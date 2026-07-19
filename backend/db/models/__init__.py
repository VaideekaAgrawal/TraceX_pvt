"""
ORM models for the full `docs/DATA_SCHEMA.md` §3 schema, split by the doc's
own groupings (one module per group):

  base.py           declarative Base, mixins, ENUM type helper (§0 conventions)
  reference.py       §3.1 reference/domain:      customers, accounts, transactions
  detection.py        §3.2 detection & governance: alerts, model_runs,
                       rule_definitions, rl_arm_state, detection_feedback
  investigation.py    §3.3 investigation spine:    cases, case_accounts,
                       case_status_history, evidence, notes, reports,
                       case_feature_vector
  orchestration.py    §3.4 AI orchestration:       ai_interactions, relationships
  platform.py         §3.5 platform:               users, audit_log, watchlist,
                       ingestion_log

Every module shares the single `Base` from `base.py`, so `Base.metadata`
(imported here) is the complete schema — this is what Alembic's `env.py`
autogenerates against and what `Base.metadata.create_all()` builds in tests.

Import every model module here (even though nothing below re-exports most of
their names individually) so that merely importing `db.models` is enough to
fully populate `Base.metadata` — callers should never need to also
`import db.models.detection` etc. just to make `create_all()`/Alembic see
those tables.
"""
from db.models.base import Base
from db.models.detection import (
    Alert,
    DetectionFeedback,
    ModelRun,
    RlArmState,
    RuleDefinition,
    RuleProposal,
)
from db.models.investigation import (
    Case,
    CaseAccount,
    CaseFeatureVector,
    CaseStatusHistory,
    Evidence,
    Note,
    Report,
)
from db.models.orchestration import AiInteraction, Relationship
from db.models.platform import AuditLog, IngestionLog, User, Watchlist
from db.models.reference import Account, Customer, Transaction

__all__ = [
    "Base",
    # reference
    "Customer",
    "Account",
    "Transaction",
    # detection & governance
    "Alert",
    "ModelRun",
    "RuleDefinition",
    "RuleProposal",
    "RlArmState",
    "DetectionFeedback",
    # investigation spine
    "Case",
    "CaseAccount",
    "CaseStatusHistory",
    "Evidence",
    "Note",
    "Report",
    "CaseFeatureVector",
    # AI orchestration
    "AiInteraction",
    "Relationship",
    # platform
    "User",
    "AuditLog",
    "Watchlist",
    "IngestionLog",
]
