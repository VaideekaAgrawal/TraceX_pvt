"""The Copilot tool catalog — ROADMAP Phase 10.

Duck-types the interface `orchestration.agent_loop` needs (`schemas()` +
`dispatch()`), so the Copilot reuses Phase 9's loop unchanged. But where Phase
9's `ToolCatalog` binds ONE case at construction (the model cannot name a
different case), the Copilot is cross-case by design — so here `case_id` is a
**validated argument**: every case-specific tool checks the requested case
against `scoping.accessible_case_ids` and returns a `ToolError`, never data, if
it is outside the user's own work. The RBAC boundary moved from "one case" to
"this user's cases"; it is still enforced in code, not in the prompt.

Two tiers of tool:

- **Personal / cross-case** (`list_my_cases`, `whats_changed`, `write_case_note`)
  — shaped to be PII-free *by construction* (ids, enums, counts, timestamps, no
  names and no free text), so they need no per-case PII gate: there is nothing to
  leak. `whats_changed` deliberately omits audit `details` for this reason (a
  note-added row's details can carry the note body).

- **Per-case facts** (`get_case_overview`, `get_account_facts`, `get_money_flow`,
  `get_ego_graph_summary`, `find_similar_cases`) — after validating the case,
  these **delegate to a Phase 9 `ToolCatalog` bound to that case**, so the fact
  computation, account-scope check, and PII egress gate are the exact same
  already-tested code, not a second copy. Names never appear (the model gets
  `customer_id`); re-hydration to a name happens later, at the display boundary.

Note reading is intentionally absent: per decision 10, `notes.body` never enters
a prompt. The Copilot can *write* a note; the investigator reads notes through the
case UI.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from db.enums import NoteSource
from db.models.platform import User
from db.repositories.investigation import CaseRepository, NoteRepository
from db.repositories.platform import AuditLogRepository
from foundation.auth import actor_type_for_role
from orchestration.tools.catalog import ToolCatalog, ToolError, build_tool_catalog

_DEFAULT_DIGEST_HOURS = 168  # a week — "what changed since I was last here"
_MAX_DIGEST_HOURS = 720  # 30 days, so an unbounded value can't scan all history
_NOTE_MAX_CHARS = 2000


def _s(desc: str) -> dict[str, Any]:
    return {"type": "string", "description": desc}


def _nullable(type_: str, desc: str) -> dict[str, Any]:
    return {"type": [type_, "null"], "description": f"{desc} Pass null for the default."}


class CopilotCatalog:
    """Investigator-scoped tools for one Copilot interaction."""

    def __init__(self, session: Session, user: User, accessible_case_ids: set[str]) -> None:
        self._session = session
        self._user = user
        self._accessible = accessible_case_ids
        self._actor_type = actor_type_for_role(user.role)
        # Phase 9 case catalogs, built lazily and cached per case for this request.
        self._case_catalogs: dict[str, ToolCatalog] = {}

    # ── agent_loop interface ──────────────────────────────────────────────

    def schemas(self) -> list[dict[str, Any]]:
        return [self._tool_schema(name, props, desc) for name, props, desc in _TOOLS]

    def dispatch(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        args = {k: v for k, v in dict(arguments or {}).items() if v is not None}
        handler = _HANDLERS.get(name)
        if handler is None:
            available = ", ".join(n for n, _, _ in _TOOLS)
            raise ToolError(f"unknown tool {name!r}; available: {available}")
        return handler(self, args)

    # ── shared helpers ────────────────────────────────────────────────────

    def _require_case(self, args: dict[str, Any]) -> str:
        """Pull `case_id` from args and validate it against this user's scope.

        The 'not in your scope' and 'no such case' answers are deliberately the
        same `ToolError` — the model, like an unauthorised user, should not learn
        whether a case it cannot see exists (the same non-disclosure Phase 9's
        account scoping and the HTTP routes' 404-not-403 already keep)."""
        case_id = args.get("case_id")
        if not case_id:
            raise ToolError("this tool requires a case_id argument")
        case_id = str(case_id)
        if case_id not in self._accessible:
            raise ToolError(f"case {case_id!r} is not in your assigned cases")
        return case_id

    def _case_catalog(self, case_id: str) -> ToolCatalog:
        cat = self._case_catalogs.get(case_id)
        if cat is None:
            cat = build_tool_catalog(
                self._session, case_id, actor_type=self._actor_type, actor_id=self._user.user_id
            )
            self._case_catalogs[case_id] = cat
        return cat

    @staticmethod
    def _tool_schema(name: str, properties: dict[str, Any], description: str) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "strict": True,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": sorted(properties),
                    "additionalProperties": False,
                },
            },
        }

    # ── personal / cross-case tools (PII-free by construction) ────────────

    def _list_my_cases(self, args: dict[str, Any]) -> dict[str, Any]:
        # Load only THIS user's cases, not the whole table then filtered in Python
        # (`list_filtered()` with no args scans every case in the system). The
        # accessible set is already role-scoped by `scoping.accessible_case_ids`.
        repo = CaseRepository(self._session)
        cases = [c for c in (repo.get(cid) for cid in self._accessible) if c is not None]
        # highest-risk first, deterministic; risk_score is nullable, treat None as 0.
        cases.sort(key=lambda c: c.risk_score if c.risk_score is not None else 0.0, reverse=True)
        return {
            "case_count": len(cases),
            "cases": [
                {
                    "case_id": c.case_id,
                    "primary_account_id": c.primary_account_id,
                    "status": str(c.status),
                    "level": str(c.level),
                    "priority": str(c.priority),
                    "risk_score": c.risk_score,
                    "network_risk_score": c.network_risk_score,
                }
                for c in cases
            ],
        }

    def _whats_changed(self, args: dict[str, Any]) -> dict[str, Any]:
        hours = min(int(args.get("hours", _DEFAULT_DIGEST_HOURS)), _MAX_DIGEST_HOURS)
        cutoff = datetime.now(UTC) - timedelta(hours=hours)
        audit = AuditLogRepository(self._session)
        per_case: list[dict[str, Any]] = []
        for case_id in sorted(self._accessible):
            events = [
                {
                    "action": e.action,
                    "entity_type": e.entity_type,
                    "entity_id": e.entity_id,
                    "actor_id": e.actor_id,
                    "at": e.created_at.isoformat() if e.created_at else None,
                }
                for e in audit.list_for_case(case_id, limit=100)
                if e.created_at is not None and _aware(e.created_at) >= cutoff
            ]
            if events:
                per_case.append({"case_id": case_id, "event_count": len(events), "events": events})
        return {"since_hours": hours, "changed_case_count": len(per_case), "cases": per_case}

    def _write_case_note(self, args: dict[str, Any]) -> dict[str, Any]:
        case_id = self._require_case(args)
        body = str(args.get("note", "")).strip()[:_NOTE_MAX_CHARS]
        if not body:
            raise ToolError("note text is required")
        note = NoteRepository(self._session).create(
            note_id=str(uuid4()),
            case_id=case_id,
            source=NoteSource.COPILOT,
            body=body,
            author_id=self._user.user_id,
            actor_type=self._actor_type,
            actor_id=self._user.user_id,
        )
        return {"note_id": note.note_id, "case_id": case_id, "saved": True}

    # ── per-case fact tools (delegate to the Phase 9 catalog) ─────────────

    def _get_case_overview(self, args: dict[str, Any]) -> dict[str, Any]:
        case_id = self._require_case(args)
        return self._case_catalog(case_id).dispatch("get_case_summary")

    def _get_account_facts(self, args: dict[str, Any]) -> dict[str, Any]:
        case_id = self._require_case(args)
        return self._case_catalog(case_id).dispatch(
            "get_account_facts", {"account_id": args.get("account_id")}
        )

    def _get_money_flow(self, args: dict[str, Any]) -> dict[str, Any]:
        case_id = self._require_case(args)
        return self._case_catalog(case_id).dispatch(
            "get_money_flow", {"account_id": args.get("account_id")}
        )

    def _get_ego_graph_summary(self, args: dict[str, Any]) -> dict[str, Any]:
        case_id = self._require_case(args)
        return self._case_catalog(case_id).dispatch(
            "get_ego_graph_summary",
            {"account_id": args.get("account_id"), "radius": args.get("radius")},
        )

    def _find_similar_cases(self, args: dict[str, Any]) -> dict[str, Any]:
        case_id = self._require_case(args)
        return self._case_catalog(case_id).dispatch(
            "find_similar_cases", {"top_k": args.get("top_k")}
        )


def _aware(dt: datetime) -> datetime:
    """SQLite round-trips tz-naive; treat a naive timestamp as UTC so the digest
    cutoff comparison never raises on naive-vs-aware."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


# name -> (properties, description). Order is the stable schema order.
_ACCOUNT = _s("An account id linked to the given case.")
_CASE = _s("A case id from your own cases (see list_my_cases).")

_TOOLS: tuple[tuple[str, dict[str, Any], str], ...] = (
    (
        "list_my_cases",
        {},
        "List the cases assigned to you (or, for a compliance reviewer, your review "
        "queue): case id, primary account, status, level, priority, and risk scores. "
        "No customer names — refer to customers by customer_id.",
    ),
    (
        "whats_changed",
        {"hours": _nullable("integer", "Look back this many hours (default 168 = 1 week).")},
        "A digest of what changed across your cases recently: the audit events "
        "(alerts opened, cases assigned/escalated, notes added, decisions) per case.",
    ),
    (
        "get_case_overview",
        {"case_id": _CASE},
        "Overview of one of your cases: status, level, priority, risk and "
        "network-risk scores, linked accounts, and the alerts that fired.",
    ),
    (
        "get_account_facts",
        {"case_id": _CASE, "account_id": _ACCOUNT},
        "Transaction statistics and non-identifying customer attributes for one "
        "account in one of your cases (totals, counterparties, occupation, income "
        "bracket, risk score). Returns customer_id, never a name.",
    ),
    (
        "get_money_flow",
        {"case_id": _CASE, "account_id": _ACCOUNT},
        "Direct (1-hop) fund flow into and out of one account, with each "
        "counterparty's total, transaction count, and share of the flow.",
    ),
    (
        "get_ego_graph_summary",
        {
            "case_id": _CASE,
            "account_id": _ACCOUNT,
            "radius": _nullable("integer", "Hops to expand (1-3)."),
        },
        "A compact summary of the transaction neighbourhood around one account: "
        "node/edge counts, total flow, highest-risk accounts, largest flows.",
    ),
    (
        "find_similar_cases",
        {"case_id": _CASE, "top_k": _nullable("integer", "How many to return.")},
        "Historically resolved cases most similar to one of your cases, each with "
        "its similarity, typology, and how it was resolved.",
    ),
    (
        "write_case_note",
        {"case_id": _CASE, "note": _s("The note text to record (what the investigator dictated).")},
        "Record a note on one of your cases (saved as a Copilot-authored note). Use "
        "only to save something the investigator asked you to note down.",
    ),
)

_HANDLERS = {
    "list_my_cases": CopilotCatalog._list_my_cases,
    "whats_changed": CopilotCatalog._whats_changed,
    "get_case_overview": CopilotCatalog._get_case_overview,
    "get_account_facts": CopilotCatalog._get_account_facts,
    "get_money_flow": CopilotCatalog._get_money_flow,
    "get_ego_graph_summary": CopilotCatalog._get_ego_graph_summary,
    "find_similar_cases": CopilotCatalog._find_similar_cases,
    "write_case_note": CopilotCatalog._write_case_note,
}
