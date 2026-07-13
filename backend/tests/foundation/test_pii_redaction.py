"""`foundation.pii_redaction` -- redact/rehydrate round-trip, dedup-by-value,
non-declared fields pass through untouched, no persistence side effect
(ROADMAP Phase 8)."""
from __future__ import annotations

from foundation.pii_redaction import PIIField, pii_kind_for_column, redact_facts, rehydrate_text


def test_round_trip_redact_then_rehydrate_recovers_original() -> None:
    facts = {"account_id": "ACC123", "current_risk_score": 72.0}
    pii_fields = [PIIField(fact_key="account_id", kind="account_id")]

    redacted, token_map = redact_facts(facts, pii_fields)
    assert redacted["account_id"] != "ACC123"
    assert redacted["current_risk_score"] == 72.0

    response_text = f"Account {redacted['account_id']} looks suspicious."
    rehydrated = rehydrate_text(response_text, token_map)
    assert rehydrated == "Account ACC123 looks suspicious."


def test_non_declared_fields_pass_through_unchanged() -> None:
    facts = {"account_id": "ACC1", "score": 99.5, "role": "MULE"}
    pii_fields = [PIIField(fact_key="account_id", kind="account_id")]

    redacted, _ = redact_facts(facts, pii_fields)
    assert redacted["score"] == 99.5
    assert redacted["role"] == "MULE"


def test_same_real_value_under_two_fields_dedups_to_one_token() -> None:
    facts = {"primary_account_id": "ACC1", "source_account_id": "ACC1"}
    pii_fields = [
        PIIField(fact_key="primary_account_id", kind="account_id"),
        PIIField(fact_key="source_account_id", kind="account_id"),
    ]

    redacted, token_map = redact_facts(facts, pii_fields)
    assert redacted["primary_account_id"] == redacted["source_account_id"]
    assert len(token_map) == 1


def test_distinct_values_of_same_kind_get_distinct_tokens() -> None:
    facts = {"a": "ACC1", "b": "ACC2"}
    pii_fields = [
        PIIField(fact_key="a", kind="account_id"),
        PIIField(fact_key="b", kind="account_id"),
    ]

    redacted, token_map = redact_facts(facts, pii_fields)
    assert redacted["a"] != redacted["b"]
    assert redacted["a"] == "[ACCOUNT_ID_1]"
    assert redacted["b"] == "[ACCOUNT_ID_2]"
    assert len(token_map) == 2


def test_token_map_is_a_plain_dict_with_no_persistence_side_effect() -> None:
    facts = {"customer_name": "Amit Verma"}
    pii_fields = [PIIField(fact_key="customer_name", kind="name")]

    _, token_map = redact_facts(facts, pii_fields)
    assert isinstance(token_map, dict)
    assert token_map == {"[NAME_1]": "Amit Verma"}

    # A second, independent call must not remember anything from the first
    # -- counters/tokens are local to one redact_facts() call, not shared
    # module state.
    _, second_token_map = redact_facts(facts, pii_fields)
    assert second_token_map == token_map
    assert second_token_map is not token_map


def test_null_declared_field_is_left_alone_not_tokenized() -> None:
    facts = {"account_id": None}
    pii_fields = [PIIField(fact_key="account_id", kind="account_id")]

    redacted, token_map = redact_facts(facts, pii_fields)
    assert redacted["account_id"] is None
    assert token_map == {}


def test_declared_field_missing_from_facts_is_a_no_op() -> None:
    facts = {"other_key": "value"}
    pii_fields = [PIIField(fact_key="account_id", kind="account_id")]

    redacted, token_map = redact_facts(facts, pii_fields)
    assert redacted == facts
    assert token_map == {}


def test_rehydrate_text_with_no_matching_tokens_returns_text_unchanged() -> None:
    assert rehydrate_text("no tokens here", {"[ACCOUNT_ID_1]": "ACC1"}) == "no tokens here"


def test_pii_kind_for_column_registered_pair() -> None:
    assert pii_kind_for_column("customers", "name") is not None


def test_pii_kind_for_column_unregistered_pair_returns_none() -> None:
    assert pii_kind_for_column("accounts", "account_id") is None
