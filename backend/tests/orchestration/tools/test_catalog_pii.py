"""
Catalog-wide PII egress test — ROADMAP Phase 8, committed decision 9.

Decision 9 is "zero egress, enforced, fail-closed": tools are *shaped* so PII is
never in the return value in the first place. That claim is only worth anything
if it is checked against every tool, on real PII values, rather than asserted in
a docstring — a future tool that innocently spreads a `Customer` row into its
payload would otherwise sail through code review.

So: plant real PII in the database, run **every** tool in the catalog, and assert
none of those values appears anywhere in any payload, at any nesting depth.

This is the "belt". The fail-closed egress gate (`orchestration/redaction.py`,
slice 4) is the "braces" — it raises on a PII value in a prompt-bound fact bundle
rather than silently stripping it. Both exist because *"it never left our
perimeter"* is a claim a bank can verify, and *"we de-identified it on the way
out"* is a materially weaker one.
"""
from __future__ import annotations

import json
from typing import Any

from orchestration.tools import TOOL_NAMES, ToolCatalog
from tests.orchestration.tools.test_catalog import (  # noqa: F401 -- fixtures
    ALL_PII,
    IN_CASE,
    catalog,
    seeded,
)


def _flatten(value: Any) -> str:
    """Every scalar in the payload, at any depth, as one searchable string.
    `default=str` so datetimes/enums/Decimals are stringified rather than
    blowing up — a PII value hiding inside an un-serializable object would
    otherwise slip past this check silently."""
    return json.dumps(value, default=str)


def test_no_tool_leaks_pii(catalog: ToolCatalog) -> None:  # noqa: F811
    leaks: list[str] = []

    for name in TOOL_NAMES:
        props = next(
            s["function"]["parameters"]["properties"]
            for s in catalog.schemas()
            if s["function"]["name"] == name
        )
        args: dict[str, Any] = {"account_id": IN_CASE} if "account_id" in props else {}

        payload = _flatten(catalog.dispatch(name, args))
        for pii in ALL_PII:
            if pii in payload:
                leaks.append(f"{name} leaked {pii!r}")

    assert not leaks, (
        "Tools must be SHAPED so PII is never in the return value (decision 9). "
        "Leaks found:\n  " + "\n  ".join(leaks)
    )


def test_account_facts_returns_the_customer_id_but_not_the_customer(
    catalog: ToolCatalog,  # noqa: F811
) -> None:
    # The positive half of decision 9: the AI still gets everything it needs to
    # reason about the customer — an internal id, entity type, risk rating,
    # income bracket — while never learning who the customer *is*. Zero egress
    # costs us no analytical capability here, which is precisely why it's
    # affordable to enforce absolutely.
    customer = catalog.dispatch("get_account_facts", {"account_id": IN_CASE})["customer"]

    assert customer["customer_id"] == "CUST1"
    assert customer["risk_rating"] == "HIGH"
    assert customer["income_bracket"] == "5-10L"
    assert customer["occupation"] == "Trader"

    for identifying in ("name", "pan", "aadhaar", "phone", "email", "address", "employer"):
        assert identifying not in customer, f"account facts exposed {identifying}"


def test_relationships_expose_the_attribute_type_never_the_value(
    catalog: ToolCatalog,  # noqa: F811
) -> None:
    # `Relationship.value_hash` delivers decision 9 for free: the model is told
    # two customers share a PAN, and how confident we are, but never which PAN.
    # That is the difference between an auditable signal and an egress incident.
    payload = _flatten(catalog.dispatch("get_relationships"))
    for pii in ALL_PII:
        assert pii not in payload
