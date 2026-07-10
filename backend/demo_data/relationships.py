"""
Relationship networks (ROADMAP Phase 1B checklist item 3): clusters of KYC-
pool customers sharing ONE overwritten attribute value, with explicitly ZERO
transactions between cluster members -- the "hidden mule network" a future
Relationship Explorer discovery pass (`docs/DATA_SCHEMA.md` §3.4
`relationships` table, Phase 7) is meant to surface from shared attributes
that transactions alone can't reveal.

This module does NOT write to the `relationships` table -- that table is
Phase 7's discovery-job output (`docs/DATA_SCHEMA.md` §3.4: "stores hidden
links transactions can't reveal"), not something a data generator seeds
directly. `seed_relationship_networks` only seeds the raw shared-attribute
data (on `customers`/`accounts`) a later discovery pass will match on; it
never inserts a `relationships` row itself.

**Scope deviation from `docs/DATA_SCHEMA.md` §4 decision 4** (documented
here, not silently dropped -- same pattern as Phase 4's "8 of 11 rules"
deviation note): decision 4 says the pitch's mock relationship data should
cover PAN/phone/email/address/device/employer/nominee. `device` and
`nominee` have no columns anywhere on `Customer`/`Account` (confirmed: zero
references in `backend/db/models/`) -- there is nothing to write a shared
value into. Per explicit user decision this session, Phase 1B ships
relationship clusters covering every decision-4 attribute that actually has
a column -- `pan`/`phone`/`email`/`address`/`employer` (all `Customer`
columns) -- and does NOT add new columns to fill the `device`/`nominee` gap;
a future phase that adds them can extend this module's `_SHARED_ATTRIBUTES`
list without other changes.

Beyond decision 4's list, this module also rotates in `income_bracket`
(`Customer`) and `branch_city` (`Account` -- the only one of the seven that
isn't on `Customer`) as additional demo variety, not as a correction to
another undocumented gap -- decision 4 never named these two, so their
inclusion here is a deliberate extra, called out explicitly rather than
left to look like scope creep.

Idempotency: this whole generator is gated by its own `ingestion_log` marker
in `seed.py` (checked/written once) -- it is never invoked a second time
against the same DB, so the per-attribute `UPDATE` calls below don't need
their own get-before-create-style guard (an `UPDATE` has no natural-key
short-circuit the way a `create()` does; relying on the outer gate is what
keeps a second invocation from producing duplicate `audit_log` rows for the
same logical write).
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from db.enums import ActorType
from db.models.reference import Customer
from db.repositories.reference import AccountRepository, CustomerRepository
from demo_data.config import DemoDataConfig
from demo_data.identifiers import demo_account_id_for_customer

#: The seven shared-attribute columns this module rotates through (see
#: module docstring's decision-4 deviation note: pan/phone/email/address/
#: employer are decision 4's list; income_bracket/branch_city are additional
#: demo variety beyond it). `branch_city` lives on `Account`, not
#: `Customer` -- `_apply_shared_value` below routes it there.
_SHARED_ATTRIBUTES = [
    "pan", "phone", "email", "address", "employer", "income_bracket", "branch_city",
]


@dataclass
class RelationshipCluster:
    """Summary of one seeded cluster -- returned for `seed.py`'s counts and
    `docs/GOLDEN_SCENARIOS.md`-style documentation, not persisted anywhere."""

    cluster_id: str
    shared_attribute: str
    shared_value: str
    member_customer_ids: list[str] = field(default_factory=list)
    member_account_ids: list[str] = field(default_factory=list)


def _shared_value_for(attribute: str, cluster_idx: int) -> str:
    """A synthetic value distinct from anything `kyc_customers.py` would
    have assigned individually (disjoint numeric ranges / distinguishing
    prefixes), so a cluster's shared value is unambiguously "the cluster
    link", not a coincidental match with unrelated demo data."""
    if attribute == "pan":
        return f"DEMOP{cluster_idx:04d}Z"
    if attribute == "phone":
        return f"9{800000000 + cluster_idx:09d}"[:10]
    if attribute == "email":
        return f"shared.cluster{cluster_idx:02d}@example-demo.invalid"
    if attribute == "address":
        return f"{100 + cluster_idx} Demo Cluster Lane, Shared Colony"
    if attribute == "employer":
        return f"Shell Holdings Group #{cluster_idx:02d}"
    if attribute == "income_bracket":
        # Alternates between the two "unusual" brackets so clusters don't
        # all look identical in a demo walkthrough.
        return "50L+" if cluster_idx % 2 == 0 else "<2L"
    if attribute == "branch_city":
        return f"Demo Branch Cluster {cluster_idx:02d}"
    raise ValueError(f"unknown shared attribute {attribute!r}")


def _apply_shared_value(
    customer_repo: CustomerRepository,
    account_repo: AccountRepository,
    *,
    customer: Customer,
    account_id: str,
    attribute: str,
    value: str,
    actor_type: ActorType,
    actor_id: str | None,
) -> None:
    # Explicit per-attribute dispatch (not `**{attribute: value}`) -- keeps
    # every call statically typed against `CustomerRepository.update`'s real
    # keyword signature instead of an unchecked `**dict[str, str]` splat.
    if attribute == "branch_city":
        account_repo.update(
            account_id, branch_city=value, actor_type=actor_type, actor_id=actor_id
        )
    elif attribute == "pan":
        customer_repo.update(
            customer.customer_id, pan=value, actor_type=actor_type, actor_id=actor_id
        )
    elif attribute == "phone":
        customer_repo.update(
            customer.customer_id, phone=value, actor_type=actor_type, actor_id=actor_id
        )
    elif attribute == "email":
        customer_repo.update(
            customer.customer_id, email=value, actor_type=actor_type, actor_id=actor_id
        )
    elif attribute == "address":
        customer_repo.update(
            customer.customer_id, address=value, actor_type=actor_type, actor_id=actor_id
        )
    elif attribute == "employer":
        customer_repo.update(
            customer.customer_id, employer=value, actor_type=actor_type, actor_id=actor_id
        )
    elif attribute == "income_bracket":
        customer_repo.update(
            customer.customer_id, income_bracket=value, actor_type=actor_type, actor_id=actor_id
        )
    else:
        raise ValueError(f"unknown shared attribute {attribute!r}")


def seed_relationship_networks(
    session,
    cfg: DemoDataConfig,
    rng: random.Random,
    kyc_pool: list[Customer],
    *,
    actor_type: ActorType,
    actor_id: str | None,
) -> list[RelationshipCluster]:
    """Build `cfg.num_relationship_clusters` clusters of 2-4 KYC-pool
    customers each (disjoint -- a customer is placed in at most one
    cluster), overwrite ONE shared attribute across every member of a
    cluster, and create ZERO transactions between them. Returns the cluster
    summaries (not persisted -- see module docstring)."""
    customer_repo = CustomerRepository(session)
    account_repo = AccountRepository(session)

    available = list(kyc_pool)
    rng.shuffle(available)

    clusters: list[RelationshipCluster] = []
    cursor = 0
    for cluster_idx in range(cfg.num_relationship_clusters):
        size = rng.randint(
            cfg.relationship_cluster_min_size, cfg.relationship_cluster_max_size
        )
        members = available[cursor : cursor + size]
        cursor += size
        if len(members) < cfg.relationship_cluster_min_size:
            break  # ran out of distinct KYC-pool customers to draw from

        attribute = _SHARED_ATTRIBUTES[cluster_idx % len(_SHARED_ATTRIBUTES)]
        shared_value = _shared_value_for(attribute, cluster_idx)

        cluster = RelationshipCluster(
            cluster_id=f"cluster-{cluster_idx:02d}",
            shared_attribute=attribute,
            shared_value=shared_value,
        )
        for customer in members:
            account_id = demo_account_id_for_customer(customer.customer_id)
            _apply_shared_value(
                customer_repo,
                account_repo,
                customer=customer,
                account_id=account_id,
                attribute=attribute,
                value=shared_value,
                actor_type=actor_type,
                actor_id=actor_id,
            )
            cluster.member_customer_ids.append(customer.customer_id)
            cluster.member_account_ids.append(account_id)

        clusters.append(cluster)

    return clusters
