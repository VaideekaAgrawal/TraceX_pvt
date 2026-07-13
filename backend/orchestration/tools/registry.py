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

import inspect
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


def _require_case_id_second_positional(fn: ToolFn, name: str) -> None:
    """`ToolInvoker.call`'s `case_id`-cannot-be-overridden guarantee (see
    that class's docstring) relies on `spec.fn`'s SECOND positional
    parameter literally being named `case_id`, so the positional bind in
    `spec.fn(self.session, self.case_id, ...)` collides with a caller-
    supplied `case_id` keyword and raises `TypeError`. That was previously
    an unenforced naming convention every registered wrapper just happened
    to follow -- checked here, at decoration time, so a future wrapper that
    doesn't conform fails loudly at import time instead of silently losing
    that guarantee (code-review finding, same "fails loudly at decoration
    time" posture as the duplicate-name check below)."""
    params = [
        p
        for p in inspect.signature(fn).parameters.values()
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    if len(params) < 2 or params[1].name != "case_id":
        got = [p.name for p in params]
        raise ValueError(
            f"tool {name!r}: registered function's second positional parameter must be "
            f"named 'case_id' (ToolInvoker.call binds it positionally there) -- got {got!r}"
        )


def register_tool(
    name: str, description: str, *, write: bool = False
) -> Callable[[ToolFn], ToolFn]:
    """Decorator: `@register_tool("similar_cases", "...")` wraps a function
    into a `ToolSpec` and adds it to the fixed catalog under `name`.

    Raises `ValueError` on a duplicate `name`, OR if the function's second
    positional parameter isn't literally named `case_id` (see
    `_require_case_id_second_positional`), at IMPORT time (i.e. as soon as
    `orchestration.tools.catalog` is imported, since every `@register_tool`
    decoration runs at module load) -- this is what makes "the catalog is
    fixed" and "`case_id` cannot be overridden" enforced invariants rather
    than just conventions: there is no code path anywhere that could
    register a second tool under an existing name, or a tool that doesn't
    structurally protect `case_id`, without the whole package failing to
    import."""

    def decorator(fn: ToolFn) -> ToolFn:
        if name in _REGISTRY:
            raise ValueError(f"tool {name!r} is already registered")
        _require_case_id_second_positional(fn, name)
        _REGISTRY[name] = ToolSpec(name=name, description=description, fn=fn, write=write)
        return fn

    return decorator


def get_tool(name: str) -> ToolSpec:
    """Raises `KeyError` if `name` isn't in the fixed tool catalog."""
    return _REGISTRY[name]


def list_tools() -> list[ToolSpec]:
    return list(_REGISTRY.values())
