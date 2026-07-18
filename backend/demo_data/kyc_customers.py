"""
KYC/customer mock (ROADMAP Phase 1B checklist item 2): populate
`pep_status`/`sanction_status`/`kyc_status`/occupation-vs-income mismatch
coverage the real `data/HI-Small_accounts.csv` dataset doesn't carry (it has
no KYC/PEP/sanction/income columns at all) -- makes L1 Customer Snapshot and
the profile-mismatch detector demo-able against something richer than the
real ingest path can provide.

`seed_kyc_customers` creates ~`cfg.num_kyc_customers` demo customers, one
account each (1:1, same index -- see `identifiers.demo_account_id_for_
customer`). Distribution targets (rounded to nearest integer via `round()`,
so actual counts may be off by one from the literal percentage):
  - ~`cfg.pct_pep` PEP-flagged
  - ~`cfg.pct_sanctioned` sanction-flagged
  - ~`cfg.pct_income_mismatch` tagged with an occupation/income mismatch
    (a low-income-coded occupation paired with a high declared income, or
    vice versa)
  - a realistic spread across every `KycStatus` value (not all VERIFIED)

Deliberately does NOT create any transactions for this pool -- these are KYC/
reference rows only. `relationships.py` (shared-attribute overwrites) and
`historical_cases.py` (case `primary_account_id`) both consume this same
pool afterward; `golden_scenarios.py` does NOT (it needs dedicated accounts
with specific structural properties, not general-purpose ones -- see its own
module docstring).
"""
from __future__ import annotations

import random
from typing import TypeVar

from db.enums import AccountStatus, ActorType, EddStatus, EntityType, KycStatus, RiskLevel
from db.models.reference import Customer
from db.repositories.reference import AccountRepository, CustomerRepository
from demo_data.config import DemoDataConfig
from demo_data.identifiers import demo_account_id_for_customer, demo_customer_id

# -- Synthetic reference pools (fabricated, not drawn from any real registry) --

_FIRST_NAMES = [
    "Aarav", "Vivaan", "Aditya", "Vihaan", "Arjun", "Sai", "Reyansh", "Krishna",
    "Ishaan", "Rohan", "Ananya", "Diya", "Saanvi", "Aadhya", "Kavya", "Myra",
    "Anika", "Riya", "Priya", "Neha", "Sanya", "Meera", "Kabir", "Rahul",
    "Rajesh", "Suresh", "Amit", "Vikram", "Sanjay", "Deepak", "Manoj", "Nikhil",
    "Karan", "Varun", "Ajay", "Pankaj", "Harish", "Girish", "Naveen", "Prakash",
    "Sunita", "Pooja", "Anjali", "Divya", "Shreya", "Nisha", "Rekha", "Swati",
    "Lakshmi", "Radha", "Geeta", "Sneha", "Preeti", "Kiran", "Aishwarya", "Fatima",
]
_LAST_NAMES = [
    "Sharma", "Verma", "Iyer", "Nair", "Reddy", "Gupta", "Malhotra", "Bose",
    "Chatterjee", "Patel", "Mehta", "Joshi", "Kapoor", "Rao", "Menon", "Pillai",
    "Agarwal", "Bansal", "Chopra", "Desai", "Ghosh", "Khanna", "Krishnan", "Kumar",
    "Mishra", "Nadar", "Pandey", "Sethi", "Shetty", "Sinha", "Trivedi", "Yadav",
    "Bhat", "Chauhan", "Dubey", "Kulkarni", "Mahajan", "Naidu", "Saxena", "Varma",
]
_BUSINESS_SUFFIXES = [
    "Traders Pvt Ltd", "Exports Pvt Ltd", "Enterprises", "Textiles Pvt Ltd",
    "Logistics Pvt Ltd", "Overseas Pvt Ltd", "Agro Industries", "Infra Ltd",
    "Jewellers", "Trading Co", "Imports Pvt Ltd", "Constructions", "Motors",
    "Steels Pvt Ltd", "Foods Pvt Ltd", "Pharma Ltd",
]
_BUSINESS_STEMS = [
    "Sunrise", "Blue Ocean", "Golden Gate", "Silver Line", "Metro", "National",
    "Continental", "Horizon", "Prime", "Apex", "Shree", "Sai", "Ganesh", "Krishna",
    "Lakshmi", "Royal", "Star", "Unity", "Everest", "Ganga", "Deccan", "Konark",
]

_BRANCH_CITIES = [
    "Mumbai", "Delhi", "Bengaluru", "Chennai", "Kolkata", "Hyderabad", "Pune",
    "Ahmedabad", "Jaipur", "Lucknow", "Surat", "Nagpur",
]
_EMPLOYERS = [
    "Union Bank of India", "Tata Consultancy Services", "Reliance Industries",
    "Infosys Ltd", "Self-Employed", "State Government", "HDFC Bank",
    "Wipro Ltd", "Maruti Suzuki India", "Local Municipal Corporation",
]
_INCOME_BRACKETS = ["<2L", "2L-5L", "5L-10L", "10L-25L", "25L-50L", "50L+"]

_LOW_INCOME_OCCUPATIONS = [
    "Daily Wage Labourer", "Domestic Help", "Street Vendor", "Farm Worker",
]
_HIGH_INCOME_OCCUPATIONS = [
    "Chartered Accountant", "Corporate Executive", "Surgeon", "Investment Banker",
]
_NORMAL_OCCUPATIONS = [
    "Teacher", "Software Engineer", "Shop Owner", "Government Employee",
    "Bank Clerk", "Retired", "Homemaker", "Self-Employed Trader",
]
#: Sectors for BUSINESS entities — used in place of a personal occupation.
_BUSINESS_SECTORS = [
    "Wholesale Trading", "Textile Manufacturing", "Import/Export", "Jewellery & Bullion",
    "Construction", "Logistics & Freight", "Food Processing", "Pharmaceuticals",
    "Real Estate", "Automobile Dealership",
]

#: Declared-income figure (INR/year) used for a "low occupation, high
#: declared income" mismatch -- comfortably above what any of
#: `_LOW_INCOME_OCCUPATIONS` would plausibly earn.
_MISMATCH_HIGH_INCOME = 5_000_000.0
#: Declared-income figure used for the inverse ("high occupation, tiny
#: declared income") mismatch direction.
_MISMATCH_LOW_INCOME = 150_000.0

#: `KycStatus` spread -- weighted list, not uniform: most demo customers are
#: fully onboarded (VERIFIED), a realistic minority sit in the other states.
_KYC_STATUS_WEIGHTS: list[tuple[KycStatus, float]] = [
    (KycStatus.VERIFIED, 0.70),
    (KycStatus.PENDING, 0.15),
    (KycStatus.EXPIRED, 0.10),
    (KycStatus.REJECTED, 0.05),
]


_T = TypeVar("_T")


def weighted_choice(rng: random.Random, weights: list[tuple[_T, float]]) -> _T:
    """Pick one value from `weights` (`[(value, probability), ...]`) via
    `rng.choices(...)`. Generic (not `KycStatus`-specific) and public --
    the identical weighted-pick pattern recurs 6 times across this package
    (`kyc_status`/`risk_rating` here, `priority` x3 and `case_level` in
    `historical_cases.py`) -- code-review finding: previously hand-rolled
    inline `rng.choices(...)` at 5 of those 6 sites instead of reusing
    this."""
    values = [v for v, _ in weights]
    probs = [w for _, w in weights]
    return rng.choices(values, weights=probs, k=1)[0]


def _synthetic_pan(rng: random.Random, i: int) -> str:
    """Fabricated PAN-shaped identifier that is deliberately **format-invalid**
    (ROADMAP Phase 8, decision 11).

    A real Indian PAN is `[A-Z]{5}[0-9]{4}[A-Z]` — and, critically, **PAN carries
    no checksum**. So any string matching that layout is a *syntactically valid*
    PAN, and the only thing standing between a generated value and a real
    person's tax identifier is luck. This generator previously emitted exactly
    that format. Shipping syntactically-valid PANs from an AML compliance product
    is indefensible in precisely the room this gets pitched to, and "they're only
    demo values" is not a defence once they're in a database.

    Fixed by putting a **digit in the leading position**, where the real format
    requires a letter. The result can never be a real PAN, for the same reason
    `_synthetic_aadhaar`'s `1` prefix can never be a real Aadhaar: it is
    structurally impossible, not merely unlikely.

    Length (10) is preserved so the UI still lays out correctly, and the
    Relationship Explorer matches on *equality*, so format is functionally
    irrelevant to every feature that consumes this."""
    letters = "".join(rng.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ") for _ in range(4))
    return f"0{letters}{i % 10000:04d}D"


def _synthetic_phone(i: int) -> str:
    """Fabricated phone number, deliberately **not** a dialable Indian mobile
    (ROADMAP Phase 8, decision 11).

    Indian mobile numbers are 10 digits beginning 6-9. This previously emitted
    `9…`, i.e. exactly that format — a demo dataset full of numbers that ring a
    real stranger's handset. Leading `1` is not an allocatable Indian mobile
    prefix, so these cannot collide with a live subscriber; same structural-
    impossibility argument as the Aadhaar and PAN generators.

    Length (10) preserved for the UI."""
    return f"1{700000000 + i:09d}"[:10]


def _synthetic_email(i: int) -> str:
    return f"demo.customer{i:04d}@example-demo.invalid"


def _synthetic_aadhaar(i: int) -> str:
    return f"{100000000000 + i:012d}"


def _pick_name(rng: random.Random, entity_type: EntityType, i: int) -> str:
    """A clean, realistic Indian name — no index suffix, so it reads like a real
    customer record in the UI. Pools are large enough (56 first x 40 last =
    2,240 individual combinations; 22 stems x 16 suffixes = 352 business
    combinations) that collisions across ~200 customers are rare; an occasional
    shared name is realistic and, if it happens, simply surfaces as a low-
    confidence fuzzy-name link in the Relationship Explorer — not a bug."""
    if entity_type is EntityType.BUSINESS:
        return f"{rng.choice(_BUSINESS_STEMS)} {rng.choice(_BUSINESS_SUFFIXES)}"
    return f"{rng.choice(_FIRST_NAMES)} {rng.choice(_LAST_NAMES)}"


def _pick_occupation_and_income(
    rng: random.Random, *, mismatch: bool
) -> tuple[str, float, str]:
    """Returns (occupation, declared_annual_income, income_bracket). When
    `mismatch` is True, deliberately pairs a low-income-coded occupation
    with a high declared income (or vice versa) -- the profile-mismatch
    coverage this module exists to seed."""
    if not mismatch:
        occupation = rng.choice(_NORMAL_OCCUPATIONS)
        bracket = rng.choice(_INCOME_BRACKETS)
        income = {
            "<2L": 150_000.0, "2L-5L": 350_000.0, "5L-10L": 750_000.0,
            "10L-25L": 1_800_000.0, "25L-50L": 3_500_000.0, "50L+": 6_000_000.0,
        }[bracket]
        return occupation, income, bracket

    if rng.random() < 0.5:
        # Low-income-coded occupation, implausibly high declared income.
        occupation = rng.choice(_LOW_INCOME_OCCUPATIONS)
        return occupation, _MISMATCH_HIGH_INCOME, "50L+"
    # High-income-coded occupation, implausibly low declared income.
    occupation = rng.choice(_HIGH_INCOME_OCCUPATIONS)
    return occupation, _MISMATCH_LOW_INCOME, "<2L"


def _risk_rating_for(
    *, pep: bool, sanctioned: bool, mismatch: bool, rng: random.Random
) -> RiskLevel:
    if sanctioned:
        return RiskLevel.CRITICAL
    if pep or mismatch:
        return RiskLevel.HIGH
    return weighted_choice(rng, [(RiskLevel.LOW, 0.8), (RiskLevel.MEDIUM, 0.2)])


def seed_kyc_customers(
    session,
    cfg: DemoDataConfig,
    rng: random.Random,
    *,
    actor_type: ActorType,
    actor_id: str | None,
) -> list[Customer]:
    """Create (idempotently, get-before-create per customer/account) the
    KYC-pool customers + one account each, and return every pool customer
    (whether freshly created this call or already present from an earlier
    run) so downstream generators (`relationships.py`, `historical_cases.py`)
    always get the full, deterministic pool regardless of whether this
    function actually inserted anything this call."""
    customer_repo = CustomerRepository(session)
    account_repo = AccountRepository(session)

    num_pep = round(cfg.num_kyc_customers * cfg.pct_pep)
    num_sanctioned = round(cfg.num_kyc_customers * cfg.pct_sanctioned)
    num_mismatch = round(cfg.num_kyc_customers * cfg.pct_income_mismatch)

    # Deterministic assignment of which indices get which flag: shuffle a
    # fixed index list once per flag rather than per-row coin flips, so the
    # *exact count* matches the configured percentage instead of drifting
    # with per-row randomness.
    indices = list(range(1, cfg.num_kyc_customers + 1))
    pep_indices = set(rng.sample(indices, k=min(num_pep, len(indices))))
    sanctioned_indices = set(rng.sample(indices, k=min(num_sanctioned, len(indices))))
    mismatch_indices = set(rng.sample(indices, k=min(num_mismatch, len(indices))))

    pool: list[Customer] = []
    for i in indices:
        customer_id = demo_customer_id(i)
        existing = customer_repo.get(customer_id)
        if existing is not None:
            pool.append(existing)
            continue

        entity_type = EntityType.BUSINESS if rng.random() < 0.10 else EntityType.INDIVIDUAL
        pep = i in pep_indices
        sanctioned = i in sanctioned_indices
        mismatch = i in mismatch_indices
        if entity_type is EntityType.BUSINESS:
            # A business carries a SECTOR, not a personal occupation, and a
            # business-scale declared income — "Prime Enterprises, occupation:
            # Farm Worker" reads as a data bug in the UI. Businesses aren't
            # subject to the occupation/income mismatch tagging.
            occupation = rng.choice(_BUSINESS_SECTORS)
            bracket = rng.choice(["25L-50L", "50L+"])
            income = {"25L-50L": 3_500_000.0, "50L+": rng.choice([15_000_000.0, 40_000_000.0])}[
                bracket
            ]
        else:
            occupation, income, bracket = _pick_occupation_and_income(rng, mismatch=mismatch)
        kyc_status = weighted_choice(rng, _KYC_STATUS_WEIGHTS)
        edd_status = EddStatus.REQUIRED if (pep or sanctioned) else EddStatus.NOT_REQUIRED

        customer = customer_repo.create(
            customer_id=customer_id,
            name=_pick_name(rng, entity_type, i),
            entity_type=entity_type,
            risk_rating=_risk_rating_for(
                pep=pep, sanctioned=sanctioned, mismatch=mismatch, rng=rng
            ),
            pan=_synthetic_pan(rng, i),
            aadhaar=_synthetic_aadhaar(i),
            phone=_synthetic_phone(i),
            email=_synthetic_email(i),
            address=f"{rng.randint(1, 999)} MG Road, {rng.choice(_BRANCH_CITIES)}",
            occupation=occupation,
            declared_annual_income=income,
            income_bracket=bracket,
            employer=rng.choice(_EMPLOYERS),
            kyc_status=kyc_status,
            edd_status=edd_status,
            pep_status=pep,
            sanction_status=sanctioned,
            actor_type=actor_type,
            actor_id=actor_id,
        )
        pool.append(customer)

        account_id = demo_account_id_for_customer(customer_id)
        if account_repo.get(account_id) is None:
            account_repo.create(
                account_id=account_id,
                customer_id=customer_id,
                account_type="savings" if entity_type is EntityType.INDIVIDUAL else "current",
                bank_name="Union Bank of India",
                bank_id="UBIN0DEMO1",
                branch_city=rng.choice(_BRANCH_CITIES),
                status=AccountStatus.ACTIVE,
                kyc_tier=rng.choice(["TIER_1", "TIER_2", "TIER_3"]),
                actor_type=actor_type,
                actor_id=actor_id,
            )

    return pool
