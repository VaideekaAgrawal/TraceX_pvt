"""`orchestration.tools.catalog` (ROADMAP Phase 8) -- each of the 9
wrappers, exercised via `ToolInvoker`: a happy path against a seeded case,
and a scope-violation case for the wrappers that add their own
out-of-case-scope check."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from db.enums import ActorType, CaseLevel, CaseStatus, Channel, EntityType, Priority, RiskLevel
from db.repositories.investigation import CaseAccountRepository, CaseRepository
from db.repositories.orchestration import RelationshipRepository
from db.repositories.reference import AccountRepository, CustomerRepository, TransactionRepository
from orchestration.tools import ToolInvoker


def _seed(session: Session) -> None:
    CustomerRepository(session).create(
        customer_id="CUST1", name="Amit Verma", entity_type=EntityType.INDIVIDUAL,
        risk_rating=RiskLevel.MEDIUM, pan="ABCDE1234F",
        actor_type=ActorType.SYSTEM, actor_id=None,
    )
    CustomerRepository(session).create(
        customer_id="CUST2", name="Priya Nair", entity_type=EntityType.INDIVIDUAL,
        risk_rating=RiskLevel.MEDIUM,
        actor_type=ActorType.SYSTEM, actor_id=None,
    )
    CustomerRepository(session).create(
        customer_id="CUST_OUT", name="Out Of Scope", entity_type=EntityType.INDIVIDUAL,
        risk_rating=RiskLevel.MEDIUM,
        actor_type=ActorType.SYSTEM, actor_id=None,
    )
    AccountRepository(session).create(
        account_id="A1", customer_id="CUST1", branch_city="Mumbai",
        actor_type=ActorType.SYSTEM, actor_id=None,
    )
    AccountRepository(session).create(
        account_id="A2", customer_id="CUST2", branch_city="Delhi",
        actor_type=ActorType.SYSTEM, actor_id=None,
    )
    AccountRepository(session).create(
        account_id="A_OUT", customer_id="CUST_OUT",
        actor_type=ActorType.SYSTEM, actor_id=None,
    )
    CaseRepository(session).create(
        case_id="CASE1", primary_account_id="A1", status=CaseStatus.NEW,
        level=CaseLevel.L1, priority=Priority.P2, actor_type=ActorType.SYSTEM, actor_id=None,
    )
    CaseAccountRepository(session).add_account(
        case_id="CASE1", account_id="A1", actor_type=ActorType.SYSTEM, actor_id=None
    )
    CaseAccountRepository(session).add_account(
        case_id="CASE1", account_id="A2", actor_type=ActorType.SYSTEM, actor_id=None
    )
    ts = datetime(2026, 1, 1, tzinfo=UTC)
    TransactionRepository(session).create(
        txn_id="T1", timestamp=ts, source_account="A2", dest_account="A1", amount=5_000.0,
        channel=Channel.NEFT, is_laundering=0, ingested_at=ts,
        actor_type=ActorType.SYSTEM, actor_id=None,
    )
    session.commit()


def _invoker(session: Session, case_id: str = "CASE1") -> ToolInvoker:
    return ToolInvoker(session, case_id, actor_type=ActorType.SYSTEM, actor_id=None)


def test_similar_cases_tool_happy_path(session: Session) -> None:
    _seed(session)
    result = _invoker(session).call("similar_cases", top_k=5)
    assert isinstance(result, list)  # empty corpus is fine, just must not crash


def test_similar_cases_tool_unknown_case_raises(session: Session) -> None:
    _seed(session)
    with pytest.raises(ValueError, match="does not exist"):
        _invoker(session, "NOT_A_CASE").call("similar_cases")


def test_path_recommendation_facts_tool_happy_path(session: Session) -> None:
    _seed(session)
    result = _invoker(session).call("path_recommendation_facts")
    assert result["case_id"] == "CASE1"
    assert result["primary_account_id"] == "A1"
    assert "fund_flow" in result
    assert "shared_attribute_adjacency" in result
    assert "prior_sar_adjacency" in result


def test_relationship_graph_tool_happy_path(session: Session) -> None:
    _seed(session)
    RelationshipRepository(session).create(
        entity_a="CUST1", entity_b="CUST_OUT", shared_attribute="pan",
        value_hash="hash1", confidence=0.95, method="shared_attribute_v1",
        actor_type=ActorType.SYSTEM, actor_id=None,
    )
    session.commit()

    result = _invoker(session).call("relationship_graph")
    assert result["case_id"] == "CASE1"
    node_ids = {n["customer_id"] for n in result["nodes"]}
    assert "CUST_OUT" in node_ids  # the 1-hop reveal


def test_ego_graph_tool_happy_path(session: Session) -> None:
    _seed(session)
    result = _invoker(session).call("ego_graph", account_id="A1", radius=1)
    assert result["center"] == "A1"


def test_ego_graph_tool_rejects_out_of_scope_account(session: Session) -> None:
    _seed(session)
    with pytest.raises(ValueError, match="not in case"):
        _invoker(session).call("ego_graph", account_id="A_OUT")


def test_network_risk_tool_lazy_computes_and_persists(session: Session) -> None:
    _seed(session)
    case = CaseRepository(session).get("CASE1")
    assert case is not None
    assert case.network_risk_score is None

    result = _invoker(session).call("network_risk")
    session.commit()
    assert result["network_risk_score"] is not None

    refreshed = CaseRepository(session).get("CASE1")
    assert refreshed is not None
    assert refreshed.network_risk_score == result["network_risk_score"]


def test_network_risk_tool_reads_cached_score_without_force(session: Session) -> None:
    _seed(session)
    invoker = _invoker(session)
    first = invoker.call("network_risk")
    session.commit()

    second = invoker.call("network_risk")
    assert second["network_risk_score"] == first["network_risk_score"]


def test_network_risk_tool_unknown_case_raises(session: Session) -> None:
    _seed(session)
    with pytest.raises(ValueError, match="does not exist"):
        _invoker(session, "NOT_A_CASE").call("network_risk")


def test_previous_alerts_summary_tool_happy_path(session: Session) -> None:
    _seed(session)
    result = _invoker(session).call("previous_alerts_summary", account_id="A1")
    assert result["total_prior_alerts"] == 0


def test_previous_alerts_summary_tool_rejects_out_of_scope_account(session: Session) -> None:
    _seed(session)
    with pytest.raises(ValueError, match="not in case"):
        _invoker(session).call("previous_alerts_summary", account_id="A_OUT")


def test_account_transaction_stats_tool_happy_path(session: Session) -> None:
    _seed(session)
    result = _invoker(session).call("account_transaction_stats", account_id="A1")
    assert result["total_in"] == 5_000.0
    assert result["txn_count"] == 1


def test_account_transaction_stats_tool_rejects_out_of_scope_account(session: Session) -> None:
    _seed(session)
    with pytest.raises(ValueError, match="not in case"):
        _invoker(session).call("account_transaction_stats", account_id="A_OUT")


def test_customer_profile_tool_happy_path(session: Session) -> None:
    _seed(session)
    result = _invoker(session).call("customer_profile", account_id="A1")
    assert result["account_id"] == "A1"
    assert result["name"] == "Amit Verma"


def test_customer_profile_tool_rejects_out_of_scope_account(session: Session) -> None:
    _seed(session)
    with pytest.raises(ValueError, match="not in case"):
        _invoker(session).call("customer_profile", account_id="A_OUT")


def test_search_transactions_tool_happy_path(session: Session) -> None:
    _seed(session)
    result = _invoker(session).call("search_transactions", account_id="A1")
    assert result["total_count"] == 1
    assert result["items"][0]["txn_id"] == "T1"


def test_search_transactions_tool_out_of_scope_account_yields_empty_scope(
    session: Session,
) -> None:
    _seed(session)
    # search_transactions is self-scoping (not a raising check) -- an
    # out-of-scope account_id narrows the query to an empty account set
    # rather than raising, matching investigation.transaction_search's own
    # documented contract.
    result = _invoker(session).call("search_transactions", account_id="A_OUT")
    assert result["items"] == []
    assert result["total_count"] == 0
