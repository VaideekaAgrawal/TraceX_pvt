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
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from db.enums import ActorType
from orchestration.tools.registry import get_tool


class ToolInvoker:
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
