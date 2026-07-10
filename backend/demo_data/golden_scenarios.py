"""
Golden edge-case scenarios (ROADMAP Phase 1B checklist item 4): one curated,
**detector-triggering** network per typology (clean layering, structuring-
across-branches, circular/round-trip, dormancy reactivation, profile
mismatch, sanction match, funnel mule), each with dedicated demo customers/
accounts and REAL `Transaction` rows shaped to genuinely trip the
corresponding pattern detector under `detection/detectors/`'s actual
thresholds (`detection/config.py::DEFAULT_DETECTION_CONFIG`) -- not just
described in prose. `docs/GOLDEN_SCENARIOS.md` documents each scenario's
expected system output and cites the exact ids this module produces.

Dedicated (not KYC-pool) accounts: each scenario needs specific structural
properties (a decreasing-amount chain, a tight cycle, a long-gap-then-burst,
a peer-group outlier, ...) the general-purpose KYC pool wasn't built to
provide -- see `kyc_customers.py`'s module docstring for why that pool is
deliberately generic instead.

**Real detector-type coverage gap** (pre-existing, not introduced or fixed
here -- flagged in `docs/SESSION_LOG.md` per `detection/rules/seed.py`'s own
module docstring): `db/enums.py::DetectionType` has only 5 members
(layering, round_trip, structuring, dormancy, profile_mismatch) --
`fan_out`/`fan_in` never survived the Phase 1 schema design, and there is no
sanction-specific detector at all. Two scenarios' *narrative* typology
therefore does not match the *DetectionType* the fabricated transactions
actually trip:
  - `sanction_match`'s fabricated shape is a peer-volume outlier (a
    sanctioned entity moving vastly more than its declared peer group) --
    trips `profile_mismatch` (peer-deviation sub-type), the closest real
    detector, plus a `Watchlist` row for a later phase's auto-escalation
    (`docs/DATA_SCHEMA.md` §3.5: "alerts touching a watchlisted entity get
    auto-priority (Phase 11)").
  - `funnel_mule`'s fabricated shape is fan-in-then-chain (three senders
    converging on a mule, which then forwards through a decreasing-amount
    hop chain) -- the fan-in half isn't a persistable `DetectionType`, but
    the "mule forwards onward" half of the same transaction set is a valid
    `layering` chain and trips that detector for real.
Every other scenario's narrative typology and triggered `DetectionType`
match exactly.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from db.enums import (
    ActorType,
    Channel,
    EddStatus,
    EntityType,
    KycStatus,
    RiskLevel,
    WatchEntityType,
)
from db.repositories.platform import WatchlistRepository
from db.repositories.reference import AccountRepository, CustomerRepository, TransactionRepository
from demo_data.identifiers import (
    demo_scenario_account_id,
    demo_scenario_customer_id,
    demo_scenario_watchlist_id,
    demo_txn_id,
)

_BASE_TIME = datetime(2025, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class GoldenScenario:
    """Static catalog metadata -- one entry per typology, independent of any
    particular seeded run's ids (those come from `GoldenScenarioResult`)."""

    key: str
    typology: str
    name: str
    expected_detection_type: str
    description: str
    known_correct_investigation_path: list[str]
    feature_explanation: str


SCENARIOS: list[GoldenScenario] = [
    GoldenScenario(
        key="layering",
        typology="layering",
        name="Clean Multi-Hop Layering Chain",
        expected_detection_type="layering",
        description=(
            "A 4-hop chain (A1->A2->A3->A4->A5) moving funds with decreasing "
            "amounts (₹10L -> ₹7L -> ₹4.5L -> ₹2.5L) inside 45 minutes -- the "
            "textbook rapid-layering signature: funds move through "
            "intermediaries fast enough that a manual trace would need to "
            "catch all four hops within the same sitting."
        ),
        known_correct_investigation_path=[
            "Open the alert on account A1 (the chain's origin).",
            "Expand the case-scoped ego-graph 2 hops out -- the full A1..A5 chain "
            "should render in one view.",
            "Confirm amount decay across every hop (₹10L -> ₹2.5L) and the "
            "45-minute total time span.",
            "Check A2-A4 (the intermediaries) for any KYC/profile flags.",
            "If no legitimate business purpose is found for the rapid pass-"
            "through, escalate for SAR filing.",
        ],
        feature_explanation=(
            "Triggers `detection.detectors.layering.LayeringDetector`'s tight-"
            "window pass: >=3 hops, decay_ratio >= 0.5, total span <= 120 "
            "minutes (all satisfied with margin)."
        ),
    ),
    GoldenScenario(
        key="structuring",
        typology="structuring",
        name="Structuring Across Branches",
        expected_detection_type="structuring",
        description=(
            "One source account sends four transactions (₹9.5L, ₹9.6L, ₹9.4L, "
            "₹9.7L) to four different destination accounts at four different "
            "branch cities over 21 days -- each individually just under the "
            "₹10L CTR reporting threshold."
        ),
        known_correct_investigation_path=[
            "Open the alert on the source account.",
            "Pull the 30-day transaction timeline -- confirm all 4 amounts sit "
            "in the ₹9-10L band, each below the CTR threshold.",
            "Check whether the 4 destination accounts are related (shared "
            "attribute, common beneficiary) via the Relationship Explorer.",
            "If the pattern isn't explained by legitimate business need, "
            "recommend SAR filing for structuring to evade reporting.",
        ],
        feature_explanation=(
            "Triggers `StructuringDetector._detect_classic`: >=3 same-source "
            "transactions in [₹9L, ₹10L) within a 30-day window (4 present, "
            "all within 21 days)."
        ),
    ),
    GoldenScenario(
        key="roundtrip",
        typology="round_trip",
        name="Circular Round-Trip Flow",
        expected_detection_type="round_trip",
        description=(
            "A 3-node cycle (R1->R2->R3->R1) circulating ₹5L, ₹4.9L, ₹4.8L "
            "within 40 minutes -- 96% of the originating debit returns to R1, "
            "the signature of wash-trading/circular fund movement with no "
            "genuine economic purpose."
        ),
        known_correct_investigation_path=[
            "Open the alert on R1.",
            "Render the cycle (R1->R2->R3->R1) -- confirm it closes back on "
            "itself within under an hour.",
            "Compute the return ratio (~96%) -- near-total fund preservation "
            "through the loop is the key tell.",
            "Check whether R2/R3 have any independent economic activity, or "
            "exist solely as pass-through nodes for this loop.",
            "Escalate for SAR filing if no legitimate purpose is found.",
        ],
        feature_explanation=(
            "Triggers `RoundTripDetector`: a bounded cycle (length 3 <= 12) "
            "with return_ratio >= 0.85 (actual 0.96)."
        ),
    ),
    GoldenScenario(
        key="dormancy",
        typology="dormancy",
        name="Dormant Account Reactivation",
        expected_detection_type="dormancy",
        description=(
            "An account receives two small deposits (₹10K each), then sits "
            "idle for 200 days, then suddenly sends five ₹6L transactions in "
            "as many days -- a 60x jump over its historical average, the "
            "classic dormant-account-reactivated-for-laundering pattern."
        ),
        known_correct_investigation_path=[
            "Open the alert -- note the 200-day gap immediately preceding the "
            "burst.",
            "Compare pre-dormancy average (~₹10K) against post-dormancy "
            "average (~₹6L) -- a 60x jump.",
            "Check the 5 post-dormancy destination accounts for any shared "
            "attributes or prior flags.",
            "Contact the account holder / review KYC freshness -- a long-"
            "dormant account reactivating at high value warrants an EDD "
            "refresh regardless of outcome.",
        ],
        feature_explanation=(
            "Triggers `DormancyDetector`: max inter-transaction gap >= 180 "
            "days (actual 200), burst of >= 5 post-gap transactions (actual "
            "5), burst/pre-dormancy average ratio >= 10x (actual ~60x)."
        ),
    ),
    GoldenScenario(
        key="profile",
        typology="profile_mismatch",
        name="Income vs. Volume Profile Mismatch",
        expected_detection_type="profile_mismatch",
        description=(
            "An individual account with declared annual income of ₹2L moves "
            "₹25L across five transactions in under a week -- 12.5x its "
            "declared income, with no occupation that would plausibly "
            "explain the volume."
        ),
        known_correct_investigation_path=[
            "Open the alert -- compare declared annual income (₹2L) against "
            "actual transacted volume (₹25L, 12.5x).",
            "Review the account's declared occupation for plausibility.",
            "Check counterparties for any relationship-network overlap.",
            "Request updated income documentation / escalate for EDD if the "
            "mismatch isn't explained.",
        ],
        feature_explanation=(
            "Triggers `ProfileMismatchDetector._detect_income_mismatch`: "
            "volume/declared_income ratio > 10 (actual 12.5)."
        ),
    ),
    GoldenScenario(
        key="sanction",
        typology="sanction_match",
        name="Sanctioned-Entity Peer-Volume Outlier",
        expected_detection_type="profile_mismatch",
        description=(
            "A peer group of 12 accounts shares the same declared occupation/"
            "income bracket; 11 move a modest ~₹1L each while the 12th (a "
            "watchlisted/sanctioned entity) moves ₹100Cr through the same "
            "counterparty -- a peer-volume outlier of ~3.2 standard "
            "deviations, on top of an explicit sanctions-list match."
        ),
        known_correct_investigation_path=[
            "Open the alert on the outlier account -- confirm the active "
            "`watchlist` match on the linked customer first (this alone "
            "should drive priority to P1).",
            "Compare against the peer group's typical volume (~₹1L) -- the "
            "outlier moves ~10,000x more.",
            "Trace the destination (the shared hub account) for further fan-"
            "out.",
            "Escalate immediately for compliance/SAR filing -- a confirmed "
            "sanctions match combined with anomalous volume is a hard "
            "escalation trigger, not a judgment call.",
        ],
        feature_explanation=(
            "No dedicated sanction-match detector exists yet (see module "
            "docstring) -- trips `ProfileMismatchDetector._detect_peer_"
            "deviation` instead: z-score > 3.0 against a >=5-member peer "
            "group sharing (occupation, income_bracket) (actual z ~3.2, "
            "group size 12). The `watchlist` row is the concrete anchor a "
            "future auto-escalation phase (Phase 11) consumes."
        ),
    ),
    GoldenScenario(
        key="funnel",
        typology="funnel_mule",
        name="Funnel Mule (Fan-In Then Layer-Out)",
        expected_detection_type="layering",
        description=(
            "Three senders converge on a single mule account (₹10L, ₹1.5L, "
            "₹1L) inside minutes, which then forwards funds onward through a "
            "2-hop decreasing chain (₹7L -> ₹4L) -- a classic funnel/mule "
            "structure: many small (or one large plus several small) "
            "contributions in, rapid layered pass-through out."
        ),
        known_correct_investigation_path=[
            "Open the alert -- render the ego-graph around the mule account.",
            "Confirm the fan-in shape: 3 distinct senders converging within "
            "minutes.",
            "Confirm the fan-out/layering shape: the mule forwards onward "
            "through a decreasing-amount 2-hop chain within the same short "
            "window.",
            "Check all 3 senders and both downstream hops for shared "
            "attributes (Relationship Explorer) -- a funnel structure often "
            "shares an organizer.",
            "Escalate for SAR filing if the mule has no plausible independent "
            "business purpose for aggregating and re-dispersing funds.",
        ],
        feature_explanation=(
            "No dedicated fan-in detector is persistable (see module "
            "docstring) -- the highest-contributing sender's own outbound "
            "leg (₹10L -> mule) starts a valid `LayeringDetector` chain "
            "(mule -> hop1 -> hop2, decay_ratio 1.0, span 20 minutes), so "
            "the layering detector fires on the funnel's downstream half."
        ),
    ),
]


@dataclass
class GoldenScenarioResult:
    """Summary of one seeded scenario run -- `key` + the account ids
    actually written, for `seed.py`'s counts and so `docs/
    GOLDEN_SCENARIOS.md`/tests can cite real, non-guessed ids. Deliberately
    just these two fields (code-review finding: an earlier revision also
    carried `customer_ids`/`transaction_ids`/`watchlist_ids`, computed by
    every builder but never read by any caller -- `seed.py` and
    `tests/demo_data/test_golden_scenarios.py` only ever consume `.key`/
    `.account_ids`). The customer/txn/watchlist ids each builder writes are
    all still fully deterministic and re-derivable from `identifiers.py`'s
    builders + the scenario `key` if a future caller needs them -- nothing
    is lost by not carrying them here."""

    key: str
    account_ids: list[str] = field(default_factory=list)


def _get_or_create_account(
    account_repo: AccountRepository,
    account_id: str,
    *,
    customer_id: str | None = None,
    branch_city: str = "Mumbai",
    actor_type: ActorType,
    actor_id: str | None,
):
    existing = account_repo.get(account_id)
    if existing is not None:
        return existing
    return account_repo.create(
        account_id=account_id,
        customer_id=customer_id,
        bank_name="Union Bank of India",
        branch_city=branch_city,
        actor_type=actor_type,
        actor_id=actor_id,
    )


def _get_or_create_customer(
    customer_repo: CustomerRepository,
    customer_id: str,
    *,
    name: str,
    occupation: str | None = None,
    declared_annual_income: float | None = None,
    income_bracket: str | None = None,
    pan: str | None = None,
    pep_status: bool = False,
    sanction_status: bool = False,
    kyc_status: KycStatus = KycStatus.VERIFIED,
    risk_rating: RiskLevel = RiskLevel.MEDIUM,
    actor_type: ActorType,
    actor_id: str | None,
):
    existing = customer_repo.get(customer_id)
    if existing is not None:
        return existing
    return customer_repo.create(
        customer_id=customer_id,
        name=name,
        entity_type=EntityType.INDIVIDUAL,
        risk_rating=risk_rating,
        pan=pan,
        occupation=occupation,
        declared_annual_income=declared_annual_income,
        income_bracket=income_bracket,
        kyc_status=kyc_status,
        edd_status=(
            EddStatus.REQUIRED if (pep_status or sanction_status) else EddStatus.NOT_REQUIRED
        ),
        pep_status=pep_status,
        sanction_status=sanction_status,
        actor_type=actor_type,
        actor_id=actor_id,
    )


def _get_or_create_txn(
    txn_repo: TransactionRepository,
    *,
    source: str,
    dest: str,
    seq: int,
    amount: float,
    timestamp: datetime,
    channel: Channel = Channel.NEFT,
    is_laundering: int = 1,
    actor_type: ActorType,
    actor_id: str | None,
) -> str:
    txn_id = demo_txn_id(source, dest, seq)
    if txn_repo.get(txn_id) is None:
        txn_repo.create(
            txn_id=txn_id,
            timestamp=timestamp,
            source_account=source,
            dest_account=dest,
            amount=amount,
            channel=channel,
            is_laundering=is_laundering,
            ingested_at=timestamp,
            actor_type=actor_type,
            actor_id=actor_id,
        )
    return txn_id


def _seed_chain(
    txn_repo: TransactionRepository,
    hops: list[tuple[str, str, float]],
    t0: datetime,
    step: timedelta,
    *,
    actor_type: ActorType,
    actor_id: str | None,
) -> list[str]:
    """Create a sequential chain of transactions from `hops` (each a
    `(source, dest, amount)` tuple), one `step` apart starting at `t0` --
    the identical hop-list-to-transaction-chain shape `_build_layering`,
    `_build_roundtrip`, and `_build_profile_mismatch` all needed
    (code-review finding: previously duplicated three times, differing only
    in the hop tuples and the time step). `_build_structuring`/
    `_build_dormancy`/`_build_sanction_match`/`_build_funnel_mule` keep
    their own inline logic instead -- their shapes genuinely differ (a
    varying per-hop channel, a two-phase pre/burst split, a fan-in loop, and
    irregular per-hop delays respectively), not a case of the same pattern
    duplicated a fourth time."""
    return [
        _get_or_create_txn(
            txn_repo, source=src, dest=dst, seq=i, amount=amt,
            timestamp=t0 + step * i,
            actor_type=actor_type, actor_id=actor_id,
        )
        for i, (src, dst, amt) in enumerate(hops)
    ]


def _get_or_create_scenario_watchlist(
    watchlist_repo: WatchlistRepository,
    key: str,
    entity_value: str,
    reason: str,
    *,
    actor_type: ActorType,
    actor_id: str | None,
) -> str:
    """Get-or-create the single `watchlist` entry a scenario needs --
    shared by `_build_profile_mismatch`/`_build_sanction_match` (code-review
    finding: previously an identical block duplicated in both, differing
    only in `entity_value`/`reason`)."""
    watchlist_id = demo_scenario_watchlist_id(key, 1)
    if watchlist_repo.get(watchlist_id) is None:
        watchlist_repo.create(
            entry_id=watchlist_id,
            entity_type=WatchEntityType.CUSTOMER,
            entity_value=entity_value,
            reason=reason,
            added_by="demo-data-studio",
            actor_type=actor_type,
            actor_id=actor_id,
        )
    return watchlist_id


# ---------------------------------------------------------------------------
# Per-scenario builders
# ---------------------------------------------------------------------------


def _build_layering(account_repo, txn_repo, *, actor_type, actor_id) -> GoldenScenarioResult:
    key = "layering"
    accounts = [demo_scenario_account_id(key, i) for i in range(1, 6)]
    for acc_id in accounts:
        _get_or_create_account(account_repo, acc_id, actor_type=actor_type, actor_id=actor_id)

    t0 = _BASE_TIME + timedelta(days=1)
    hops = [(accounts[0], accounts[1], 1_000_000.0), (accounts[1], accounts[2], 700_000.0),
            (accounts[2], accounts[3], 450_000.0), (accounts[3], accounts[4], 250_000.0)]
    _seed_chain(
        txn_repo, hops, t0, timedelta(minutes=15), actor_type=actor_type, actor_id=actor_id
    )
    return GoldenScenarioResult(key=key, account_ids=accounts)


def _build_structuring(account_repo, txn_repo, *, actor_type, actor_id) -> GoldenScenarioResult:
    key = "structuring"
    source = demo_scenario_account_id(key, 1)
    dests = [demo_scenario_account_id(key, i) for i in range(2, 6)]
    branches = ["Mumbai", "Delhi", "Chennai", "Kolkata"]
    _get_or_create_account(account_repo, source, actor_type=actor_type, actor_id=actor_id)
    for dst, city in zip(dests, branches, strict=True):
        _get_or_create_account(
            account_repo, dst, branch_city=city, actor_type=actor_type, actor_id=actor_id
        )

    t0 = _BASE_TIME + timedelta(days=2)
    amounts = [950_000.0, 960_000.0, 940_000.0, 970_000.0]
    for i, (dst, amt) in enumerate(zip(dests, amounts, strict=True)):
        _get_or_create_txn(
            txn_repo, source=source, dest=dst, seq=i, amount=amt,
            timestamp=t0 + timedelta(days=7 * i), channel=Channel.branch_cash,
            actor_type=actor_type, actor_id=actor_id,
        )
    return GoldenScenarioResult(key=key, account_ids=[source, *dests])


def _build_roundtrip(account_repo, txn_repo, *, actor_type, actor_id) -> GoldenScenarioResult:
    key = "roundtrip"
    accounts = [demo_scenario_account_id(key, i) for i in range(1, 4)]
    for acc_id in accounts:
        _get_or_create_account(account_repo, acc_id, actor_type=actor_type, actor_id=actor_id)

    t0 = _BASE_TIME + timedelta(days=3)
    hops = [(accounts[0], accounts[1], 500_000.0), (accounts[1], accounts[2], 490_000.0),
            (accounts[2], accounts[0], 480_000.0)]
    _seed_chain(
        txn_repo, hops, t0, timedelta(minutes=20), actor_type=actor_type, actor_id=actor_id
    )
    return GoldenScenarioResult(key=key, account_ids=accounts)


def _build_dormancy(account_repo, txn_repo, *, actor_type, actor_id) -> GoldenScenarioResult:
    key = "dormancy"
    dormant = demo_scenario_account_id(key, 1)
    pre_counterparties = [demo_scenario_account_id(key, i) for i in (2, 3)]
    post_counterparties = [demo_scenario_account_id(key, i) for i in range(4, 9)]
    for acc_id in [dormant, *pre_counterparties, *post_counterparties]:
        _get_or_create_account(account_repo, acc_id, actor_type=actor_type, actor_id=actor_id)

    t0 = _BASE_TIME + timedelta(days=5)
    _get_or_create_txn(
        txn_repo, source=pre_counterparties[0], dest=dormant, seq=0, amount=10_000.0,
        timestamp=t0, actor_type=actor_type, actor_id=actor_id,
    )
    _get_or_create_txn(
        txn_repo, source=pre_counterparties[1], dest=dormant, seq=1, amount=10_000.0,
        timestamp=t0 + timedelta(days=5), actor_type=actor_type, actor_id=actor_id,
    )
    burst_start = t0 + timedelta(days=5) + timedelta(days=200)
    for i, cp in enumerate(post_counterparties):
        _get_or_create_txn(
            txn_repo, source=dormant, dest=cp, seq=2 + i, amount=600_000.0,
            timestamp=burst_start + timedelta(days=i),
            actor_type=actor_type, actor_id=actor_id,
        )
    return GoldenScenarioResult(
        key=key, account_ids=[dormant, *pre_counterparties, *post_counterparties]
    )


def _build_profile_mismatch(
    customer_repo, account_repo, txn_repo, watchlist_repo, *, actor_type, actor_id
) -> GoldenScenarioResult:
    key = "profile"
    customer_id = demo_scenario_customer_id(key, 1)
    account_id = demo_scenario_account_id(key, 1)
    counterparties = [demo_scenario_account_id(key, i) for i in range(2, 7)]

    customer = _get_or_create_customer(
        customer_repo, customer_id, name="Profile Mismatch Demo Subject #1",
        occupation="Unemployed", declared_annual_income=200_000.0, income_bracket="<2L",
        pan="DEMOPMIS0001Z", risk_rating=RiskLevel.HIGH,
        actor_type=actor_type, actor_id=actor_id,
    )
    _get_or_create_account(
        account_repo, account_id, customer_id=customer_id, actor_type=actor_type, actor_id=actor_id
    )
    for cp in counterparties:
        _get_or_create_account(account_repo, cp, actor_type=actor_type, actor_id=actor_id)

    t0 = _BASE_TIME + timedelta(days=10)
    legs = [
        (counterparties[0], account_id, 500_000.0),
        (counterparties[1], account_id, 500_000.0),
        (account_id, counterparties[2], 500_000.0),
        (account_id, counterparties[3], 500_000.0),
        (counterparties[4], account_id, 500_000.0),
    ]
    _seed_chain(
        txn_repo, legs, t0, timedelta(days=1), actor_type=actor_type, actor_id=actor_id
    )

    _get_or_create_scenario_watchlist(
        watchlist_repo, key, customer.pan or customer_id,
        "Income/volume mismatch -- escalation candidate (demo).",
        actor_type=actor_type, actor_id=actor_id,
    )

    return GoldenScenarioResult(key=key, account_ids=[account_id, *counterparties])


def _build_sanction_match(
    customer_repo, account_repo, txn_repo, watchlist_repo, *, actor_type, actor_id
) -> GoldenScenarioResult:
    key = "sanction"
    occupation = "Import-Export Consultant"
    income_bracket = "10L-25L"
    declared_income = 1_800_000.0

    peer_customer_ids = [demo_scenario_customer_id(key, i) for i in range(1, 12)]  # 11 peers
    peer_account_ids = [demo_scenario_account_id(key, i) for i in range(1, 12)]
    outlier_customer_id = demo_scenario_customer_id(key, 12)
    outlier_account_id = demo_scenario_account_id(key, 12)
    hub_account_id = demo_scenario_account_id(key, 13)

    for cid, aid in zip(peer_customer_ids, peer_account_ids, strict=True):
        _get_or_create_customer(
            customer_repo, cid, name=f"Sanction Peer {cid}", occupation=occupation,
            declared_annual_income=declared_income, income_bracket=income_bracket,
            risk_rating=RiskLevel.LOW, actor_type=actor_type, actor_id=actor_id,
        )
        _get_or_create_account(
            account_repo, aid, customer_id=cid, actor_type=actor_type, actor_id=actor_id
        )

    outlier_customer = _get_or_create_customer(
        customer_repo, outlier_customer_id, name="Sanctioned Entity (Demo)",
        occupation=occupation, declared_annual_income=declared_income,
        income_bracket=income_bracket, pan="DEMOPSANC012Z",
        pep_status=True, sanction_status=True, risk_rating=RiskLevel.CRITICAL,
        actor_type=actor_type, actor_id=actor_id,
    )
    _get_or_create_account(
        account_repo, outlier_account_id, customer_id=outlier_customer_id,
        actor_type=actor_type, actor_id=actor_id,
    )
    _get_or_create_account(
        account_repo, hub_account_id, branch_city="Mumbai",
        actor_type=actor_type, actor_id=actor_id,
    )

    t0 = _BASE_TIME + timedelta(days=20)
    for i, peer_account in enumerate(peer_account_ids, start=1):
        _get_or_create_txn(
            txn_repo, source=peer_account, dest=hub_account_id, seq=i, amount=100_000.0,
            timestamp=t0 + timedelta(minutes=10 * i), is_laundering=0,
            actor_type=actor_type, actor_id=actor_id,
        )
    _get_or_create_txn(
        txn_repo, source=outlier_account_id, dest=hub_account_id, seq=12,
        amount=1_000_000_000.0, timestamp=t0 + timedelta(minutes=130),
        actor_type=actor_type, actor_id=actor_id,
    )

    _get_or_create_scenario_watchlist(
        watchlist_repo, key, outlier_customer.pan or outlier_customer_id,
        "Sanctions list match (mock OFAC/UN) -- demo.",
        actor_type=actor_type, actor_id=actor_id,
    )

    return GoldenScenarioResult(
        key=key, account_ids=[*peer_account_ids, outlier_account_id, hub_account_id]
    )


def _build_funnel_mule(account_repo, txn_repo, *, actor_type, actor_id) -> GoldenScenarioResult:
    key = "funnel"
    senders = [demo_scenario_account_id(key, i) for i in (1, 2, 3)]
    mule = demo_scenario_account_id(key, 4)
    hop1 = demo_scenario_account_id(key, 5)
    hop2 = demo_scenario_account_id(key, 6)
    for acc_id in [*senders, mule, hop1, hop2]:
        _get_or_create_account(account_repo, acc_id, actor_type=actor_type, actor_id=actor_id)

    t0 = _BASE_TIME + timedelta(days=30)
    inbound = [
        (senders[0], mule, 1_000_000.0, 0),
        (senders[1], mule, 150_000.0, 2),
        (senders[2], mule, 100_000.0, 4),
    ]
    outbound = [(mule, hop1, 700_000.0, 10), (hop1, hop2, 400_000.0, 20)]

    for i, (src, dst, amt, delay) in enumerate([*inbound, *outbound]):
        _get_or_create_txn(
            txn_repo, source=src, dest=dst, seq=i, amount=amt,
            timestamp=t0 + timedelta(minutes=delay),
            actor_type=actor_type, actor_id=actor_id,
        )
    return GoldenScenarioResult(key=key, account_ids=[*senders, mule, hop1, hop2])


def seed_golden_scenarios(
    session,
    rng: random.Random,
    *,
    actor_type: ActorType,
    actor_id: str | None,
) -> list[GoldenScenarioResult]:
    """Build all 7 `SCENARIOS`, each with its own dedicated accounts (and,
    for `profile`/`sanction`, dedicated customers) and real fabricated
    `Transaction` rows shaped to trip the detector `SCENARIOS[i].
    expected_detection_type` names. `rng` is accepted for signature
    consistency with the other generators but unused -- every scenario's
    structure is deliberately fixed (a golden scenario has to reproduce the
    *exact* pattern shape its detector needs every run, not a randomized
    approximation of one)."""
    del rng  # deliberately unused -- see docstring
    customer_repo = CustomerRepository(session)
    account_repo = AccountRepository(session)
    txn_repo = TransactionRepository(session)
    watchlist_repo = WatchlistRepository(session)

    return [
        _build_layering(account_repo, txn_repo, actor_type=actor_type, actor_id=actor_id),
        _build_structuring(account_repo, txn_repo, actor_type=actor_type, actor_id=actor_id),
        _build_roundtrip(account_repo, txn_repo, actor_type=actor_type, actor_id=actor_id),
        _build_dormancy(account_repo, txn_repo, actor_type=actor_type, actor_id=actor_id),
        _build_profile_mismatch(
            customer_repo, account_repo, txn_repo, watchlist_repo,
            actor_type=actor_type, actor_id=actor_id,
        ),
        _build_sanction_match(
            customer_repo, account_repo, txn_repo, watchlist_repo,
            actor_type=actor_type, actor_id=actor_id,
        ),
        _build_funnel_mule(account_repo, txn_repo, actor_type=actor_type, actor_id=actor_id),
    ]
