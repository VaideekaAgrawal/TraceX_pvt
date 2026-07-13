"""
Fixed tool catalog registry (ROADMAP Phase 8). "Fixed" is load-bearing: the
catalog is populated once, at import time, by `orchestration.tools.catalog`
-- there is no dynamic registration path anywhere in this codebase, and
`register_tool` enforces that by raising on a duplicate name rather than
silently allowing a second registration to shadow the first.

Every tool is a thin wrapper (`orchestration.tools.catalog`) over an
existing, already-tested `investigation/*` function -- this registry does
not itself compute anything; it is the lookup table an agent (Phase 9/10)
or `ToolInvoker` (this phase) uses to find the right wrapper by name.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

#: `(session, case_id, *, actor_type, actor_id, **kwargs) -> Any` --
#: `session`/`case_id` positional (see `ToolInvoker.call`'s docstring for
#: why `case_id` can never be overridden via `**kwargs`), everything else
#: keyword-only.
ToolFn = Callable[..., Any]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    fn: ToolFn
    write: bool = False


_REGISTRY: dict[str, ToolSpec] = {}


def register_tool(
    name: str, description: str, *, write: bool = False
) -> Callable[[ToolFn], ToolFn]:
    """Decorator: `@register_tool("similar_cases", "...")` wraps a function
    into a `ToolSpec` and adds it to the fixed catalog under `name`.

    Raises `ValueError` on a duplicate `name` at IMPORT time (i.e. as soon
    as `orchestration.tools.catalog` is imported, since every `@register_
    tool` decoration runs at module load) -- this is what makes "the
    catalog is fixed" an enforced invariant rather than just a convention:
    there is no code path anywhere that could register a second tool under
    an existing name without the whole package failing to import."""

    def decorator(fn: ToolFn) -> ToolFn:
        if name in _REGISTRY:
            raise ValueError(f"tool {name!r} is already registered")
        _REGISTRY[name] = ToolSpec(name=name, description=description, fn=fn, write=write)
        return fn

    return decorator


def get_tool(name: str) -> ToolSpec:
    """Raises `KeyError` if `name` isn't in the fixed tool catalog."""
    return _REGISTRY[name]


def list_tools() -> list[ToolSpec]:
    return list(_REGISTRY.values())
