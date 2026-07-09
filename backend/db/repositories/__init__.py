"""
Repository layer — one class per aggregate/table-group, mirroring
`db/models/`'s own grouping (`docs/DATA_SCHEMA.md` §3). Every repository
takes a `sqlalchemy.orm.Session` (from `db.session`) and exposes typed
CRUD methods; every create/update/soft-delete method also appends the
matching `audit_log` row in the same Session flush (`db.repositories._audit`,
doc §0's audit invariant — "Repositories enforce this, not callers").

    reference.py       -> CustomerRepository, AccountRepository,
                           TransactionRepository
    detection.py        -> AlertRepository, ModelRunRepository,
                            RuleDefinitionRepository, RlArmStateRepository,
                            DetectionFeedbackRepository
    investigation.py    -> CaseRepository, CaseAccountRepository,
                            CaseStatusHistoryRepository, EvidenceRepository,
                            NoteRepository, ReportRepository,
                            CaseFeatureVectorRepository
    orchestration.py    -> AiInteractionRepository, RelationshipRepository
    platform.py          -> UserRepository, AuditLogRepository,
                            WatchlistRepository, IngestionLogRepository

Since there's no auth yet (Phase 2), every write method takes explicit
`actor_type: ActorType, actor_id: str | None` parameters rather than pulling
them from a request context that doesn't exist yet — later-phase callers
supply them.
"""
from db.repositories.detection import (
    AlertRepository,
    DetectionFeedbackRepository,
    ModelRunRepository,
    RlArmStateRepository,
    RuleDefinitionRepository,
)
from db.repositories.investigation import (
    CaseAccountRepository,
    CaseFeatureVectorRepository,
    CaseRepository,
    CaseStatusHistoryRepository,
    EvidenceRepository,
    NoteRepository,
    ReportRepository,
)
from db.repositories.orchestration import AiInteractionRepository, RelationshipRepository
from db.repositories.platform import (
    AuditLogRepository,
    IngestionLogRepository,
    UserRepository,
    WatchlistRepository,
)
from db.repositories.reference import (
    AccountRepository,
    CustomerRepository,
    TransactionRepository,
)

__all__ = [
    # reference
    "CustomerRepository",
    "AccountRepository",
    "TransactionRepository",
    # detection & governance
    "AlertRepository",
    "ModelRunRepository",
    "RuleDefinitionRepository",
    "RlArmStateRepository",
    "DetectionFeedbackRepository",
    # investigation spine
    "CaseRepository",
    "CaseAccountRepository",
    "CaseStatusHistoryRepository",
    "EvidenceRepository",
    "NoteRepository",
    "ReportRepository",
    "CaseFeatureVectorRepository",
    # AI orchestration
    "AiInteractionRepository",
    "RelationshipRepository",
    # platform
    "UserRepository",
    "AuditLogRepository",
    "WatchlistRepository",
    "IngestionLogRepository",
]
