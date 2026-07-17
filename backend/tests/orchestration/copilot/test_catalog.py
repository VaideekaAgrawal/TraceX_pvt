"""CopilotCatalog — ROADMAP Phase 10. Mostly security tests: the model can only
touch the user's own cases, never sees a name, and cannot read note free text."""
from __future__ import annotations

import json

import pytest
from sqlalchemy.orm import Session

from db.models.platform import User
from db.repositories.investigation import NoteRepository
from orchestration.copilot import scoping
from orchestration.copilot.catalog import CopilotCatalog
from orchestration.tools.catalog import ToolError


@pytest.fixture
def catalog(session: Session, investigator: User) -> CopilotCatalog:
    return CopilotCatalog(session, investigator, scoping.accessible_case_ids(session, investigator))


def test_schemas_are_strict_and_closed(catalog: CopilotCatalog) -> None:
    for schema in catalog.schemas():
        fn = schema["function"]
        params = fn["parameters"]
        assert fn["strict"] is True, fn["name"]
        assert params["additionalProperties"] is False, fn["name"]
        assert sorted(params["required"]) == sorted(params["properties"]), fn["name"]


def test_no_case_id_is_ever_bound_only_validated(catalog: CopilotCatalog) -> None:
    # Cross-case: case_id is an ARGUMENT on the case tools (unlike Phase 9).
    names = {s["function"]["name"]: s for s in catalog.schemas()}
    assert "case_id" in names["get_case_overview"]["function"]["parameters"]["properties"]


def test_list_my_cases_returns_only_mine_and_no_names(catalog: CopilotCatalog) -> None:
    result = catalog.dispatch("list_my_cases")
    assert {c["case_id"] for c in result["cases"]} == {"CASE-MINE"}
    assert "Rajesh" not in json.dumps(result)


def test_a_case_outside_scope_is_rejected(catalog: CopilotCatalog) -> None:
    with pytest.raises(ToolError):
        catalog.dispatch("get_case_overview", {"case_id": "CASE-THEIRS"})


def test_an_unknown_case_is_rejected_the_same_way(catalog: CopilotCatalog) -> None:
    with pytest.raises(ToolError):
        catalog.dispatch("get_case_overview", {"case_id": "NO-SUCH-CASE"})


def test_in_scope_case_overview_works(catalog: CopilotCatalog) -> None:
    assert catalog.dispatch("get_case_overview", {"case_id": "CASE-MINE"})["case_id"] == "CASE-MINE"


def test_account_facts_returns_customer_id_never_a_name(catalog: CopilotCatalog) -> None:
    result = catalog.dispatch(
        "get_account_facts", {"case_id": "CASE-MINE", "account_id": "ACC-MINE"}
    )
    assert result["customer"]["customer_id"] == "CUST-REHY-1"
    assert "Rajesh" not in json.dumps(result)


def test_write_case_note_saves_a_copilot_note(catalog: CopilotCatalog, session: Session) -> None:
    result = catalog.dispatch(
        "write_case_note", {"case_id": "CASE-MINE", "note": "Follow up on the wire chain"}
    )
    assert result["saved"] is True
    notes = NoteRepository(session).list_for_case("CASE-MINE")
    assert any(
        n.body == "Follow up on the wire chain" and str(n.source) == "COPILOT" for n in notes
    )


def test_write_note_to_a_foreign_case_is_rejected(catalog: CopilotCatalog) -> None:
    with pytest.raises(ToolError):
        catalog.dispatch("write_case_note", {"case_id": "CASE-THEIRS", "note": "x"})


def test_there_is_no_note_reading_tool(catalog: CopilotCatalog) -> None:
    # Decision 10: notes.body never enters a prompt, so no tool exposes it.
    names = [s["function"]["name"] for s in catalog.schemas()]
    assert "write_case_note" in names
    assert not any("read" in n and "note" in n for n in names)
