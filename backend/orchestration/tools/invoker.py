"""
`ToolInvoker` (ROADMAP Phase 8) -- the single call surface a future agent
(Phase 9/10) uses to reach the fixed tool catalog. `case_id` is bound once
at construction, never re-suppliable per call, so an agent structurally
cannot widen its own scope to another case mid-conversation by passing a
different `case_id` in `**kwargs` -- `ToolSpec.fn` already receives
`case_id` positionally from `self.case_id`, so a caller-supplied `case_id`
keyword would collide with that positional argument and raise `TypeError`
(Python's own multiple-values-for-argument error), not something this class
has to detect and reject itself.

**`ToolInvoker` does NOT itself verify the calling actor is assigned to
`case_id`.** `actor_type`/`actor_id` are threaded through purely for audit
attribution (they land in `audit_log`/`AiInteraction` rows via whatever a
tool wrapper's underlying `investigation/*` function does with them), never
for authorization -- there is no `case.assigned_to == actor_id` check
anywhere in this class or in `orchestration.tools.catalog`'s wrappers.
Case-ID scoping is structural (see above); actor-to-case AUTHORIZATION is
not. Callers MUST run `foundation.auth.require_case_access` (or
equivalent) before constructing a `ToolInvoker`, exactly as every existing
HTTP route does today (code-review finding: this reliance was previously
undisclosed). Deliberately not enforced inside this class itself --
`orchestration.tools` has no dependency on `foundation.auth`/`db.models.
platform.User` today, and adding one here would invert this codebase's
existing layering direction (`api` depends on `foundation.auth`, not the
reverse) for a check that's arguably the HTTP layer's job per ROADMAP
Phase 10's own "Hard RBAC scoping... (Phase 2 enforcement)" checklist
item -- Phase 9/10's actual HTTP wiring is where this belongs, not a
DB-querying assignment check bolted onto this mechanism-only class.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from db.enums import ActorType
from orchestration.tools.registry import get_tool


class ToolInvoker:
    """See module docstring for the full guardrail-boundary explanation --
    in short: `case_id` scoping is structural and enforced here; actor-to-
    case AUTHORIZATION is NOT and must already have been checked by the
    caller (`foundation.auth.require_case_access` or equivalent) before
    this class is ever constructed."""

    def __init__(
        self, session: Session, case_id: str, *, actor_type: ActorType, actor_id: str | None
    ) -> None:
        self.session = session
        self.case_id = case_id
        self.actor_type = actor_type
        self.actor_id = actor_id
        self.tools_called: list[dict[str, Any]] = []

    def call(self, tool_name: str, **kwargs: Any) -> Any:
        """Look up `tool_name` in the fixed catalog (raises `KeyError` if
        unknown) and invoke its wrapper with `self.session`/`self.case_id`
        bound positionally, `self.actor_type`/`self.actor_id` bound as
        keywords, and `kwargs` forwarded as the tool's own parameters.

        Records `{"tool": tool_name, "args": kwargs}` onto `self.
        tools_called` on success -- accumulates across every call this
        invoker makes, so a caller can pass the full list straight into
        `orchestration.llm_client.generate_and_persist_explanation`'s new
        `tools_called` parameter once a whole tool-calling sequence is
        done. NOT recorded if `spec.fn` raises -- a failed/rejected call
        (e.g. an out-of-scope `account_id`) never happened as far as the
        audit trail is concerned."""
        spec = get_tool(tool_name)
        value = spec.fn(
            self.session, self.case_id, actor_type=self.actor_type, actor_id=self.actor_id,
            **kwargs,
        )
        self.tools_called.append({"tool": tool_name, "args": kwargs})
        return value
