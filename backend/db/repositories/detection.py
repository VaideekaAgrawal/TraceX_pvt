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

from datetime import UTC, datetime
from typing import Any, ClassVar

from sqlalchemy import func, select

from db.enums import ActorType, CaseResolution, DetectionType, Priority, RiskLevel
from db.models.base import utcnow
from db.models.detection import (
    Alert,
    DetectionFeedback,
    ModelRun,
    RlArmState,
    RuleDefinition,
)
from db.models.investigation import Case
from db.repositories.base import UNSET, BaseRepository, collect_changes


class AlertRepository(BaseRepository[Alert]):
    model = Alert
    entity_type = "alert"
    pk_attr = "alert_id"

    #: `sort=` values `list_filtered`/the `/alerts` route accept, mapped to
    #: the SQLAlchemy ORDER BY expression each represents. Module-level
    #: `ALERT_SORT_KEYS` below is the public surface for callers outside
    #: this module (ROADMAP Phase 14) -- reaching into this "private"
    #: class attribute directly from `api.routes.alerts` would work but
    #: defeats the point of naming it private.
    _LIST_SORTS: ClassVar[dict[str, Any]] = {
        "risk_score_desc": Alert.risk_score.desc(),
        "risk_score_asc": Alert.risk_score.asc(),
        "created_at_desc": Alert.created_at.desc(),
        "created_at_asc": Alert.created_at.asc(),
        "priority_asc": Alert.priority.asc(),
        "priority_desc": Alert.priority.desc(),
    }

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
        score: float = UNSET,
        risk_score: float = UNSET,
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
        (doc §3.2) as a case of setting that one field.

        `score`/`risk_score` are accepted here (code-review finding,
        Phase 4: they weren't, so a re-detected alert's row went stale on
        those two columns even though both are freshly recomputed for
        every detection result, including re-detections) so a refresh can
        actually refresh the composite risk number, not just the metadata
        around it.
        """
        alert = self.get(alert_id)
        if alert is None:
            raise ValueError(f"alert {alert_id!r} does not exist")
        changes = collect_changes(
            case_id=case_id,
            score=score,
            risk_score=risk_score,
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
        """Ordered by `risk_score` descending (code-review finding,
        Phase 4: `investigation.cases.close_case` picks `[0]` as the
        primary alert to attribute a verdict to -- that needs to be the
        highest-risk alert, not an incidental DB-insertion-order first
        row)."""
        stmt = (
            select(Alert)
            .where(Alert.case_id == case_id)
            .order_by(Alert.risk_score.desc())
        )
        return list(self.session.scalars(stmt))

    def list_for_primary_account(self, account_id: str, *, limit: int = 100) -> list[Alert]:
        """Alerts where `account_id` is the *primary* account -- deliberately
        narrower than a full `account_ids` membership search (ROADMAP Phase
        5: `investigation.previous_alerts` documents this same narrowing --
        network-wide "any connected account" reach is Phase 6/7's Previous
        Alert & Case History feature, not this one). Ordered descending by
        `created_at` (most recent first) before `.limit()` (code-review
        finding, Phase 5: ascending order meant an account with more than
        `limit` alerts had its *oldest* ones kept and its most recent
        activity silently dropped -- backwards for both callers, which want
        recent/prior-SAR signal, not ancient history). Callers that want
        chronological display order (e.g. `investigation.previous_alerts`'s
        `risk_trend`) re-sort ascending themselves rather than relying on
        this method's order."""
        stmt = (
            select(Alert)
            .where(Alert.primary_account_id == account_id)
            .order_by(Alert.created_at.desc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt))

    def list_for_primary_accounts(
        self, account_ids: list[str], *, limit: int = 1000
    ) -> list[Alert]:
        """Batched form of `list_for_primary_account` -- one `IN (...)`
        query for many accounts instead of one query per account
        (code-review finding, Phase 6: `investigation.graph_filters.
        annotate_nodes` was calling `list_for_primary_account` once per
        ego-graph node -- hundreds of sequential round-trips at radius=4 on
        a real hub account; confirmed live at 325ms for that one endpoint
        vs. 6-13ms for every other new L2 endpoint). Mirrors
        `AccountRepository.list_by_ids`'s plain-`IN`-clause batching
        precedent, NOT `list_for_primary_account`'s per-account cap: `limit`
        here is a single OVERALL cap across every requested account, not a
        per-account one. Correct for `annotate_nodes`'s use (a boolean "does
        this account have any prior SAR-resolved alert" check over a
        bounded ego-graph node set, where per-account recency ordering
        doesn't change the answer) -- NOT a drop-in replacement for a
        caller that specifically needs each account's own most-recent-N."""
        if not account_ids:
            return []
        stmt = (
            select(Alert)
            .where(Alert.primary_account_id.in_(account_ids))
            .order_by(Alert.created_at.desc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt))

    def list_unassigned(self, *, limit: int = 100) -> list[Alert]:
        """Alerts with no case yet — the alert->case assignment queue
        (Phase 4 consumes this)."""
        stmt = select(Alert).where(Alert.case_id.is_(None)).limit(limit)
        return list(self.session.scalars(stmt))

    def list_by_status(self, status: str, *, limit: int = 100) -> list[Alert]:
        stmt = select(Alert).where(Alert.status == status).limit(limit)
        return list(self.session.scalars(stmt))

    def _list_where_clause(
        self,
        *,
        status: str | None = None,
        priority: Priority | None = None,
        severity: RiskLevel | None = None,
        detection_type: DetectionType | None = None,
        min_risk_score: float | None = None,
        max_risk_score: float | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        unassigned_only: bool = False,
        assigned_to: str | None = None,
    ) -> list[Any]:
        """Shared WHERE-clause builder for `list_filtered`/`count_filtered`
        (ROADMAP Phase 14: `GET /alerts`) -- one filter set, two callers, so
        the count a caller sees for a page always matches the page's own
        filters. `assigned_to` is deliberately a subquery against `cases`
        (not a column on `alerts` itself, doc §3.2's schema) rather than a
        join, so this repository's return type stays exactly `list[Alert]`/
        `int` with no risk of row duplication from the 1:many `cases` join
        surface a real JOIN would introduce."""
        clauses: list[Any] = []
        if status is not None:
            clauses.append(Alert.status == status)
        if priority is not None:
            clauses.append(Alert.priority == priority)
        if severity is not None:
            clauses.append(Alert.severity == severity)
        if detection_type is not None:
            clauses.append(Alert.detection_type == detection_type)
        if min_risk_score is not None:
            clauses.append(Alert.risk_score >= min_risk_score)
        if max_risk_score is not None:
            clauses.append(Alert.risk_score <= max_risk_score)
        if start is not None:
            clauses.append(Alert.created_at >= start)
        if end is not None:
            clauses.append(Alert.created_at <= end)
        if unassigned_only:
            clauses.append(Alert.case_id.is_(None))
        if assigned_to is not None:
            clauses.append(
                Alert.case_id.in_(select(Case.case_id).where(Case.assigned_to == assigned_to))
            )
        return clauses

    def list_filtered(
        self,
        *,
        status: str | None = None,
        priority: Priority | None = None,
        severity: RiskLevel | None = None,
        detection_type: DetectionType | None = None,
        min_risk_score: float | None = None,
        max_risk_score: float | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        unassigned_only: bool = False,
        assigned_to: str | None = None,
        sort: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Alert]:
        """`GET /alerts`'s data source (ROADMAP Phase 14). `sort=None`
        returns the full filtered set with no SQL ORDER BY and no LIMIT/
        OFFSET applied -- the caller (the route) is expected to run the RL
        prioritization queue over the full set and paginate in Python in
        that case, per `investigation.prioritization.rank_alert_queue`'s
        own "sorts everything, re-ranks only the top 200" contract. When
        `sort` is given, it's a plain SQL-ordered page instead (no RL
        re-ranking asked for -- an explicit sort order overrides it)."""
        clauses = self._list_where_clause(
            status=status,
            priority=priority,
            severity=severity,
            detection_type=detection_type,
            min_risk_score=min_risk_score,
            max_risk_score=max_risk_score,
            start=start,
            end=end,
            unassigned_only=unassigned_only,
            assigned_to=assigned_to,
        )
        stmt = select(Alert).where(*clauses)
        if sort is not None:
            stmt = stmt.order_by(self._LIST_SORTS[sort])
            if limit is not None:
                stmt = stmt.limit(limit).offset(offset)
        return list(self.session.scalars(stmt))

    def count_filtered(
        self,
        *,
        status: str | None = None,
        priority: Priority | None = None,
        severity: RiskLevel | None = None,
        detection_type: DetectionType | None = None,
        min_risk_score: float | None = None,
        max_risk_score: float | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        unassigned_only: bool = False,
        assigned_to: str | None = None,
    ) -> int:
        clauses = self._list_where_clause(
            status=status,
            priority=priority,
            severity=severity,
            detection_type=detection_type,
            min_risk_score=min_risk_score,
            max_risk_score=max_risk_score,
            start=start,
            end=end,
            unassigned_only=unassigned_only,
            assigned_to=assigned_to,
        )
        stmt = select(func.count()).select_from(Alert).where(*clauses)
        return self.session.scalar(stmt) or 0

    def count_active(self) -> int:
        """Every alert not in `"closed"` status -- the Dashboard's headline
        "active alerts" number (ROADMAP Phase 14). `"closed"` is written by
        `investigation.cases.close_case` for every `Alert` linked to a case
        it closes (code-review finding, Phase 14: this filter used to be a
        permanent no-op -- no code path ever wrote `"closed"`, only
        `"open"`/`"assigned"` -- fixed there, not here)."""
        stmt = select(func.count()).select_from(Alert).where(Alert.status != "closed")
        return self.session.scalar(stmt) or 0

    def count_active_grouped_by_severity(self) -> dict[str, int]:
        stmt = (
            select(Alert.severity, func.count())
            .where(Alert.status != "closed")
            .group_by(Alert.severity)
        )
        return {str(severity): count for severity, count in self.session.execute(stmt)}

    def avg_active_risk_score(self) -> float | None:
        stmt = select(func.avg(Alert.risk_score)).where(Alert.status != "closed")
        result = self.session.scalar(stmt)
        return float(result) if result is not None else None

    def count_by_day(self, *, since: datetime) -> list[tuple[str, int]]:
        """Alert counts bucketed by UTC calendar day since `since`, for the
        Dashboard's `alerts_over_time` chart (ROADMAP Phase 14). Bucketed in
        Python, not via a SQL `date()`/`strftime()` call -- this codebase
        targets both SQLite and Postgres (`docs/DATA_SCHEMA.md` §0) and
        those two engines' date-truncation functions diverge; fine at
        current scale (~4k rows) to fetch and bucket in Python instead.
        SQLite hands back a naive-but-UTC-valued `datetime` on read (see
        `db.repositories._audit._canonical_ts`'s identical reasoning) while
        a real tz-aware value (e.g. from Postgres) is converted to UTC
        first, so both engines bucket identically. Returns `(day, count)`
        pairs sorted by day ascending; days with zero alerts are NOT
        included here -- the caller (`investigation.dashboard.
        compute_dashboard_summary`) zero-fills the requested window."""
        stmt = select(Alert.created_at).where(Alert.created_at >= since)
        buckets: dict[str, int] = {}
        for (created_at,) in self.session.execute(stmt):
            if created_at.tzinfo is not None:
                created_at = created_at.astimezone(UTC)
            day = created_at.date().isoformat()
            buckets[day] = buckets.get(day, 0) + 1
        return sorted(buckets.items())


#: Public surface for `_LIST_SORTS`'s keys (ROADMAP Phase 14 spec: "expose
#: `ALERT_SORT_KEYS = set(_LIST_SORTS)` (module-level constant, not reaching
#: into a 'private' class attribute from the route module)") -- `api.routes.
#: alerts` validates a caller-supplied `sort` query param against this set.
ALERT_SORT_KEYS: set[str] = set(AlertRepository._LIST_SORTS)


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

    def counts_by_verdict(self) -> dict[str, int]:
        """Total resolved-case verdicts grouped by `CaseResolution`, e.g.
        `{"TRUE_POSITIVE_SAR": 12, "FALSE_POSITIVE": 30, ...}`. The durable,
        persisted basis for a real precision figure in the governance surface
        (ROADMAP Phase 12) -- unlike the bandit's process-lifetime tp/fp
        counters, these survive a restart."""
        stmt = select(DetectionFeedback.verdict, func.count()).group_by(
            DetectionFeedback.verdict
        )
        return {str(verdict): count for verdict, count in self.session.execute(stmt)}
