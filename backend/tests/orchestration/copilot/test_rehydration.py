"""PII re-hydration — ROADMAP Phase 10, decision 9."""
from __future__ import annotations

from sqlalchemy.orm import Session

from db.models.platform import User
from orchestration.copilot import rehydration


def test_collect_customer_ids_finds_customer_id_keys_only() -> None:
    facts = {
        "get_account_facts(account_id=A).customer.customer_id": "CUST1",
        "get_case_summary.account_ids[0]": "ACC9",  # not a customer_id
        "get_account_facts(account_id=A).total_in": 5000.0,
        "customer_id": "CUST2",
    }
    assert rehydration.collect_customer_ids(facts) == {"CUST1", "CUST2"}


def test_build_name_map_resolves_real_names(session: Session, investigator: User) -> None:
    assert rehydration.build_name_map(session, {"CUST-REHY-1"}) == {
        "CUST-REHY-1": "Rajesh Kumar Sharma"
    }


def test_build_name_map_empty_input() -> None:
    # No session touched when there's nothing to resolve.
    assert rehydration.build_name_map(None, set()) == {}  # type: ignore[arg-type]


def test_rehydrate_shows_name_and_keeps_the_id() -> None:
    out = rehydration.rehydrate(
        "Account for CUST-REHY-1 is high risk.", {"CUST-REHY-1": "Rajesh Kumar Sharma"}
    )
    assert out == "Account for Rajesh Kumar Sharma (CUST-REHY-1) is high risk."


def test_rehydrate_is_a_noop_without_a_map() -> None:
    assert rehydration.rehydrate("nothing to do", {}) == "nothing to do"
