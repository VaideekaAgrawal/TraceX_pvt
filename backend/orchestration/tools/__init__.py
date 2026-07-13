"""
Tool layer (ROADMAP Phase 8) -- a FIXED catalog of retrievable/computed
tools, each scoped to a single case ID, that Phase 9's Recommendation
Engine and Phase 10's Copilot will call instead of ever running a free-form
DB/graph query themselves.

Importing this package registers the full catalog (`orchestration.tools.
catalog`, imported below for its side effect) so `get_tool`/`list_tools`
work immediately off `import orchestration.tools`.

Deliberately agent-agnostic mechanism only -- no action catalog, no ranking
policy, no LLM-driven tool selection (that's Phase 9/10's job; see
`orchestration.tools.registry`/`invoker` module docstrings)."""
from __future__ import annotations

from orchestration.tools import catalog  # noqa: F401 -- import for registration side effect
from orchestration.tools.invoker import ToolInvoker
from orchestration.tools.registry import ToolSpec, get_tool, list_tools, register_tool

__all__ = ["ToolInvoker", "ToolSpec", "get_tool", "list_tools", "register_tool"]
