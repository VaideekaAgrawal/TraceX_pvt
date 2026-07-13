"""`orchestration.tools.registry`/`orchestration.tools.invoker` (ROADMAP
Phase 8) -- duplicate-name rejection, unknown-name lookup, catalog listing,
and the structural `case_id`-cannot-be-overridden guarantee."""
from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from db.enums import ActorType
from orchestration.tools import ToolInvoker
from orchestration.tools.registry import _REGISTRY, get_tool, list_tools, register_tool


def test_get_tool_raises_key_error_on_unknown_name() -> None:
    with pytest.raises(KeyError):
        get_tool("not_a_real_tool")


def test_list_tools_returns_the_full_catalog() -> None:
    names = {spec.name for spec in list_tools()}
    assert names == set(_REGISTRY.keys())
    # The 9 tools this phase's catalog registers (see orchestration.tools.catalog).
    expected = {
        "similar_cases",
        "path_recommendation_facts",
        "relationship_graph",
        "ego_graph",
        "network_risk",
        "previous_alerts_summary",
        "account_transaction_stats",
        "customer_profile",
        "search_transactions",
    }
    assert expected <= names


def test_register_tool_raises_on_duplicate_name() -> None:
    @register_tool("test_only_duplicate_check_tool", "for this test only")
    def _fn(session: Session, case_id: str, **kwargs: object) -> None:
        return None

    with pytest.raises(ValueError, match="already registered"):

        @register_tool("test_only_duplicate_check_tool", "duplicate")
        def _fn2(session: Session, case_id: str, **kwargs: object) -> None:
            return None

    del _REGISTRY["test_only_duplicate_check_tool"]  # don't leak into other tests


def test_network_risk_tool_has_write_true() -> None:
    assert get_tool("network_risk").write is True


def test_read_only_tool_has_write_false() -> None:
    assert get_tool("similar_cases").write is False


def test_tool_invoker_call_cannot_override_bound_case_id(session: Session) -> None:
    invoker = ToolInvoker(session, "CASE1", actor_type=ActorType.SYSTEM, actor_id=None)
    with pytest.raises(TypeError):
        invoker.call("similar_cases", case_id="OTHER_CASE")


def test_tool_invoker_accumulates_tools_called_across_calls(session: Session) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    @register_tool("test_only_accumulate_tool", "for this test only")
    def _fn(
        session: Session, case_id: str, *, actor_type: ActorType, actor_id: str | None, x: int
    ) -> int:
        calls.append(("test_only_accumulate_tool", {"x": x}))
        return x * 2

    try:
        invoker = ToolInvoker(session, "CASE1", actor_type=ActorType.SYSTEM, actor_id=None)
        assert invoker.call("test_only_accumulate_tool", x=1) == 2
        assert invoker.call("test_only_accumulate_tool", x=2) == 4
        assert invoker.tools_called == [
            {"tool": "test_only_accumulate_tool", "args": {"x": 1}},
            {"tool": "test_only_accumulate_tool", "args": {"x": 2}},
        ]
    finally:
        del _REGISTRY["test_only_accumulate_tool"]


def test_register_tool_rejects_wrapper_whose_second_positional_param_is_not_case_id() -> None:
    # Regression test (code-review finding): the case_id-cannot-be-overridden
    # guarantee is structural only if every registered wrapper's second
    # positional parameter is literally named `case_id` -- previously an
    # unenforced convention. A malformed wrapper must fail loudly at
    # decoration time, not silently lose that guarantee.
    with pytest.raises(ValueError, match="case_id"):

        @register_tool("test_only_malformed_tool", "wrong param name")
        def _bad_fn(session: Session, not_case_id: str, **kwargs: object) -> None:
            return None

    assert "test_only_malformed_tool" not in _REGISTRY


def test_register_tool_rejects_wrapper_with_too_few_positional_params() -> None:
    with pytest.raises(ValueError, match="case_id"):

        @register_tool("test_only_one_param_tool", "missing case_id entirely")
        def _bad_fn(session: Session, **kwargs: object) -> None:
            return None

    assert "test_only_one_param_tool" not in _REGISTRY


def test_tool_invoker_does_not_record_a_failed_call(session: Session) -> None:
    @register_tool("test_only_failing_tool", "for this test only")
    def _fn(session: Session, case_id: str, *, actor_type: ActorType, actor_id: str | None) -> None:
        raise ValueError("boom")

    try:
        invoker = ToolInvoker(session, "CASE1", actor_type=ActorType.SYSTEM, actor_id=None)
        with pytest.raises(ValueError, match="boom"):
            invoker.call("test_only_failing_tool")
        assert invoker.tools_called == []
    finally:
        del _REGISTRY["test_only_failing_tool"]
