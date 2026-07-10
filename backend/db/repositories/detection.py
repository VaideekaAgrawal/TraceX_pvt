"""
Repositories for `docs/DATA_SCHEMA.md` §3.2 detection & governance tables:
`alerts`, `model_runs`, `rule_definitions`, `rl_arm_state`,
`detection_feedback`.

Scope note (per this task's instructions): `ModelRunRepository` and
`RlArmStateRepository` are persistence CRUD only — "the tables are reachable
and writable through a repo, nothing about model/bandit state can be lost on
restart because there's a durable path to it." The actual ML training and
LinUCB bandit math are Phase 3, not here. In particular this repository
deliberately does NOT enforce "exactly one active `model_run` per
model_name" (doc §3.2) as a side-effecting `activate()` that deactivates
other rows — that cross-row invariant is model-governance business logic
for the Phase 3 port to own; `update(..., active=...)` is exposed as plain
CRUD so Phase 3 can implement that invariant on top of it.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from db.enums import ActorType, CaseResolution, DetectionType, Priority, RiskLevel
from db.models.base import utcnow
from db.models.detection import (
    Alert,
    DetectionFeedback,
    ModelRun,
    RlArmState,
    RuleDefinition,
)
from db.repositories.base import UNSET, BaseRepository, collect_changes


class AlertRepository(BaseRepository[Alert]):
    model = Alert
    entity_type = "alert"
    pk_attr = "alert_id"

    def create(
        self,
        *,
        alert_id: str,
        detection_type: DetectionType,
        primary_account_id: str,
        account_ids: list[str],
        score: float,
        risk_score: float,
        severity: RiskLevel,
        priority: Priority,
        status: str,
        source: str,
        case_id: str | None = None,
        confidence: str | None = None,
        rule_ids: list[str] | None = None,
        model_run_id: str | None = None,
        created_at: datetime | None = None,
        last_seen_at: datetime | None = None,
        actor_type: ActorType,
        actor_id: str | None,
    ) -> Alert:
        now = utcnow()
        alert = Alert(
            alert_id=alert_id,
            case_id=case_id,
            detection_type=detection_type,
            primary_account_id=primary_account_id,
            account_ids=account_ids,
            score=score,
            risk_score=risk_score,
            severity=severity,
            priority=priority,
            confidence=confidence,
            status=status,
            rule_ids=rule_ids,
            model_run_id=model_run_id,
            source=source,
            created_at=created_at if created_at is not None else now,
            last_seen_at=last_seen_at if last_seen_at is not None else now,
        )
        return self._create(
            alert,
            actor_type=actor_type,
            actor_id=actor_id,
            action="alert_created",
            case_id=case_id,
        )

    def update(
        self,
        alert_id: str,
        *,
        actor_type: ActorType,
        actor_id: str | None,
        case_id: str | None = UNSET,
        severity: RiskLevel = UNSET,
        priority: Priority = UNSET,
        confidence: str | None = UNSET,
        status: str = UNSET,
        rule_ids: list[str] | None = UNSET,
        model_run_id: str | None = UNSET,
        last_seen_at: datetime = UNSET,
    ) -> Alert:
        """Generic field update — covers both status/case-assignment
        changes and "refresh `last_seen_at` on idempotent re-detection"
        (doc §3.2) as a case of setting that one field."""
        alert = self.get(alert_id)
        if alert is None:
            raise ValueError(f"alert {alert_id!r} does not exist")
        changes = collect_changes(
            case_id=case_id,
            severity=severity,
            priority=priority,
            confidence=confidence,
            status=status,
            rule_ids=rule_ids,
            model_run_id=model_run_id,
            last_seen_at=last_seen_at,
        )
        audit_case_id = changes.get("case_id", alert.case_id)
        return self._update(
            alert,
            changes,
            actor_type=actor_type,
            actor_id=actor_id,
            action="alert_updated",
            case_id=audit_case_id,
        )

    def mark_opened(self, alert_id: str, *, actor_type: ActorType, actor_id: str | None) -> None:
        """Record that an investigator opened this alert -- a legitimate
        audit-only repository call with no domain-field change: there is no
        `alerts` column tracking "opened" distinct from `status`/
        `last_seen_at`, and overloading either would corrupt their existing,
        different meanings (`status` is open/assigned/closed;
        `last_seen_at` means "last re-detected by the pipeline", doc §3.2).
        Routes through `_update()` with an empty `changes` dict rather than
        calling `append_audit_log` directly, so the single-choke-point
        invariant documented in `db/repositories/_audit.py` still holds --
        mirrors `UserRepository.record_login`'s pattern of a repo method
        whose only real purpose is producing the audited row, just with zero
        fields actually written here instead of one."""
        alert = self.get(alert_id)
        if alert is None:
            raise ValueError(f"alert {alert_id!r} does not exist")
        self._update(
            alert,
            {},
            actor_type=actor_type,
            actor_id=actor_id,
            action="alert_opened",
            case_id=alert.case_id,
        )

    def list_for_case(self, case_id: str) -> list[Alert]:
        stmt = select(Alert).where(Alert.case_id == case_id)
        return list(self.session.scalars(stmt))

    def list_unassigned(self, *, limit: int = 100) -> list[Alert]:
        """Alerts with no case yet — the alert->case assignment queue
        (Phase 4 consumes this)."""
        stmt = select(Alert).where(Alert.case_id.is_(None)).limit(limit)
        return list(self.session.scalars(stmt))

    def list_by_status(self, status: str, *, limit: int = 100) -> list[Alert]:
        stmt = select(Alert).where(Alert.status == status).limit(limit)
        return list(self.session.scalars(stmt))


class ModelRunRepository(BaseRepository[ModelRun]):
    model = ModelRun
    entity_type = "model_run"
    pk_attr = "run_id"

    def create(
        self,
        *,
        run_id: str,
        model_name: str,
        model_type: str,
        version: str,
        trained_at: datetime,
        metrics: dict,
        dataset_hash: str | None = None,
        feature_importance: dict | None = None,
        artifact_path: str | None = None,
        active: bool = False,
        actor_type: ActorType,
        actor_id: str | None,
    ) -> ModelRun:
        run = ModelRun(
            run_id=run_id,
            model_name=model_name,
            model_type=model_type,
            version=version,
            trained_at=trained_at,
            dataset_hash=dataset_hash,
            metrics=metrics,
            feature_importance=feature_importance,
            artifact_path=artifact_path,
            active=active,
        )
        return self._create(
            run, actor_type=actor_type, actor_id=actor_id, action="model_run_created"
        )

    def update(
        self,
        run_id: str,
        *,
        actor_type: ActorType,
        actor_id: str | None,
        metrics: dict = UNSET,
        feature_importance: dict | None = UNSET,
        artifact_path: str | None = UNSET,
        active: bool = UNSET,
    ) -> ModelRun:
        run = self.get(run_id)
        if run is None:
            raise ValueError(f"model_run {run_id!r} does not exist")
        changes = collect_changes(
            metrics=metrics,
            feature_importance=feature_importance,
            artifact_path=artifact_path,
            active=active,
        )
        return self._update(
            run, changes, actor_type=actor_type, actor_id=actor_id, action="model_run_updated"
        )

    def list_active(self) -> list[ModelRun]:
        stmt = select(ModelRun).where(ModelRun.active.is_(True))
        return list(self.session.scalars(stmt))

    def get_active_for_model(self, model_name: str) -> ModelRun | None:
        stmt = select(ModelRun).where(
            ModelRun.model_name == model_name, ModelRun.active.is_(True)
        )
        return self.session.scalars(stmt).first()


class RuleDefinitionRepository(BaseRepository[RuleDefinition]):
    model = RuleDefinition
    entity_type = "rule_definition"
    pk_attr = "rule_id"

    def create(
        self,
        *,
        rule_id: str,
        name: str,
        dsl: dict,
        tier: int,
        confidence: float,
        enabled: bool = True,
        created_by: str | None = None,
        actor_type: ActorType,
        actor_id: str | None,
    ) -> RuleDefinition:
        rule = RuleDefinition(
            rule_id=rule_id,
            name=name,
            dsl=dsl,
            tier=tier,
            confidence=confidence,
            enabled=enabled,
            created_by=created_by,
        )
        return self._create(
            rule, actor_type=actor_type, actor_id=actor_id, action="rule_definition_created"
        )

    def update(
        self,
        rule_id: str,
        *,
        actor_type: ActorType,
        actor_id: str | None,
        name: str = UNSET,
        dsl: dict = UNSET,
        tier: int = UNSET,
        confidence: float = UNSET,
        enabled: bool = UNSET,
    ) -> RuleDefinition:
        rule = self.get(rule_id)
        if rule is None:
            raise ValueError(f"rule_definition {rule_id!r} does not exist")
        changes = collect_changes(
            name=name, dsl=dsl, tier=tier, confidence=confidence, enabled=enabled
        )
        return self._update(
            rule,
            changes,
            actor_type=actor_type,
            actor_id=actor_id,
            action="rule_definition_updated",
        )

    def list_enabled(self) -> list[RuleDefinition]:
        stmt = select(RuleDefinition).where(RuleDefinition.enabled.is_(True))
        return list(self.session.scalars(stmt))

    def list_by_tier(self, tier: int) -> list[RuleDefinition]:
        stmt = select(RuleDefinition).where(RuleDefinition.tier == tier)
        return list(self.session.scalars(stmt))


class RlArmStateRepository(BaseRepository[RlArmState]):
    """LinUCB bandit persistence — no bandit math here, only durable
    get/upsert/list so the `A`/`b` state the algorithm needs to resume
    learning is never lost on restart (doc §3.2 reasoning)."""

    model = RlArmState
    entity_type = "rl_arm_state"
    pk_attr = "arm_id"

    def upsert(
        self,
        *,
        arm_id: str,
        a_matrix: list,
        b_vector: list,
        actor_type: ActorType,
        actor_id: str | None,
    ) -> RlArmState:
        existing = self.get(arm_id)
        now = utcnow()
        if existing is None:
            state = RlArmState(
                arm_id=arm_id, a_matrix=a_matrix, b_vector=b_vector, updated_at=now
            )
            return self._create(
                state,
                actor_type=actor_type,
                actor_id=actor_id,
                action="rl_arm_state_created",
            )
        changes = {"a_matrix": a_matrix, "b_vector": b_vector, "updated_at": now}
        return self._update(
            existing,
            changes,
            actor_type=actor_type,
            actor_id=actor_id,
            action="rl_arm_state_updated",
        )

    def list_all(self) -> list[RlArmState]:
        return self.list(limit=10_000)


class DetectionFeedbackRepository(BaseRepository[DetectionFeedback]):
    model = DetectionFeedback
    entity_type = "detection_feedback"
    pk_attr = "id"

    def create(
        self,
        *,
        case_id: str,
        verdict: CaseResolution,
        reward: float,
        created_by: str,
        alert_id: str | None = None,
        rule_ids: list[str] | None = None,
        created_at: datetime | None = None,
        actor_type: ActorType,
        actor_id: str | None,
    ) -> DetectionFeedback:
        feedback = DetectionFeedback(
            case_id=case_id,
            alert_id=alert_id,
            verdict=verdict,
            reward=reward,
            rule_ids=rule_ids,
            created_by=created_by,
            created_at=created_at if created_at is not None else utcnow(),
        )
        return self._create(
            feedback,
            actor_type=actor_type,
            actor_id=actor_id,
            action="detection_feedback_created",
            case_id=case_id,
        )

    def list_for_case(self, case_id: str) -> list[DetectionFeedback]:
        stmt = select(DetectionFeedback).where(DetectionFeedback.case_id == case_id)
        return list(self.session.scalars(stmt))

    def list_for_alert(self, alert_id: str) -> list[DetectionFeedback]:
        stmt = select(DetectionFeedback).where(DetectionFeedback.alert_id == alert_id)
        return list(self.session.scalars(stmt))
