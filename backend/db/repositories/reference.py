"""
Repositories for `docs/DATA_SCHEMA.md` §3.1 reference/domain tables:
`customers`, `accounts`, `transactions`.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from sqlalchemy import ColumnElement, func, or_, select

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

    def list_by_ids(self, customer_ids: list[str]) -> list[Customer]:
        """Batched `customer_id IN (...)` lookup — avoids an N-query loop
        for callers that already have a small, bounded list of ids to
        resolve at once (code-review finding, Phase 5:
        `investigation.network_risk` used to `.get()` one customer per
        case-linked account). Assumes a case-scale id list (dozens, not
        export-scale thousands) — no chunking against SQLite's IN-clause
        parameter ceiling, the same "case-scoped is small" assumption
        `CaseAccountRepository.list_for_case` already relies on elsewhere
        in this codebase; a caller with an unbounded id list should chunk
        itself (see `detection.data._chunked` for that pattern)."""
        if not customer_ids:
            return []
        stmt = select(Customer).where(Customer.customer_id.in_(customer_ids))
        return list(self.session.scalars(stmt))

    def list_relationship_candidate_pool(self, *, limit: int = 5001) -> list[Customer]:
        """Relationship Explorer v1 discovery's candidate pool (ROADMAP
        Phase 7, `investigation.relationship_discovery`) — gated on `pan IS
        NOT NULL OR income_bracket IS NOT NULL`, not every customer.

        This is a real-data scale requirement, not just a perf shortcut:
        166,207 real ingested customers vs. ~200 Phase-1B demo KYC
        customers means an unbounded pairwise comparison is ~2.8x10^10
        pairs (never happening). A customer with neither field on file also
        has no genuine KYC-quality signal to corroborate a match on — the
        same "wait on data" reasoning `docs/DATA_SCHEMA.md` already applies
        to the device/IP attributes Relationship Explorer v1 defers
        entirely, applied here to the real customer population instead of
        a whole attribute.

        `limit` defaults to 5001 (`investigation.relationship_discovery.
        MAX_CANDIDATE_POOL_SIZE + 1`) so that module's caller can detect
        "the gated pool exceeds the safety valve" (`len(result) >
        MAX_CANDIDATE_POOL_SIZE`) from this single query's result, without a
        separate `COUNT(*)` round trip."""
        stmt = (
            select(Customer)
            .where(or_(Customer.pan.is_not(None), Customer.income_bracket.is_not(None)))
            .limit(limit)
        )
        return list(self.session.scalars(stmt))


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

    def list_by_ids(self, account_ids: list[str]) -> list[Account]:
        """Batched `account_id IN (...)` lookup — same reasoning as
        `CustomerRepository.list_by_ids` (code-review finding, Phase 5):
        avoids an N-query loop for a small, bounded id list (e.g. a case's
        linked accounts, or one account's counterparty set within a case
        window). No chunking — assumes case-scale, not export-scale."""
        if not account_ids:
            return []
        stmt = select(Account).where(Account.account_id.in_(account_ids))
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
        most_recent: bool = False,
    ) -> list[Transaction]:
        """Transactions touching `account_id` (as source and/or dest) within
        `[start, end]`, ordered by timestamp — the read pattern the two
        composite indexes `(source_account, timestamp)`/`(dest_account,
        timestamp)` exist for (ego-graph extraction, timeline
        reconstruction, doc §3.1).

        `most_recent=False` (default, unchanged behavior): `ORDER BY
        timestamp ASC LIMIT limit` — for an account with more than `limit`
        matching transactions, this keeps the OLDEST ones. Every existing
        caller either windows tightly enough that this never matters, or
        already deliberately wants "oldest-first, capped" (case-scoped graph
        construction, where age doesn't matter, just completeness up to the
        cap).

        `most_recent=True`: fetches the newest `limit` rows (`ORDER BY
        timestamp DESC LIMIT limit`) and reverses them back to ascending
        order before returning — same `[start, end]`/composite-index-backed
        query, just keeping the newest tail of a truncated result instead of
        the oldest. Code-review finding, Phase 6: `investigation.
        behavior_analysis`'s `velocity_increase`/`dormancy_reactivation`
        treat the last element of this list as "most recent activity," and
        `investigation.timeline.build_timeline`'s consumers may assume the
        returned window reaches "now" — both silently broke for any account
        exceeding `investigation.case_graph.CASE_SCOPE_TRANSACTION_LIMIT`
        (10,000) under the old ascending-only behavior (the same class of
        truncation bug Phase 5's review already fixed once for a different
        caller, via `CASE_SCOPE_TRANSACTION_LIMIT` itself) — those two
        callers now pass `most_recent=True`."""
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
        if most_recent:
            stmt = stmt.order_by(Transaction.timestamp.desc()).limit(limit)
            return list(reversed(list(self.session.scalars(stmt))))
        stmt = stmt.order_by(Transaction.timestamp.asc()).limit(limit)
        return list(self.session.scalars(stmt))

    #: Every `sort` value `search_for_accounts` accepts, mapped to its
    #: ORDER BY clause. Module-level so `count_for_accounts` doesn't need
    #: it (a count has no order) and so the accepted set is defined once.
    _SEARCH_SORTS: dict[str, Any] = {
        "timestamp_desc": Transaction.timestamp.desc(),
        "timestamp_asc": Transaction.timestamp.asc(),
        "amount_desc": Transaction.amount.desc(),
        "amount_asc": Transaction.amount.asc(),
    }

    def _search_where_clause(
        self,
        account_ids: list[str],
        *,
        min_amount: float | None,
        max_amount: float | None,
        start: datetime | None,
        end: datetime | None,
        channels: list[Channel] | None,
        direction: Literal["in", "out"] | None,
        txn_type: str | None,
    ) -> list[ColumnElement[bool]]:
        """Shared filter-clause builder for `search_for_accounts`/
        `count_for_accounts` (ROADMAP Phase 6) -- generalizes
        `list_for_account_in_window`'s `side_filter` idiom to a *set* of
        scoped `account_ids` rather than one account.

        `direction` is defined relative to the whole `account_ids` scope,
        not any single account within it (this method has no concept of a
        "center" the way `investigation.graph_filters` does): `"in"` means
        `dest_account` is one of `account_ids` (money arriving into the
        scope, from any counterparty, in or out of scope); `"out"` means
        `source_account` is. With no `direction`, a transaction matches if
        *either* side is in scope -- the same "touches this account" test
        `list_for_account_in_window` uses, just widened to a set. This
        reading is what lets the same method serve both L2 search routes
        unchanged: the whole-case search passes every case-linked account
        id, the single-account search narrows `account_ids` to `[account_id]`
        first (making `"in"`/`"out"` collapse to exactly
        `list_for_account_in_window`'s `as_dest`/`as_source` semantics for
        that one account)."""
        if direction == "in":
            touches_scope: ColumnElement[bool] = Transaction.dest_account.in_(account_ids)
        elif direction == "out":
            touches_scope = Transaction.source_account.in_(account_ids)
        else:
            touches_scope = Transaction.source_account.in_(account_ids) | (
                Transaction.dest_account.in_(account_ids)
            )
        clauses: list[ColumnElement[bool]] = [touches_scope]
        if min_amount is not None:
            clauses.append(Transaction.amount >= min_amount)
        if max_amount is not None:
            clauses.append(Transaction.amount <= max_amount)
        if start is not None:
            clauses.append(Transaction.timestamp >= start)
        if end is not None:
            clauses.append(Transaction.timestamp <= end)
        if channels:
            clauses.append(Transaction.channel.in_(channels))
        if txn_type is not None:
            clauses.append(Transaction.txn_type == txn_type)
        return clauses

    def search_for_accounts(
        self,
        account_ids: list[str],
        *,
        min_amount: float | None = None,
        max_amount: float | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        channels: list[Channel] | None = None,
        direction: Literal["in", "out"] | None = None,
        txn_type: str | None = None,
        limit: int = 200,
        offset: int = 0,
        sort: str = "timestamp_desc",
    ) -> list[Transaction]:
        """Filtered, paginated transaction search over a *set* of account
        ids (ROADMAP Phase 6 -- Complete Transaction Analysis). Empty
        `account_ids` returns `[]` with no query issued: the caller
        (`investigation.transaction_search.search`) always passes
        `CaseAccountRepository.list_account_ids_for_case`'s output (or a
        subset of it) -- there is structurally no path to call this with an
        unbounded id set, so an empty scope is "this case has no accounts
        yet," not "search everything." Unrecognized `sort` falls back to
        `timestamp_desc` rather than raising, matching this codebase's
        general "narrow, don't 500, on a bad-but-harmless query param"
        posture at the repository layer (validation belongs to the route)."""
        if not account_ids:
            return []
        clauses = self._search_where_clause(
            account_ids,
            min_amount=min_amount,
            max_amount=max_amount,
            start=start,
            end=end,
            channels=channels,
            direction=direction,
            txn_type=txn_type,
        )
        order = self._SEARCH_SORTS.get(sort, self._SEARCH_SORTS["timestamp_desc"])
        stmt = select(Transaction).where(*clauses).order_by(order).limit(limit).offset(offset)
        return list(self.session.scalars(stmt))

    def count_for_accounts(
        self,
        account_ids: list[str],
        *,
        min_amount: float | None = None,
        max_amount: float | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        channels: list[Channel] | None = None,
        direction: Literal["in", "out"] | None = None,
        txn_type: str | None = None,
    ) -> int:
        """Total row count for `search_for_accounts`'s exact filter set
        (unpaginated) -- powers the response's `total_count` so a caller
        can page without re-fetching everything first."""
        if not account_ids:
            return 0
        clauses = self._search_where_clause(
            account_ids,
            min_amount=min_amount,
            max_amount=max_amount,
            start=start,
            end=end,
            channels=channels,
            direction=direction,
            txn_type=txn_type,
        )
        stmt = select(func.count()).select_from(Transaction).where(*clauses)
        return int(self.session.scalar(stmt) or 0)
