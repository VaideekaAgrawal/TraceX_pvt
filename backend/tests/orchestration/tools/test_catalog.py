"""
Tool catalog tests — ROADMAP Phase 8, slice 2.

These are mostly *security* tests, not feature tests. The catalog's job is to
make three things impossible rather than discouraged (see
`orchestration/tools/catalog.py`): the model cannot name a different case, it
cannot read an account outside the case it was bound to, and it cannot see PII.
Each is asserted here against the shape an actual attack takes — a forged
`case_id` argument, an out-of-case `account_id`, and real PII values planted in
the database — rather than by checking that the code merely looks right.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy.orm import Session

from db.enums import (
    ActorType,
    CaseLevel,
    CaseStatus,
    Channel,
    EntityType,
    Priority,
    RiskLevel,
    UserRole,
)
from db.repositories.investigation import CaseAccountRepository, CaseRepository
from db.repositories.platform import UserRepository
from db.repositories.reference import AccountRepository, CustomerRepository, TransactionRepository
from orchestration.tools import TOOL_NAMES, Tool, ToolCatalog, ToolError, build_tool_catalog

# Planted PII. Every value here is distinctive enough that a substring search
# over a tool payload cannot produce a false positive.
PII_NAME = "Rajesh Kumar Sharma"
PII_PAN = "ZZQPK9081L"
PII_AADHAAR = "123456789012"
PII_PHONE = "9876543210"
PII_EMAIL = "rajesh.sharma@example.com"
PII_ADDRESS = "42 Marine Drive, Mumbai"
PII_EMPLOYER = "Sharma Exports Pvt Ltd"
ALL_PII = (
    PII_NAME, PII_PAN, PII_AADHAAR, PII_PHONE, PII_EMAIL, PII_ADDRESS, PII_EMPLOYER,
)

IN_CASE = "ACC-IN-CASE"
IN_CASE_2 = "ACC-IN-CASE-2"
OUT_OF_CASE = "ACC-OTHER-CASE"  # exists in the DB, NOT linked to our case
CASE_ID = "CASE-UNDER-TEST"
OTHER_CASE_ID = "CASE-SOMEONE-ELSES"


@pytest.fixture
def seeded(session: Session) -> Session:
    users = UserRepository(session)
    users.create(
        user_id="U1", username="inv1", email="inv1@example.com", password_hash="x",
        role=UserRole.INVESTIGATOR, full_name="Investigator One",
        actor_type=ActorType.SYSTEM, actor_id=None,
    )
    CustomerRepository(session).create(
        customer_id="CUST1",
        name=PII_NAME, pan=PII_PAN, aadhaar=PII_AADHAAR, phone=PII_PHONE,
        email=PII_EMAIL, address=PII_ADDRESS, employer=PII_EMPLOYER,
        entity_type=EntityType.INDIVIDUAL, risk_rating=RiskLevel.HIGH,
        occupation="Trader", declared_annual_income=500_000.0, income_bracket="5-10L",
        actor_type=ActorType.SYSTEM, actor_id=None,
    )
    accounts = AccountRepository(session)
    for acct in (IN_CASE, IN_CASE_2, OUT_OF_CASE):
        accounts.create(
            account_id=acct, customer_id="CUST1", branch_city="Mumbai",
            current_risk_score=71.0, actor_type=ActorType.SYSTEM, actor_id=None,
        )
    now = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    TransactionRepository(session).create(
        txn_id="T1", source_account=IN_CASE_2, dest_account=IN_CASE,
        amount=250_000.0, channel=Channel.NEFT, txn_type="TRANSFER",
        timestamp=now, is_laundering=False, ingested_at=now,
        actor_type=ActorType.SYSTEM, actor_id=None,
    )
    cases = CaseRepository(session)
    for cid, primary in ((CASE_ID, IN_CASE), (OTHER_CASE_ID, OUT_OF_CASE)):
        cases.create(
            case_id=cid, primary_account_id=primary, status=CaseStatus.IN_PROGRESS,
            level=CaseLevel.L1, priority=Priority.P1, risk_score=80.0,
            assigned_to="U1", actor_type=ActorType.SYSTEM, actor_id=None,
        )
    links = CaseAccountRepository(session)
    for acct in (IN_CASE, IN_CASE_2):
        links.add_account(case_id=CASE_ID, account_id=acct,
                          actor_type=ActorType.SYSTEM, actor_id=None)
    links.add_account(case_id=OTHER_CASE_ID, account_id=OUT_OF_CASE,
                      actor_type=ActorType.SYSTEM, actor_id=None)
    session.commit()
    return session


@pytest.fixture
def catalog(seeded: Session) -> ToolCatalog:
    return build_tool_catalog(
        seeded, CASE_ID, actor_type=ActorType.INVESTIGATOR, actor_id="U1"
    )


# ── the catalog is fixed ──────────────────────────────────────────────────


def test_catalog_exposes_exactly_the_twelve_named_tools(catalog: ToolCatalog) -> None:
    assert len(TOOL_NAMES) == 12
    assert [s["function"]["name"] for s in catalog.schemas()] == list(TOOL_NAMES)


def test_schemas_are_strict_and_closed(catalog: ToolCatalog) -> None:
    for schema in catalog.schemas():
        fn = schema["function"]
        params = fn["parameters"]
        assert fn["strict"] is True, fn["name"]
        assert params["additionalProperties"] is False, fn["name"]
        # OpenAI strict mode requires EVERY property to be listed in `required`;
        # optionality is expressed as a nullable type instead. A schema that
        # violates this is rejected at request time, so assert it here rather
        # than discovering it on a live call.
        assert sorted(params["required"]) == sorted(params["properties"]), fn["name"]


# ── property 1: the model cannot choose the case ──────────────────────────


def test_no_tool_schema_exposes_case_id(catalog: ToolCatalog) -> None:
    # The core containment property. `case_id` is bound at construction, so the
    # model has no vocabulary for "look at a different case" — it isn't a rule it
    # might break, it's a sentence it cannot form.
    for schema in catalog.schemas():
        props = schema["function"]["parameters"]["properties"]
        assert "case_id" not in props, f"{schema['function']['name']} exposes case_id"


def test_dispatch_rejects_a_forged_case_id_argument(catalog: ToolCatalog) -> None:
    # What a prompt-injected model would actually try.
    with pytest.raises(ToolError, match="unexpected argument"):
        catalog.dispatch("get_case_summary", {"case_id": OTHER_CASE_ID})


def test_dispatch_reports_the_bound_case_not_a_requested_one(catalog: ToolCatalog) -> None:
    assert catalog.dispatch("get_case_summary")["case_id"] == CASE_ID
    assert catalog.case_id == CASE_ID


# ── property 2: account ids are validated against the case's scope ────────


@pytest.mark.parametrize(
    "tool",
    ["get_account_facts", "get_money_flow", "get_ego_graph", "get_timeline",
     "get_behavior_analysis", "get_previous_alerts", "search_transactions"],
)
def test_out_of_case_account_returns_an_error_never_data(
    catalog: ToolCatalog, tool: str
) -> None:
    # OUT_OF_CASE is a real account on a real (other) case. Reaching it through
    # this catalog would be a cross-case leak — exactly what decision 5's
    # case-scoped-ego-graph boundary exists to prevent.
    with pytest.raises(ToolError) as exc:
        catalog.dispatch(tool, {"account_id": OUT_OF_CASE})
    assert OUT_OF_CASE in str(exc.value)


def test_scope_error_does_not_disclose_whether_the_account_exists(
    catalog: ToolCatalog
) -> None:
    # A real-but-out-of-scope account and a wholly nonexistent one must be
    # indistinguishable, or the error message becomes an oracle the model can
    # use to enumerate accounts it was never allowed to see.
    with pytest.raises(ToolError) as real:
        catalog.dispatch("get_account_facts", {"account_id": OUT_OF_CASE})
    with pytest.raises(ToolError) as fake:
        catalog.dispatch("get_account_facts", {"account_id": "NO-SUCH-ACCOUNT"})
    strip = lambda m: str(m).replace(OUT_OF_CASE, "X").replace("NO-SUCH-ACCOUNT", "X")  # noqa: E731
    assert strip(real.value) == strip(fake.value)


def test_in_case_account_is_accepted(catalog: ToolCatalog) -> None:
    facts = catalog.dispatch("get_account_facts", {"account_id": IN_CASE})
    assert facts["account_id"] == IN_CASE


# ── property 3: tools return structured facts, never prose ────────────────


def test_every_tool_returns_a_fact_dict(catalog: ToolCatalog) -> None:
    for name in TOOL_NAMES:
        args: dict[str, Any] = {}
        props = next(
            s["function"]["parameters"]["properties"]
            for s in catalog.schemas()
            if s["function"]["name"] == name
        )
        if "account_id" in props:
            args["account_id"] = IN_CASE
        result = catalog.dispatch(name, args)
        assert isinstance(result, dict), name
        assert not isinstance(result, str), name


def test_money_flow_hands_over_precomputed_percentages(catalog: ToolCatalog) -> None:
    # The model must never have to divide two numbers and then cite a figure no
    # tool produced — that claim would fail slice 3's citation check.
    flow = catalog.dispatch("get_money_flow", {"account_id": IN_CASE})
    for node in flow.get("sources", []) + flow.get("destinations", []):
        assert "pct_of_inflow" in node or "pct_of_outflow" in node


# ── unknown tools / arguments ─────────────────────────────────────────────


def test_unknown_tool_raises(catalog: ToolCatalog) -> None:
    with pytest.raises(ToolError, match="unknown tool"):
        catalog.dispatch("drop_all_cases", {})


def test_unknown_argument_raises(catalog: ToolCatalog) -> None:
    with pytest.raises(ToolError, match="unexpected argument"):
        catalog.dispatch("get_account_facts", {"account_id": IN_CASE, "limit": 999})


def test_null_arguments_fall_back_to_server_defaults(catalog: ToolCatalog) -> None:
    # Strict mode forces the model to send every key, so it sends nulls for the
    # ones it doesn't care about. Those must mean "use the default", not
    # "filter on None".
    result = catalog.dispatch(
        "search_transactions",
        {"account_id": None, "min_amount": None, "max_amount": None,
         "direction": None, "limit": None},
    )
    assert "items" in result and "total_count" in result


def test_account_facts_precomputes_the_income_ratio_so_the_model_never_derives_it(
    catalog: ToolCatalog,
) -> None:
    # Live measurement (METRICS.md §13): the model reliably states inflows as a
    # percentage of declared income — it did so even when the system prompt
    # explicitly forbade computing new numbers — and the grounding validator
    # rejected the claim every time, correctly, because the ratio was the model's
    # own arithmetic.
    #
    # The answer to "the model keeps deriving X" is never to relax the gate; it is
    # to make a tool compute X. Then the figure is a citable fact with auditable
    # provenance instead of a number nobody can check. Same precedent as
    # get_money_flow returning pct_of_total.
    facts = catalog.dispatch("get_account_facts", {"account_id": IN_CASE})
    # 250,000 inflow against 500,000 declared income.
    assert facts["inflow_pct_of_declared_income"] == 50.0


# ── code-review regressions ───────────────────────────────────────────────


def test_dispatch_gates_pii_at_the_point_of_egress(catalog: ToolCatalog, seeded: Session) -> None:
    """Code-review finding: the PII gate ran only at PERSIST time, inside
    `gateway.generate_and_persist_explanation`.

    But in a tool-calling loop the tool results are shipped to the model as
    `role: "tool"` messages long before anything is persisted — so every tool
    payload reached the third-party model without ever passing the gate. The check
    was in the wrong place, and a Phase 9 agent would have sailed straight past it.

    It now runs on `dispatch`, where egress actually begins, so no loop — present
    or future — can bypass it by construction rather than by remembering to.
    """
    from orchestration.redaction import PIIEgressError

    # Force a tool to leak: monkeypatching the handler is the closest stand-in for
    # a future tool whose author forgets to shape the payload (which is exactly
    # what build_case_relationship_graph did with customer.name).
    catalog._tools["get_case_summary"] = Tool(
        name="get_case_summary",
        description="x",
        properties={},
        handler=lambda: {"case_id": CASE_ID, "oops_customer_name": PII_NAME},
    )
    with pytest.raises(PIIEgressError):
        catalog.dispatch("get_case_summary")


def test_get_network_risk_is_read_only(catalog: ToolCatalog, seeded: Session) -> None:
    # Code-review finding: this lazily called compute_network_risk, which ends in
    # CaseRepository.update() -> writes the case row AND an audit_log entry stamped
    # with the investigator's actor_id. A model calling a "read-only fact tool"
    # would have mutated case state and forged an audit entry reading as though the
    # human did it. A fact tool reads facts; scoring is a human-attributed action.
    from db.models.investigation import Case
    from db.models.platform import AuditLog

    audit_before = seeded.query(AuditLog).count()

    result = catalog.dispatch("get_network_risk")

    # A null score is an honest fact the model can state, not a licence to compute.
    assert result["network_risk_score"] is None
    assert result["computed"] is False
    assert seeded.query(Case).filter_by(case_id=CASE_ID).one().network_risk_score is None
    assert seeded.query(AuditLog).count() == audit_before, "a read-only tool wrote an audit row"
