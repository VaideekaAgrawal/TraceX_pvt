"""
Grounding-contract tests — ROADMAP Phase 8, committed decision 8.

The property under test is the one we intend to say out loud to a bank: *the
model cannot assert a number it was not handed.* So most of these tests are
adversarial — they play the part of a model that is fabricating — and each one
names the specific hole it closes. A test suite that only checks the happy path
would prove the validator runs, not that it works.
"""
from __future__ import annotations

import pytest

from orchestration.grounding import (
    SUBMIT_TOOL_NAME,
    Citation,
    Claim,
    FactBundle,
    GroundingError,
    claims_schema,
    parse_response,
    submit_tool,
    submit_tool_choice,
    validate,
)


@pytest.fixture
def bundle() -> FactBundle:
    b = FactBundle()
    b.add_tool_result(
        "get_account_facts",
        {
            "account_id": "A1",
            "total_in": 10_000.0,
            "total_out": 0.0,
            "txn_count": 1,
            "counterparty_count": 1,
            "current_risk_score": 71.0,
            "customer": {"risk_rating": "HIGH", "declared_annual_income": 500_000.0},
        },
    )
    b.add_tool_result(
        "get_money_flow",
        {
            "center": "A1",
            "sources": [{"account_id": "A2", "total_amount": 10_000.0, "pct_of_inflow": 100.0}],
            "destinations": [],
        },
    )
    b.add_tool_result("get_network_risk", {"network_risk_score": None})
    return b


def _claim(statement: str, *citations: tuple[str, object]) -> Claim:
    return Claim(
        statement=statement,
        citations=tuple(Citation(fact_key=k, value=v) for k, v in citations),
    )


# ── the fact bundle ───────────────────────────────────────────────────────


def test_bundle_flattens_nested_dicts_and_lists_to_citable_leaves(bundle: FactBundle) -> None:
    facts = bundle.facts
    assert facts["get_account_facts.total_in"] == 10_000.0
    assert facts["get_account_facts.customer.risk_rating"] == "HIGH"
    # Indexed so a claim can cite ONE counterparty, not "the sources list".
    assert facts["get_money_flow.sources[0].pct_of_inflow"] == 100.0


def test_bundle_distinguishes_a_missing_fact_from_a_null_one(bundle: FactBundle) -> None:
    # `network_risk_score` is legitimately null on an unscored case. A validator
    # that conflated "no such fact" with "the fact is None" would either reject
    # honest claims or, worse, accept invented ones citing keys that don't exist.
    found, value = bundle.resolve("get_network_risk.network_risk_score")
    assert (found, value) == (True, None)

    found, value = bundle.resolve("get_network_risk.nonexistent")
    assert (found, value) == (False, None)


def test_bundle_records_tools_called(bundle: FactBundle) -> None:
    # Populates `ai_interactions.tools_called`, null since Phase 1. Records each
    # CALL with its arguments (see the audit-trail regression test below), not a
    # de-duplicated list of names.
    assert bundle.tool_names == ["get_account_facts", "get_money_flow", "get_network_risk"]
    assert [c["tool"] for c in bundle.tools_called] == [
        "get_account_facts",
        "get_money_flow",
        "get_network_risk",
    ]


# ── gate 1: the citation must resolve ─────────────────────────────────────


def test_rejects_a_claim_citing_a_fact_that_does_not_exist(bundle: FactBundle) -> None:
    # The crudest fabrication: invent a source.
    result = validate(
        [_claim("The account sent Rs.4,000,000 offshore.", ("get_account_facts.offshore", 4e6))],
        bundle,
    )
    assert not result.ok
    assert "unknown fact_key" in result.rejected[0].reason
    assert result.narrative() == ""  # nothing survives to reach a human


# ── gate 2: the cited value must be what the tool actually said ───────────


def test_rejects_a_claim_that_misreports_a_real_facts_value(bundle: FactBundle) -> None:
    # Subtler: cite a REAL key, but lie about what it holds. Gate 1 alone would
    # wave this through, which is exactly why gate 2 exists.
    result = validate(
        [_claim("Inflows totalled Rs.9,400,000.", ("get_account_facts.total_in", 9_400_000.0))],
        bundle,
    )
    assert not result.ok
    assert "misreports" in result.rejected[0].reason
    assert "10000.0" in result.rejected[0].reason  # tells the auditor the truth


# ── gate 3: every number in the prose must be grounded ────────────────────


def test_rejects_an_ungrounded_number_hiding_in_correctly_cited_prose(
    bundle: FactBundle,
) -> None:
    # THE hole gate 3 closes, and the most dangerous case in the whole module:
    # every citation is real and every cited value is correct, so gates 1 and 2
    # both pass — but the sentence a human actually reads contains "37
    # counterparties", a number no tool ever produced. Structured citations being
    # honest does not make the prose honest.
    result = validate(
        [
            _claim(
                "The account received Rs.10,000 across 37 counterparties.",
                ("get_account_facts.total_in", 10_000.0),
                ("get_account_facts.counterparty_count", 1),
            )
        ],
        bundle,
    )
    assert not result.ok
    assert "ungrounded number" in result.rejected[0].reason
    assert "37" in result.rejected[0].reason


def test_rejects_a_number_the_model_derived_itself(bundle: FactBundle) -> None:
    # 10,000 / 500,000 = 2%. Both inputs are real and correctly cited, but the
    # ratio is the MODEL's arithmetic, and model arithmetic is precisely the
    # thing nobody can audit. If a ratio is wanted, a tool must compute it —
    # which is why `get_money_flow` already returns `pct_of_total`.
    result = validate(
        [
            _claim(
                "Inflows of Rs.10,000 represent 2.0 percent of the declared "
                "annual income of Rs.500,000.",
                ("get_account_facts.total_in", 10_000.0),
                ("get_account_facts.customer.declared_annual_income", 500_000.0),
            )
        ],
        bundle,
    )
    assert not result.ok
    assert "ungrounded number" in result.rejected[0].reason


def test_accepts_a_percentage_that_a_tool_computed(bundle: FactBundle) -> None:
    # The flip side, and the reason the rule above is livable: the same claim is
    # fine when the percentage came from a tool instead of the model.
    result = validate(
        [
            _claim(
                "Account A2 supplied Rs.10,000, which is 100.0 percent of inflow.",
                ("get_money_flow.sources[0].total_amount", 10_000.0),
                ("get_money_flow.sources[0].pct_of_inflow", 100.0),
            )
        ],
        bundle,
    )
    assert result.ok, [str(r) for r in result.rejected]


# ── the validator must not be pedantic ────────────────────────────────────


def test_numeric_formatting_differences_are_not_fabrications(bundle: FactBundle) -> None:
    # 71 vs 71.0, and "10,000" with a thousands separator, are the SAME numbers.
    # Rejecting them would be pedantry, and a validator that cries wolf is a
    # validator someone switches off.
    result = validate(
        [
            _claim(
                "Risk score is 71 and inflows are Rs.10,000.",
                ("get_account_facts.current_risk_score", "71"),
                ("get_account_facts.total_in", "10,000"),
            )
        ],
        bundle,
    )
    assert result.ok, [str(r) for r in result.rejected]


def test_identifiers_and_dates_are_not_read_as_numeric_claims(bundle: FactBundle) -> None:
    # An explanation must be able to name the account it is about. If `A1` or an
    # ISO date tripped gate 3, every good explanation would be rejected for
    # mentioning its own subject.
    result = validate(
        [
            _claim(
                "Account A1 (reviewed 2026-03-01, ref DEMO-ACC-004) shows "
                "Rs.10,000 of inflow.",
                ("get_account_facts.total_in", 10_000.0),
            )
        ],
        bundle,
    )
    assert result.ok, [str(r) for r in result.rejected]


def test_a_timestamp_in_prose_is_not_an_ungrounded_number(bundle: FactBundle) -> None:
    # REGRESSION, and it came from a live run rather than my imagination: the
    # model wrote "...of 250000.0 on 2026-03-01 12:00:00", and gate 3 rejected the
    # whole correct claim because it read the `12` out of the CLOCK TIME as a
    # fabricated figure. A date says when, not how much.
    #
    # This is the most important calibration test in the file. A validator that
    # rejects true statements is not "safely strict" — it is one that people turn
    # off, and turning it off takes the real control with it.
    result = validate(
        [
            _claim(
                "The account received Rs.10,000 on 2026-03-01 12:00:00 from A2.",
                ("get_account_facts.total_in", 10_000.0),
            )
        ],
        bundle,
    )
    assert result.ok, [str(r) for r in result.rejected]


def test_a_month_name_date_in_prose_is_not_an_ungrounded_number(bundle: FactBundle) -> None:
    # Second live false rejection, same family: the model opened with "In March
    # 2026, the account received..." and gate 3 read the YEAR as a fabricated
    # quantity. AML narratives are full of periods; if every one of them tripped
    # the validator, the validator would be useless.
    result = validate(
        [
            _claim(
                "In March 2026, the account received inflows of Rs.10,000.",
                ("get_account_facts.total_in", 10_000.0),
            )
        ],
        bundle,
    )
    assert result.ok, [str(r) for r in result.rejected]


def test_a_bare_number_that_looks_like_a_year_is_still_checked(bundle: FactBundle) -> None:
    # The date exemption requires a MONTH NAME precisely so it can't be used as a
    # smuggling route: a naked 2026 with no month beside it is still a quantity,
    # and still has to be grounded.
    result = validate(
        [_claim("The account moved 2026 rupees.", ("get_account_facts.total_in", 10_000.0))],
        bundle,
    )
    assert not result.ok
    assert "ungrounded number" in result.rejected[0].reason


def test_gate_3_still_catches_a_fabrication_next_to_a_timestamp(bundle: FactBundle) -> None:
    # ...and the timestamp exemption must not become a smuggling route: a real
    # ungrounded number sitting beside a date is still caught.
    result = validate(
        [
            _claim(
                "On 2026-03-01 12:00:00 the account moved Rs.750,000.",
                ("get_account_facts.total_in", 10_000.0),
            )
        ],
        bundle,
    )
    assert not result.ok
    assert "ungrounded number" in result.rejected[0].reason
    assert "750000" in result.rejected[0].reason.replace(",", "")


def test_enum_values_match_case_insensitively(bundle: FactBundle) -> None:
    result = validate(
        [
            _claim(
                "The customer is rated high risk.",
                ("get_account_facts.customer.risk_rating", "high"),
            )
        ],
        bundle,
    )
    assert result.ok, [str(r) for r in result.rejected]


# ── partial failure is still failure ──────────────────────────────────────


def test_one_bad_claim_taints_the_response(bundle: FactBundle) -> None:
    # A partially-grounded answer is not a safe answer: the ungrounded sentence
    # is exactly the one an investigator has no way to check. `ok` is False, and
    # `narrative()` carries only what survived.
    result = validate(
        [
            _claim("Inflows were Rs.10,000.", ("get_account_facts.total_in", 10_000.0)),
            _claim("It also wired Rs.88,000 abroad.", ("get_account_facts.total_out", 88_000.0)),
        ],
        bundle,
    )
    assert not result.ok
    assert len(result.accepted) == 1
    assert len(result.rejected) == 1
    assert "88,000" not in result.narrative()
    assert "10,000" in result.narrative()


# ── parsing fails closed ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"claims": []},
        {"claims": [{"statement": "", "citations": []}]},
        {"claims": [{"statement": "no citations key"}]},
        {"claims": ["not an object"]},
    ],
)
def test_unparseable_response_raises_rather_than_degrading_to_zero_claims(
    payload: dict[str, object],
) -> None:
    # Fail CLOSED. If a malformed response quietly became "no claims", then
    # `GroundingResult.ok` — which is True when nothing was rejected — would
    # report a clean pass on a response we never actually understood.
    with pytest.raises(GroundingError):
        parse_response(payload)


def test_parse_response_round_trips_a_well_formed_reply() -> None:
    claims = parse_response(
        {
            "claims": [
                {
                    "statement": "Inflows were Rs.10,000.",
                    "citations": [{"fact_key": "get_account_facts.total_in", "value": 10000.0}],
                }
            ]
        }
    )
    assert claims[0].citations[0].fact_key == "get_account_facts.total_in"


# ── the schema itself forbids an uncited claim ────────────────────────────


def test_schema_makes_an_uncited_claim_unrepresentable() -> None:
    # Belt: the schema's minItems means the model cannot even express a claim
    # with no citations. Braces: `_reject_reason` checks for it anyway, because
    # strict-schema enforcement is a promise made by the thing being constrained.
    claim = claims_schema()["properties"]["claims"]["items"]
    assert claim["properties"]["citations"]["minItems"] == 1
    assert claim["additionalProperties"] is False
    assert sorted(claim["required"]) == ["citations", "statement"]


def test_the_answer_comes_back_as_a_forced_tool_call_not_response_format() -> None:
    # Regression test for a LIVE-VERIFIED provider defect (METRICS.md §13):
    # anthropic/claude-sonnet-4.5 advertises `structured_outputs` in OpenRouter's
    # supported_parameters and then SILENTLY IGNORES `response_format`, returning
    # prose with no error. Built on response_format, the grounding contract would
    # have degraded to nothing on the production model without a single alarm.
    #
    # Tool-calling is honoured everywhere we tested, so the answer arrives as a
    # forced call whose arguments ARE the structured answer. If someone later
    # "simplifies" this back to response_format, this test is the tripwire.
    tool = submit_tool()
    assert tool["function"]["name"] == SUBMIT_TOOL_NAME
    assert tool["function"]["strict"] is True
    # Same schema either way — only the transport differs.
    assert tool["function"]["parameters"] == claims_schema()
    # And the model is not merely offered the tool, it is forced into it: free
    # prose would bypass the validator entirely.
    assert submit_tool_choice() == {
        "type": "function",
        "function": {"name": SUBMIT_TOOL_NAME},
    }


# ── code-review regressions ───────────────────────────────────────────────


def test_same_tool_different_arguments_do_not_collide() -> None:
    """THE code-review finding, and the most severe bug in Phase 8.

    Facts used to be keyed by tool NAME only, so in a multi-account case — the
    normal shape of an AML investigation — `get_account_facts(A)` and
    `get_account_facts(B)` both wrote `get_account_facts.total_in` and the second
    silently overwrote the first.

    The consequence was not a crash. It was that a claim attributing account B's
    Rs 9,400,000 to account A passed ALL THREE GATES and reached the investigator,
    while the TRUE claim about account A was rejected as a misreport. A
    false-negative in the one control whose promise is *the model cannot assert a
    number it was not handed*, producing exactly the wrong-account/wrong-amount
    error that would be catastrophic in a SAR.

    Keys now carry the call's arguments, so the two accounts cannot be conflated.
    """
    b = FactBundle()
    b.add_tool_result("get_account_facts", {"total_in": 10_000.0}, {"account_id": "A"})
    b.add_tool_result("get_account_facts", {"total_in": 9_400_000.0}, {"account_id": "B"})

    # Both survive, addressable separately.
    assert b.facts["get_account_facts(account_id=A).total_in"] == 10_000.0
    assert b.facts["get_account_facts(account_id=B).total_in"] == 9_400_000.0

    # The TRUE claim about A is accepted...
    true_a = _claim(
        "Account A received Rs.10,000.",
        ("get_account_facts(account_id=A).total_in", 10_000.0),
    )
    assert validate([true_a], b).ok

    # ...and B's number can no longer be smuggled onto A: to state 9,400,000 the
    # model must cite B's key, and then the claim says so on its face.
    misattributed = _claim(
        "Account A received Rs.9,400,000.",
        ("get_account_facts(account_id=A).total_in", 9_400_000.0),
    )
    result = validate([misattributed], b)
    assert not result.ok
    assert "misreports" in result.rejected[0].reason


def test_repeating_a_call_with_identical_arguments_overwrites_in_place() -> None:
    # The one case the old behaviour got right, preserved: an identical re-call is
    # deterministic, so a second copy would only hand the model a stale key.
    b = FactBundle()
    b.add_tool_result("get_account_facts", {"total_in": 1.0}, {"account_id": "A"})
    b.add_tool_result("get_account_facts", {"total_in": 1.0}, {"account_id": "A"})
    assert len(b.facts) == 1


def test_tools_called_records_every_call_with_its_arguments_in_order() -> None:
    # Code-review finding: this used to be a de-duplicated list of bare NAMES, so
    # an interaction that inspected five accounts persisted `["get_account_facts"]`
    # and an auditor could not tell which accounts the model had actually looked
    # at. A trail that cannot reconstruct the calls is not an audit trail.
    b = FactBundle()
    b.add_tool_result("get_case_summary", {"case_id": "C1"})
    b.add_tool_result("get_account_facts", {"total_in": 1.0}, {"account_id": "A"})
    b.add_tool_result("get_account_facts", {"total_in": 2.0}, {"account_id": "B"})

    assert b.tools_called == [
        {"tool": "get_case_summary", "arguments": {}},
        {"tool": "get_account_facts", "arguments": {"account_id": "A"}},
        {"tool": "get_account_facts", "arguments": {"account_id": "B"}},
    ]
    assert b.tool_names == ["get_case_summary", "get_account_facts"]
