"""
Repositories for `docs/DATA_SCHEMA.md` §3.3 investigation spine: `cases`,
`case_accounts`, `case_status_history`, `evidence`, `notes`, `reports`,
`case_feature_vector`.

`cases` is explicitly called out (doc §3.3) as "kills the two-store
landmine" — the ONE case store going forward. `CaseRepository` reads/writes
only the `cases` row itself; it must never cache status/assignment
elsewhere. Note in particular: `CaseRepository.update()` does not also
write a `case_status_history` row on a status change — writing that history
row is a second, explicit call to `CaseStatusHistoryRepository` by the
caller (the Phase 4 FSM). Baking that coupling into `CaseRepository` would
mean the repository deciding *when* a transition is FSM-valid, which is
lifecycle business logic (explicitly out of scope: Phase 4), not
persistence. Both tables are independently reachable/writable through their
own repos now so nothing here needs "unwinding" once Phase 4 lands.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from db.enums import (
    AccountRole,
    ActorType,
    CaseLevel,
    CaseResolution,
    CaseStatus,
    EvidenceType,
    NoteSource,
    Priority,
    ReportStatus,
    ReportType,
)
from db.models.base import utcnow
from db.models.investigation import (
    Case,
    CaseAccount,
    CaseFeatureVector,
    CaseStatusHistory,
    Evidence,
    Note,
    Report,
)
from db.repositories.base import UNSET, BaseRepository, collect_changes


class CaseRepository(BaseRepository[Case]):
    model = Case
    entity_type = "case"
    pk_attr = "case_id"

    def create(
        self,
        *,
        case_id: str,
        primary_account_id: str,
        status: CaseStatus,
        level: CaseLevel,
        priority: Priority,
        title: str | None = None,
        typology: str | None = None,
        risk_score: float | None = None,
        network_risk_score: float | None = None,
        network_risk_reasons: dict | None = None,
        assigned_to: str | None = None,
        sla_due_at: datetime | None = None,
        actor_type: ActorType,
        actor_id: str | None,
    ) -> Case:
        case = Case(
            case_id=case_id,
            primary_account_id=primary_account_id,
            title=title,
            status=status,
            level=level,
            priority=priority,
            typology=typology,
            risk_score=risk_score,
            network_risk_score=network_risk_score,
            network_risk_reasons=network_risk_reasons,
            assigned_to=assigned_to,
            sla_due_at=sla_due_at,
        )
        return self._create(
            case,
            actor_type=actor_type,
            actor_id=actor_id,
            action="case_created",
            case_id=case_id,
        )

    def update(
        self,
        case_id: str,
        *,
        actor_type: ActorType,
        actor_id: str | None,
        title: str | None = UNSET,
        level: CaseLevel = UNSET,
        priority: Priority = UNSET,
        typology: str | None = UNSET,
        risk_score: float | None = UNSET,
        network_risk_score: float | None = UNSET,
        network_risk_reasons: dict | None = UNSET,
        assigned_to: str | None = UNSET,
        sla_due_at: datetime | None = UNSET,
        closed_at: datetime | None = UNSET,
        resolution: CaseResolution | None = UNSET,
        resolution_reason: str | None = UNSET,
        evidence_hash: str | None = UNSET,
        action: str = "case_updated",
    ) -> Case:
        """Plain field update on the one `cases` row -- every column
        *except* `status`. Does not touch `case_status_history` — see
        module docstring.

        `status` is deliberately NOT a parameter here (code-review finding,
        Phase 4: it used to be, and nothing structurally stopped a future
        caller from writing `Case.status` directly, bypassing FSM-legality
        checks, the `case_status_history` row, and any RL-feedback wiring
        that a real transition implies). `set_status_for_transition()` is
        the only method on this repository that can change `status`, and it
        is documented as callable only from `investigation.fsm.
        transition_case` — so that module is now structurally, not just
        conventionally, the sole path to a status change.

        `action` defaults to the generic `case_updated` verb but is
        overridable so Phase 4's case-lifecycle callers can log the
        taxonomy-specific verbs `docs/DATA_SCHEMA.md` §3.5 names (e.g.
        `evidence_pinned`-adjacent case verbs) instead of a generic one.
        """
        case = self.get(case_id)
        if case is None:
            raise ValueError(f"case {case_id!r} does not exist")
        changes = collect_changes(
            title=title,
            level=level,
            priority=priority,
            typology=typology,
            risk_score=risk_score,
            network_risk_score=network_risk_score,
            network_risk_reasons=network_risk_reasons,
            assigned_to=assigned_to,
            sla_due_at=sla_due_at,
            closed_at=closed_at,
            resolution=resolution,
            resolution_reason=resolution_reason,
            evidence_hash=evidence_hash,
        )
        return self._update(
            case,
            changes,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            case_id=case_id,
        )

    def set_status_for_transition(
        self,
        case_id: str,
        *,
        status: CaseStatus,
        action: str,
        actor_type: ActorType,
        actor_id: str | None,
        assigned_to: str | None = UNSET,
        sla_due_at: datetime | None = UNSET,
        closed_at: datetime | None = UNSET,
        resolution: CaseResolution | None = UNSET,
        resolution_reason: str | None = UNSET,
    ) -> Case:
        """The ONLY repository method that may change `Case.status` —
        intentionally callable exclusively from `investigation.fsm.
        transition_case`, which owns FSM-legality validation and the
        `case_status_history` append (Phase 1's module docstring: "the
        repository deciding *when* a transition is FSM-valid... is
        lifecycle business logic", out of scope for this repository).

        Also accepts the handful of other plain `cases` fields that
        realistically change *at the same moment* as a status transition
        (`assigned_to`/`sla_due_at` for the NEW->ASSIGNED handoff,
        `resolution`/`resolution_reason`/`closed_at` for a closing
        transition) so a caller like `investigation.assignment.auto_assign`
        or `investigation.cases.close_case` writes them in the SAME
        `_update()` call/audit_log row as the status change, instead of two
        separate `case_repo` calls producing two audit rows for one logical
        event (code-review finding, Phase 4: confirmed live as
        `case_assigned` appearing twice per real assignment). Deliberately
        narrower than `update()`'s full field list -- extend it if a future
        caller genuinely needs to bundle another field with a transition,
        rather than widening this preemptively.
        """
        case = self.get(case_id)
        if case is None:
            raise ValueError(f"case {case_id!r} does not exist")
        changes = collect_changes(
            status=status,
            assigned_to=assigned_to,
            sla_due_at=sla_due_at,
            closed_at=closed_at,
            resolution=resolution,
            resolution_reason=resolution_reason,
        )
        return self._update(
            case,
            changes,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            case_id=case_id,
        )

    def list_by_assignee(
        self, user_id: str, *, statuses: list[CaseStatus] | None = None, limit: int = 100
    ) -> list[Case]:
        stmt = select(Case).where(Case.assigned_to == user_id)
        if statuses:
            stmt = stmt.where(Case.status.in_(statuses))
        stmt = stmt.limit(limit)
        return list(self.session.scalars(stmt))

    def list_by_status(self, status: CaseStatus, *, limit: int = 100) -> list[Case]:
        stmt = select(Case).where(Case.status == status).limit(limit)
        return list(self.session.scalars(stmt))


class CaseAccountRepository(BaseRepository[CaseAccount]):
    model = CaseAccount
    entity_type = "case_account"
    pk_attr = "id"

    def add_account(
        self,
        *,
        case_id: str,
        account_id: str,
        role: AccountRole | None = None,
        hop_distance: int | None = None,
        actor_type: ActorType,
        actor_id: str | None,
    ) -> CaseAccount:
        case_account = CaseAccount(
            case_id=case_id, account_id=account_id, role=role, hop_distance=hop_distance
        )
        return self._create(
            case_account,
            actor_type=actor_type,
            actor_id=actor_id,
            action="case_account_added",
            case_id=case_id,
        )

    def update(
        self,
        id_: int,
        *,
        actor_type: ActorType,
        actor_id: str | None,
        role: AccountRole | None = UNSET,
        hop_distance: int | None = UNSET,
    ) -> CaseAccount:
        case_account = self.get(id_)
        if case_account is None:
            raise ValueError(f"case_account {id_!r} does not exist")
        changes = collect_changes(role=role, hop_distance=hop_distance)
        return self._update(
            case_account,
            changes,
            actor_type=actor_type,
            actor_id=actor_id,
            action="case_account_updated",
            case_id=case_account.case_id,
        )

    def list_for_case(self, case_id: str) -> list[CaseAccount]:
        """The accounts a case's scope permits AI/graph tools to touch —
        this table *is* the case-scoping security boundary (doc §3.3)."""
        stmt = select(CaseAccount).where(CaseAccount.case_id == case_id)
        return list(self.session.scalars(stmt))


class CaseStatusHistoryRepository(BaseRepository[CaseStatusHistory]):
    """Append-only FSM transition log — no `update()`, only
    `record_transition` (create) + reads, matching the doc's "explicit
    history (not derived)" reasoning."""

    model = CaseStatusHistory
    entity_type = "case_status_history"
    pk_attr = "id"

    def record_transition(
        self,
        *,
        case_id: str,
        to_status: CaseStatus,
        from_status: CaseStatus | None = None,
        changed_by: str | None = None,
        reason: str | None = None,
        changed_at: datetime | None = None,
        actor_type: ActorType,
        actor_id: str | None,
    ) -> CaseStatusHistory:
        history = CaseStatusHistory(
            case_id=case_id,
            from_status=from_status,
            to_status=to_status,
            changed_by=changed_by,
            reason=reason,
            changed_at=changed_at if changed_at is not None else utcnow(),
        )
        return self._create(
            history,
            actor_type=actor_type,
            actor_id=actor_id,
            action="case_status_history_recorded",
            case_id=case_id,
        )

    def list_for_case(self, case_id: str) -> list[CaseStatusHistory]:
        stmt = (
            select(CaseStatusHistory)
            .where(CaseStatusHistory.case_id == case_id)
            .order_by(CaseStatusHistory.changed_at.asc())
        )
        return list(self.session.scalars(stmt))


class EvidenceRepository(BaseRepository[Evidence]):
    model = Evidence
    entity_type = "evidence"
    pk_attr = "evidence_id"

    def create(
        self,
        *,
        evidence_id: str,
        case_id: str,
        type: EvidenceType,  # noqa: A002 -- mirrors the doc's column name
        added_by: str,
        ref_id: str | None = None,
        label: str | None = None,
        payload: dict | None = None,
        file_path: str | None = None,
        pinned: bool = False,
        added_at: datetime | None = None,
        actor_type: ActorType,
        actor_id: str | None,
    ) -> Evidence:
        evidence = Evidence(
            evidence_id=evidence_id,
            case_id=case_id,
            type=type,
            ref_id=ref_id,
            label=label,
            payload=payload,
            file_path=file_path,
            pinned=pinned,
            added_by=added_by,
            added_at=added_at if added_at is not None else utcnow(),
        )
        return self._create(
            evidence,
            actor_type=actor_type,
            actor_id=actor_id,
            action="evidence_created",
            case_id=case_id,
        )

    def update(
        self,
        evidence_id: str,
        *,
        actor_type: ActorType,
        actor_id: str | None,
        label: str | None = UNSET,
        payload: dict | None = UNSET,
        file_path: str | None = UNSET,
        pinned: bool = UNSET,
    ) -> Evidence:
        evidence = self.get(evidence_id)
        if evidence is None:
            raise ValueError(f"evidence {evidence_id!r} does not exist")
        changes = collect_changes(
            label=label, payload=payload, file_path=file_path, pinned=pinned
        )
        return self._update(
            evidence,
            changes,
            actor_type=actor_type,
            actor_id=actor_id,
            action="evidence_updated",
            case_id=evidence.case_id,
        )

    def pin(self, evidence_id: str, *, actor_type: ActorType, actor_id: str | None) -> Evidence:
        """Mark an evidence item pinned, generating a dedicated
        `evidence_pinned` audit action (`docs/DATA_SCHEMA.md` §3.5's named
        taxonomy verb) instead of the generic `evidence_updated` the plain
        `update()` method would log for the same field change. Kept as its
        own method (rather than asking every caller to remember
        `update(..., pinned=True)`) precisely so "pin" is always audited
        under its own distinguishable action name."""
        evidence = self.get(evidence_id)
        if evidence is None:
            raise ValueError(f"evidence {evidence_id!r} does not exist")
        return self._update(
            evidence,
            {"pinned": True},
            actor_type=actor_type,
            actor_id=actor_id,
            action="evidence_pinned",
            case_id=evidence.case_id,
        )

    def list_for_case(self, case_id: str) -> list[Evidence]:
        stmt = select(Evidence).where(Evidence.case_id == case_id)
        return list(self.session.scalars(stmt))

    def list_pinned_for_case(self, case_id: str) -> list[Evidence]:
        stmt = select(Evidence).where(
            Evidence.case_id == case_id, Evidence.pinned.is_(True)
        )
        return list(self.session.scalars(stmt))


class NoteRepository(BaseRepository[Note]):
    model = Note
    entity_type = "note"
    pk_attr = "note_id"

    def create(
        self,
        *,
        note_id: str,
        case_id: str,
        source: NoteSource,
        body: str,
        author_id: str | None = None,
        created_at: datetime | None = None,
        actor_type: ActorType,
        actor_id: str | None,
    ) -> Note:
        note = Note(
            note_id=note_id,
            case_id=case_id,
            author_id=author_id,
            source=source,
            body=body,
            created_at=created_at if created_at is not None else utcnow(),
        )
        return self._create(
            note,
            actor_type=actor_type,
            actor_id=actor_id,
            action="note_created",
            case_id=case_id,
        )

    def update(
        self, note_id: str, *, body: str, actor_type: ActorType, actor_id: str | None
    ) -> Note:
        note = self.get(note_id)
        if note is None:
            raise ValueError(f"note {note_id!r} does not exist")
        return self._update(
            note,
            {"body": body},
            actor_type=actor_type,
            actor_id=actor_id,
            action="note_updated",
            case_id=note.case_id,
        )

    def list_for_case(self, case_id: str) -> list[Note]:
        stmt = select(Note).where(Note.case_id == case_id).order_by(Note.created_at.asc())
        return list(self.session.scalars(stmt))


class ReportRepository(BaseRepository[Report]):
    model = Report
    entity_type = "report"
    pk_attr = "report_id"

    def create(
        self,
        *,
        report_id: str,
        case_id: str,
        type: ReportType,  # noqa: A002 -- mirrors the doc's column name
        status: ReportStatus,
        generated_by: str,
        narrative: str | None = None,
        json_payload: str | None = None,
        json_hash: str | None = None,
        pdf_path: str | None = None,
        fiu_reference: str | None = None,
        generated_at: datetime | None = None,
        actor_type: ActorType,
        actor_id: str | None,
    ) -> Report:
        report = Report(
            report_id=report_id,
            case_id=case_id,
            type=type,
            status=status,
            narrative=narrative,
            json_payload=json_payload,
            json_hash=json_hash,
            pdf_path=pdf_path,
            fiu_reference=fiu_reference,
            generated_by=generated_by,
            generated_at=generated_at if generated_at is not None else utcnow(),
        )
        return self._create(
            report,
            actor_type=actor_type,
            actor_id=actor_id,
            action="report_created",
            case_id=case_id,
        )

    def update(
        self,
        report_id: str,
        *,
        actor_type: ActorType,
        actor_id: str | None,
        status: ReportStatus = UNSET,
        narrative: str | None = UNSET,
        json_payload: str | None = UNSET,
        json_hash: str | None = UNSET,
        pdf_path: str | None = UNSET,
        fiu_reference: str | None = UNSET,
        submitted_at: datetime | None = UNSET,
    ) -> Report:
        report = self.get(report_id)
        if report is None:
            raise ValueError(f"report {report_id!r} does not exist")
        changes = collect_changes(
            status=status,
            narrative=narrative,
            json_payload=json_payload,
            json_hash=json_hash,
            pdf_path=pdf_path,
            fiu_reference=fiu_reference,
            submitted_at=submitted_at,
        )
        return self._update(
            report,
            changes,
            actor_type=actor_type,
            actor_id=actor_id,
            action="report_updated",
            case_id=report.case_id,
        )

    def list_for_case(self, case_id: str) -> list[Report]:
        stmt = select(Report).where(Report.case_id == case_id)
        return list(self.session.scalars(stmt))


class CaseFeatureVectorRepository(BaseRepository[CaseFeatureVector]):
    """1:1 with `cases` (doc §3.3) — `upsert` since a case's feature vector
    is recomputed in place, not versioned."""

    model = CaseFeatureVector
    entity_type = "case_feature_vector"
    pk_attr = "case_id"

    def upsert(
        self,
        *,
        case_id: str,
        vector: list[float],
        typology: str | None = None,
        outcome: CaseResolution | None = None,
        computed_at: datetime | None = None,
        actor_type: ActorType,
        actor_id: str | None,
    ) -> CaseFeatureVector:
        now = computed_at if computed_at is not None else utcnow()
        existing = self.get(case_id)
        if existing is None:
            feature_vector = CaseFeatureVector(
                case_id=case_id, vector=vector, typology=typology, outcome=outcome, computed_at=now
            )
            return self._create(
                feature_vector,
                actor_type=actor_type,
                actor_id=actor_id,
                action="case_feature_vector_created",
                case_id=case_id,
            )
        changes = {"vector": vector, "typology": typology, "outcome": outcome, "computed_at": now}
        return self._update(
            existing,
            changes,
            actor_type=actor_type,
            actor_id=actor_id,
            action="case_feature_vector_updated",
            case_id=case_id,
        )
