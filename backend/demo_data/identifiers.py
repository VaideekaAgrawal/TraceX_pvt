"""
Deterministic id builders for every entity `demo_data` creates -- pure
functions of their inputs, so re-running the generator with the same config/
seed always produces the same ids. Get-before-create idempotency (every
sub-generator; see each module's docstring) depends on this: the second run
must compute the exact same primary keys the first run did, or `repo.get(id)
is None` would never short-circuit anything.

Two id "namespaces":
  - The shared KYC pool (`demo_customer_id`/`demo_account_id`/
    `demo_case_id`), a flat `NNNN`-indexed sequence shared by
    `kyc_customers.py`/`relationships.py`/`historical_cases.py`.
  - Golden-scenario-dedicated entities (`demo_scenario_customer_id`/
    `demo_scenario_account_id`/`demo_scenario_watchlist_id`), namespaced by
    `scenario_key` so each of the 7 scenarios gets its own small, readable id
    range instead of sharing the flat KYC pool's numbering (`golden_scenarios
    .py`'s module docstring: these are dedicated accounts, "not drawn from
    the KYC pool").
"""
from __future__ import annotations

import hashlib

from demo_data.config import DEMO_PREFIX


def demo_customer_id(i: int) -> str:
    return f"{DEMO_PREFIX}CUST-{i:04d}"


def demo_account_id(i: int) -> str:
    return f"{DEMO_PREFIX}ACC-{i:04d}"


def demo_account_id_for_customer(customer_id: str) -> str:
    """The account id paired 1:1 with `customer_id` in the KYC pool
    (`kyc_customers.py` creates exactly one account per customer, same
    index) -- lets a caller holding only a `Customer` row (e.g.
    `historical_cases.py`'s `kyc_pool: list[Customer]`) derive the matching
    account id without a second query or a second return value threaded
    through `seed_kyc_customers`."""
    if not customer_id.startswith(f"{DEMO_PREFIX}CUST-"):
        raise ValueError(f"not a demo KYC-pool customer id: {customer_id!r}")
    return customer_id.replace(f"{DEMO_PREFIX}CUST-", f"{DEMO_PREFIX}ACC-", 1)


def demo_case_id(i: int) -> str:
    return f"{DEMO_PREFIX}CASE-{i:04d}"


def demo_txn_id(source_account: str, dest_account: str, seq: int) -> str:
    """Deterministic, collision-resistant txn id from a stable tuple (same
    convention as `db/ingest.py::make_txn_id`'s hash-of-stable-fields
    approach) -- `seq` disambiguates multiple hops between the same pair."""
    digest = hashlib.sha256(f"{source_account}|{dest_account}|{seq}".encode()).hexdigest()
    return f"{DEMO_PREFIX}TXN-{digest[:24].upper()}"


def demo_scenario_customer_id(scenario_key: str, i: int) -> str:
    return f"{DEMO_PREFIX}CUST-{scenario_key.upper()}-{i:02d}"


def demo_scenario_account_id(scenario_key: str, i: int) -> str:
    return f"{DEMO_PREFIX}ACC-{scenario_key.upper()}-{i:02d}"


def demo_scenario_watchlist_id(scenario_key: str, i: int) -> str:
    return f"{DEMO_PREFIX}WL-{scenario_key.upper()}-{i:02d}"
