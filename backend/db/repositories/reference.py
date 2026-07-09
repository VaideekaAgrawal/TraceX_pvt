"""
Repositories for `docs/DATA_SCHEMA.md` §3.1 reference/domain tables:
`customers`, `accounts`, `transactions`.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from db.enums import (
    AccountStatus,
    ActorType,
    Channel,
    EddStatus,
    EntityType,
    KycStatus,
    RiskLevel,
)
from db.models.reference import Account, Customer, Transaction
from db.repositories.base import UNSET, BaseRepository, collect_changes


class CustomerRepository(BaseRepository[Customer]):
    model = Customer
    entity_type = "customer"
    pk_attr = "customer_id"

    def create(
        self,
        *,
        customer_id: str,
        name: str,
        entity_type: EntityType,
        risk_rating: RiskLevel,
        pan: str | None = None,
        aadhaar: str | None = None,
        phone: str | None = None,
        email: str | None = None,
        address: str | None = None,
        occupation: str | None = None,
        declared_annual_income: float | None = None,
        income_bracket: str | None = None,
        employer: str | None = None,
        kyc_status: KycStatus = KycStatus.PENDING,
        edd_status: EddStatus = EddStatus.NOT_REQUIRED,
        pep_status: bool = False,
        sanction_status: bool = False,
        actor_type: ActorType,
        actor_id: str | None,
    ) -> Customer:
        customer = Customer(
            customer_id=customer_id,
            name=name,
            entity_type=entity_type,
            pan=pan,
            aadhaar=aadhaar,
            phone=phone,
            email=email,
            address=address,
            occupation=occupation,
            declared_annual_income=declared_annual_income,
            income_bracket=income_bracket,
            employer=employer,
            kyc_status=kyc_status,
            edd_status=edd_status,
            pep_status=pep_status,
            sanction_status=sanction_status,
            risk_rating=risk_rating,
        )
        return self._create(
            customer, actor_type=actor_type, actor_id=actor_id, action="customer_created"
        )

    def update(
        self,
        customer_id: str,
        *,
        actor_type: ActorType,
        actor_id: str | None,
        name: str = UNSET,
        pan: str | None = UNSET,
        aadhaar: str | None = UNSET,
        phone: str | None = UNSET,
        email: str | None = UNSET,
        address: str | None = UNSET,
        occupation: str | None = UNSET,
        declared_annual_income: float | None = UNSET,
        income_bracket: str | None = UNSET,
        employer: str | None = UNSET,
        kyc_status: KycStatus = UNSET,
        edd_status: EddStatus = UNSET,
        pep_status: bool = UNSET,
        sanction_status: bool = UNSET,
        risk_rating: RiskLevel = UNSET,
    ) -> Customer:
        customer = self.get(customer_id)
        if customer is None:
            raise ValueError(f"customer {customer_id!r} does not exist")
        changes = collect_changes(
            name=name,
            pan=pan,
            aadhaar=aadhaar,
            phone=phone,
            email=email,
            address=address,
            occupation=occupation,
            declared_annual_income=declared_annual_income,
            income_bracket=income_bracket,
            employer=employer,
            kyc_status=kyc_status,
            edd_status=edd_status,
            pep_status=pep_status,
            sanction_status=sanction_status,
            risk_rating=risk_rating,
        )
        return self._update(
            customer,
            changes,
            actor_type=actor_type,
            actor_id=actor_id,
            action="customer_updated",
        )


class AccountRepository(BaseRepository[Account]):
    model = Account
    entity_type = "account"
    pk_attr = "account_id"

    def create(
        self,
        *,
        account_id: str,
        customer_id: str | None = None,
        account_type: str = "savings",
        bank_name: str | None = None,
        bank_id: str | None = None,
        branch_city: str | None = None,
        status: AccountStatus = AccountStatus.ACTIVE,
        kyc_tier: str | None = None,
        opening_date: datetime | None = None,
        expected_monthly_volume: float | None = None,
        current_risk_score: float | None = None,
        actor_type: ActorType,
        actor_id: str | None,
    ) -> Account:
        account = Account(
            account_id=account_id,
            customer_id=customer_id,
            account_type=account_type,
            bank_name=bank_name,
            bank_id=bank_id,
            branch_city=branch_city,
            status=status,
            kyc_tier=kyc_tier,
            opening_date=opening_date,
            expected_monthly_volume=expected_monthly_volume,
            current_risk_score=current_risk_score,
        )
        return self._create(
            account, actor_type=actor_type, actor_id=actor_id, action="account_created"
        )

    def update(
        self,
        account_id: str,
        *,
        actor_type: ActorType,
        actor_id: str | None,
        customer_id: str | None = UNSET,
        account_type: str = UNSET,
        bank_name: str | None = UNSET,
        bank_id: str | None = UNSET,
        branch_city: str | None = UNSET,
        status: AccountStatus = UNSET,
        kyc_tier: str | None = UNSET,
        opening_date: datetime | None = UNSET,
        expected_monthly_volume: float | None = UNSET,
        current_risk_score: float | None = UNSET,
    ) -> Account:
        account = self.get(account_id)
        if account is None:
            raise ValueError(f"account {account_id!r} does not exist")
        changes = collect_changes(
            customer_id=customer_id,
            account_type=account_type,
            bank_name=bank_name,
            bank_id=bank_id,
            branch_city=branch_city,
            status=status,
            kyc_tier=kyc_tier,
            opening_date=opening_date,
            expected_monthly_volume=expected_monthly_volume,
            current_risk_score=current_risk_score,
        )
        return self._update(
            account, changes, actor_type=actor_type, actor_id=actor_id, action="account_updated"
        )

    def get_by_customer(self, customer_id: str) -> list[Account]:
        """All accounts belonging to one customer — the 1:N read the schema
        doc's ER overview calls out (`customers ──1:N── accounts`)."""
        stmt = select(Account).where(Account.customer_id == customer_id)
        return list(self.session.scalars(stmt))


class TransactionRepository(BaseRepository[Transaction]):
    """Transactions are an immutable ledger (doc §3.1: written once at
    ingest, no `updated_at`) — this repository intentionally has no
    `update()` method, only `create`/`get`/list reads."""

    model = Transaction
    entity_type = "transaction"
    pk_attr = "txn_id"

    def create(
        self,
        *,
        txn_id: str,
        timestamp: datetime,
        source_account: str,
        dest_account: str,
        amount: float,
        channel: Channel,
        is_laundering: int,
        ingested_at: datetime,
        amount_received: float | None = None,
        currency: str = "INR",
        txn_type: str = "transfer",
        narration: str | None = None,
        purpose: str | None = None,
        merchant_type: str | None = None,
        from_bank: str | None = None,
        to_bank: str | None = None,
        reference_id: str | None = None,
        source_file_hash: str | None = None,
        actor_type: ActorType,
        actor_id: str | None,
    ) -> Transaction:
        txn = Transaction(
            txn_id=txn_id,
            timestamp=timestamp,
            source_account=source_account,
            dest_account=dest_account,
            amount=amount,
            amount_received=amount_received,
            currency=currency,
            channel=channel,
            txn_type=txn_type,
            narration=narration,
            purpose=purpose,
            merchant_type=merchant_type,
            is_laundering=is_laundering,
            from_bank=from_bank,
            to_bank=to_bank,
            reference_id=reference_id,
            source_file_hash=source_file_hash,
            ingested_at=ingested_at,
        )
        return self._create(
            txn, actor_type=actor_type, actor_id=actor_id, action="transaction_created"
        )

    def list_for_account_in_window(
        self,
        account_id: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        as_source: bool = True,
        as_dest: bool = True,
        limit: int = 500,
    ) -> list[Transaction]:
        """Transactions touching `account_id` (as source and/or dest) within
        `[start, end]`, ordered by timestamp — the read pattern the two
        composite indexes `(source_account, timestamp)`/`(dest_account,
        timestamp)` exist for (ego-graph extraction, timeline
        reconstruction, doc §3.1)."""
        if not as_source and not as_dest:
            raise ValueError("at least one of as_source/as_dest must be True")

        clauses = []
        if as_source:
            clauses.append(Transaction.source_account == account_id)
        if as_dest:
            clauses.append(Transaction.dest_account == account_id)

        side_filter = clauses[0] if len(clauses) == 1 else (clauses[0] | clauses[1])
        stmt = select(Transaction).where(side_filter)
        if start is not None:
            stmt = stmt.where(Transaction.timestamp >= start)
        if end is not None:
            stmt = stmt.where(Transaction.timestamp <= end)
        stmt = stmt.order_by(Transaction.timestamp.asc()).limit(limit)
        return list(self.session.scalars(stmt))
