"""Shared fixtures for the Phase 10 Copilot tests: an investigator with one
assigned case (a customer that HAS a real name, so re-hydration has something to
resolve) and a second case assigned to someone else (out of scope)."""
from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from db.enums import (
    ActorType,
    CaseLevel,
    CaseStatus,
    EntityType,
    Priority,
    RiskLevel,
    UserRole,
)
from db.models.platform import User
from db.repositories.investigation import CaseAccountRepository, CaseRepository
from db.repositories.platform import UserRepository
from db.repositories.reference import AccountRepository, CustomerRepository

MY_CASE = "CASE-MINE"
OTHER_CASE = "CASE-THEIRS"
MY_ACCOUNT = "ACC-MINE"
CUSTOMER_ID = "CUST-REHY-1"
CUSTOMER_NAME = "Rajesh Kumar Sharma"


@pytest.fixture
def investigator(session: Session) -> User:
    users = UserRepository(session)
    me = users.create(
        user_id="U-INV", username="inv", email="inv@example.com", password_hash="x",
        role=UserRole.INVESTIGATOR, full_name="Inv One",
        actor_type=ActorType.SYSTEM, actor_id=None,
    )
    users.create(
        user_id="U-OTHER", username="other", email="other@example.com", password_hash="x",
        role=UserRole.INVESTIGATOR, full_name="Other",
        actor_type=ActorType.SYSTEM, actor_id=None,
    )
    CustomerRepository(session).create(
        customer_id=CUSTOMER_ID, name=CUSTOMER_NAME, entity_type=EntityType.INDIVIDUAL,
        risk_rating=RiskLevel.HIGH, occupation="Trader", declared_annual_income=500_000.0,
        income_bracket="5-10L", actor_type=ActorType.SYSTEM, actor_id=None,
    )
    AccountRepository(session).create(
        account_id=MY_ACCOUNT, customer_id=CUSTOMER_ID, branch_city="Mumbai",
        current_risk_score=71.0, actor_type=ActorType.SYSTEM, actor_id=None,
    )
    cases = CaseRepository(session)
    cases.create(
        case_id=MY_CASE, primary_account_id=MY_ACCOUNT, status=CaseStatus.IN_PROGRESS,
        level=CaseLevel.L1, priority=Priority.P1, risk_score=80.0,
        assigned_to="U-INV", actor_type=ActorType.SYSTEM, actor_id=None,
    )
    cases.create(
        case_id=OTHER_CASE, primary_account_id=MY_ACCOUNT, status=CaseStatus.IN_PROGRESS,
        level=CaseLevel.L1, priority=Priority.P1, risk_score=80.0,
        assigned_to="U-OTHER", actor_type=ActorType.SYSTEM, actor_id=None,
    )
    CaseAccountRepository(session).add_account(
        case_id=MY_CASE, account_id=MY_ACCOUNT, actor_type=ActorType.SYSTEM, actor_id=None
    )
    session.commit()
    return me
