"""Shared fixtures for the Phase 9 recommendation tests: a case with a real
layering alert, so `rule_grounding` and the engine have something to ground on."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from db.enums import (
    ActorType,
    CaseLevel,
    CaseStatus,
    Channel,
    DetectionType,
    EntityType,
    Priority,
    RiskLevel,
    UserRole,
)
from db.repositories.detection import AlertRepository
from db.repositories.investigation import CaseAccountRepository, CaseRepository
from db.repositories.platform import UserRepository
from db.repositories.reference import AccountRepository, CustomerRepository, TransactionRepository
from detection.rules.seed import seed_builtin_rules

CASE_ID = "CASE-REC-1"
ACC1 = "ACC-REC-1"
ACC2 = "ACC-REC-2"


@pytest.fixture
def case_with_layering_alert(session: Session) -> Session:
    """A case linked to two accounts with a single high-severity LAYERING alert
    naming the built-in layering rule."""
    UserRepository(session).create(
        user_id="U1", username="inv1", email="inv1@example.com", password_hash="x",
        role=UserRole.INVESTIGATOR, full_name="Investigator One",
        actor_type=ActorType.SYSTEM, actor_id=None,
    )
    CustomerRepository(session).create(
        customer_id="CUST1", name="Corp #1", entity_type=EntityType.BUSINESS,
        risk_rating=RiskLevel.HIGH, occupation="Trading", declared_annual_income=500_000.0,
        income_bracket="5-10L", actor_type=ActorType.SYSTEM, actor_id=None,
    )
    accounts = AccountRepository(session)
    for acct in (ACC1, ACC2):
        accounts.create(
            account_id=acct, customer_id="CUST1", branch_city="Mumbai",
            current_risk_score=71.0, actor_type=ActorType.SYSTEM, actor_id=None,
        )
    now = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    TransactionRepository(session).create(
        txn_id="T1", source_account=ACC2, dest_account=ACC1,
        amount=250_000.0, channel=Channel.NEFT, txn_type="TRANSFER",
        timestamp=now, is_laundering=False, ingested_at=now,
        actor_type=ActorType.SYSTEM, actor_id=None,
    )
    CaseRepository(session).create(
        case_id=CASE_ID, primary_account_id=ACC1, status=CaseStatus.IN_PROGRESS,
        level=CaseLevel.L1, priority=Priority.P1, risk_score=80.0,
        assigned_to="U1", actor_type=ActorType.SYSTEM, actor_id=None,
    )
    links = CaseAccountRepository(session)
    for acct in (ACC1, ACC2):
        links.add_account(case_id=CASE_ID, account_id=acct,
                          actor_type=ActorType.SYSTEM, actor_id=None)
    seed_builtin_rules(session, actor_type=ActorType.SYSTEM, actor_id=None)
    AlertRepository(session).create(
        alert_id="AL1", detection_type=DetectionType.layering,
        primary_account_id=ACC1, account_ids=[ACC1, ACC2],
        score=0.82, risk_score=80.0, severity=RiskLevel.HIGH, priority=Priority.P1,
        status="open", source="pipeline", case_id=CASE_ID, rule_ids=["builtin_layering"],
        actor_type=ActorType.SYSTEM, actor_id=None,
    )
    session.commit()
    return session
