"""
Demo Data Studio orchestrator -- runs five sub-generators in order
(kyc_customers -> relationships -> relationship_discovery ->
historical_cases -> golden_scenarios), each gated by its own
`ingestion_log` marker row so a second run is a true no-op (`db/ingest.py`'s
exact pattern: "a file already logged with status 'success' is not
re-processed at all").

`relationship_discovery` (ROADMAP Phase 7) runs `investigation.
relationship_discovery.discover_relationships` right after
`seed_relationship_networks` -- the concrete live-verification hook that
Phase 1B's 8 seeded shared-attribute clusters are actually rediscovered
into real `relationships` rows, not just left as raw shared-attribute data
on `customers`/`accounts`. Unlike the other four, it takes no `random.
Random` instance (it's a deterministic pairwise comparison, not a
generator with random draws) and doesn't consume `kyc_pool` directly --
it queries the candidate pool itself (`CustomerRepository.
list_relationship_candidate_pool`).

`file_hash` for each marker is a literal descriptive string (e.g.
`"demo-seed:kyc_customers:v1"`), **not** a real file hash -- deliberate
deviation from `db/ingest.py`'s convention, documented here since there is no
source file to hash: these markers exist purely to record "did this
generator's bulk work already run", the same idempotency role a file hash
plays for a real CSV ingest. The trailing `:v1` lets a future schema/logic
change to one generator invalidate just that marker (bump to `:v2`) without
forcing every other generator to re-run.

`kyc_customers` is always re-derived into `kyc_pool` via `_load_kyc_pool`
(a fresh query) regardless of whether this call actually executed
`seed_kyc_customers` or found its marker already `success` -- `relationships`
and `historical_cases` both need the full, deterministic pool either way.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from db.enums import ActorType
from db.models.reference import Customer
from db.repositories.platform import IngestionLogRepository
from db.repositories.reference import CustomerRepository
from demo_data.config import DEFAULT_DEMO_DATA_CONFIG, DEMO_SEED
from demo_data.golden_scenarios import seed_golden_scenarios
from demo_data.historical_cases import seed_historical_cases
from demo_data.identifiers import demo_customer_id
from demo_data.kyc_customers import seed_kyc_customers
from demo_data.pilot_transactions import generate_pilot_transactions
from demo_data.relationships import seed_relationship_networks
from investigation.relationship_discovery import discover_relationships

_KYC_MARKER = "demo-seed:kyc_customers:v1"
_PILOT_TXNS_MARKER = "demo-seed:pilot_transactions:v1"
_RELATIONSHIPS_MARKER = "demo-seed:relationships:v1"
_RELATIONSHIP_DISCOVERY_MARKER = "demo-seed:relationship_discovery:v1"
_HISTORICAL_CASES_MARKER = "demo-seed:historical_cases:v1"
_GOLDEN_SCENARIOS_MARKER = "demo-seed:golden_scenarios:v1"


@dataclass
class DemoSeedSummary:
    """Counts for this call only -- 0 for anything short-circuited by an
    already-`success` marker (see `already_seeded`)."""

    kyc_customers_created: int = 0
    planted_scenarios_created: int = 0
    relationship_clusters_created: int = 0
    relationships_discovered: int = 0
    historical_cases_created: int = 0
    golden_scenarios_created: int = 0
    already_seeded: list[str] = field(default_factory=list)


def _marker_done(log_repo: IngestionLogRepository, file_hash: str) -> bool:
    row = log_repo.get(file_hash)
    return row is not None and row.status == "success"


def _mark_done(
    log_repo: IngestionLogRepository,
    file_hash: str,
    *,
    filename: str,
    count: int,
    actor_type: ActorType,
    actor_id: str | None,
) -> None:
    log_repo.create(
        file_hash=file_hash,
        filename=filename,
        status="success",
        validation={"count": count},
        actor_type=actor_type,
        actor_id=actor_id,
    )


def _load_kyc_pool(session: Session, num_kyc_customers: int) -> list[Customer]:
    """Fetch the deterministic KYC pool by id (`demo_customer_id(1..N)`) --
    used both after a fresh `seed_kyc_customers` call and after a short-
    circuited skip, so downstream generators always see the same pool
    regardless of whether this run actually executed it."""
    repo = CustomerRepository(session)
    pool = []
    for i in range(1, num_kyc_customers + 1):
        customer = repo.get(demo_customer_id(i))
        if customer is not None:
            pool.append(customer)
    return pool


def run_demo_data_studio(
    session: Session,
    *,
    actor_type: ActorType,
    actor_id: str | None,
    hmac_key: str,
    include_golden_scenarios: bool = True,
) -> DemoSeedSummary:
    """Orchestrate all five sub-generators. Each of the four RANDOM
    generators gets its own independent `random.Random(DEMO_SEED + offset)`
    instance (not one shared RNG threaded through all of them) so a
    generator's output is reproducible regardless of which of the others
    did or didn't actually execute this call (a shared RNG's output would
    depend on how many random draws the earlier generators made, which
    changes based on short-circuiting). `relationship_discovery` is
    deterministic (no RNG) -- see module docstring.

    `hmac_key` (from `Settings.pii_hmac_key`) keys the relationship-discovery
    stage's `value_hash` HMAC (ROADMAP Phase 8, decision 9). Required: an empty
    key is refused rather than silently degraded to an unkeyed digest.
    """
    cfg = DEFAULT_DEMO_DATA_CONFIG
    log_repo = IngestionLogRepository(session)
    summary = DemoSeedSummary()

    if _marker_done(log_repo, _KYC_MARKER):
        summary.already_seeded.append("kyc_customers")
    else:
        rng = random.Random(DEMO_SEED)
        pool = seed_kyc_customers(session, cfg, rng, actor_type=actor_type, actor_id=actor_id)
        session.flush()
        _mark_done(
            log_repo, _KYC_MARKER, filename="demo_data_studio/kyc_customers",
            count=len(pool), actor_type=actor_type, actor_id=actor_id,
        )
        summary.kyc_customers_created = len(pool)

    kyc_pool = _load_kyc_pool(session, cfg.num_kyc_customers)

    if _marker_done(log_repo, _PILOT_TXNS_MARKER):
        summary.already_seeded.append("pilot_transactions")
    else:
        rng = random.Random(DEMO_SEED + 4)
        scenarios = generate_pilot_transactions(
            session, kyc_pool, cfg, rng, actor_type=actor_type, actor_id=actor_id
        )
        session.flush()
        _mark_done(
            log_repo, _PILOT_TXNS_MARKER, filename="demo_data_studio/pilot_transactions",
            count=len(scenarios), actor_type=actor_type, actor_id=actor_id,
        )
        summary.planted_scenarios_created = len(scenarios)

    if _marker_done(log_repo, _RELATIONSHIPS_MARKER):
        summary.already_seeded.append("relationships")
    else:
        rng = random.Random(DEMO_SEED + 1)
        clusters = seed_relationship_networks(
            session, cfg, rng, kyc_pool, actor_type=actor_type, actor_id=actor_id
        )
        session.flush()
        _mark_done(
            log_repo, _RELATIONSHIPS_MARKER, filename="demo_data_studio/relationships",
            count=len(clusters), actor_type=actor_type, actor_id=actor_id,
        )
        summary.relationship_clusters_created = len(clusters)

    if _marker_done(log_repo, _RELATIONSHIP_DISCOVERY_MARKER):
        summary.already_seeded.append("relationship_discovery")
    else:
        stats = discover_relationships(
            session, actor_type=actor_type, actor_id=actor_id, hmac_key=hmac_key
        )
        session.flush()
        _mark_done(
            log_repo, _RELATIONSHIP_DISCOVERY_MARKER,
            filename="demo_data_studio/relationship_discovery",
            count=stats.relationships_created, actor_type=actor_type, actor_id=actor_id,
        )
        summary.relationships_discovered = stats.relationships_created

    if _marker_done(log_repo, _HISTORICAL_CASES_MARKER):
        summary.already_seeded.append("historical_cases")
    else:
        rng = random.Random(DEMO_SEED + 2)
        cases = seed_historical_cases(
            session, cfg, rng, kyc_pool, actor_type=actor_type, actor_id=actor_id
        )
        session.flush()
        _mark_done(
            log_repo, _HISTORICAL_CASES_MARKER, filename="demo_data_studio/historical_cases",
            count=len(cases), actor_type=actor_type, actor_id=actor_id,
        )
        summary.historical_cases_created = len(cases)

    if not include_golden_scenarios:
        # The crisp India-centric pilot dataset covers every typology on
        # KYC-rich accounts already; the 7 golden scenarios use dedicated
        # accounts with no rich KYC, so they surface as a couple of blank-
        # Customer-Snapshot cases. Skip them for a uniformly KYC-linked demo.
        summary.already_seeded.append("golden_scenarios (skipped)")
    elif _marker_done(log_repo, _GOLDEN_SCENARIOS_MARKER):
        summary.already_seeded.append("golden_scenarios")
    else:
        rng = random.Random(DEMO_SEED + 3)
        results = seed_golden_scenarios(session, rng, actor_type=actor_type, actor_id=actor_id)
        session.flush()
        _mark_done(
            log_repo, _GOLDEN_SCENARIOS_MARKER, filename="demo_data_studio/golden_scenarios",
            count=len(results), actor_type=actor_type, actor_id=actor_id,
        )
        summary.golden_scenarios_created = len(results)

    return summary
