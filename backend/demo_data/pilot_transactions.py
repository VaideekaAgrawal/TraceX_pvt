"""Pilot transaction layer — the crisp, India-centric demo dataset.

The KYC pool (`kyc_customers.py`) gives ~200 fully-profiled Indian customers but
**no transactions**, and the golden scenarios (`golden_scenarios.py`) plant
detector-triggering transactions on *dedicated* accounts with no rich KYC. This
module closes the gap: it lays a realistic transaction layer over the KYC pool so
that every flagged account has a real name/occupation/income, and plants a
curated set of typology scenarios that produce a **reasonable** number of clean,
investigable cases.

Design goals (in priority order):

1. **Credible alert rate.** ~80% of customers get only a clean baseline (salary,
   rent, spending sized to their declared income) that must NOT trip any
   detector. A bank does not believe a system that flags everyone.
2. **A deliberate L1 / L2 / false-negative mix**, because a demo that only shows
   easy wins is not credible:
   - **L1** — single-account, obvious at a glance (structuring under the CTR
     line; a student receiving crores; a dormant account erupting).
   - **L2** — multi-account networks only the graph cracks (layering chains,
     round-trip cycles, funnel-mule rings).
   - **FN** — genuinely suspicious activity crafted to sit *just under* a detector
     threshold, so it is NOT flagged. `is_laundering=1` marks the ground truth;
     the system misses it, and only a human working the surrounding network in L2
     would catch it. This is what makes the tool look like a real aid, not magic.
3. **Every planted shape reuses the amounts/timing the golden scenarios already
   proved trip the real detectors** (`detection/rules/seed.py`'s built-in rules
   at `PrimitiveRegistry.DEFAULTS`): structuring band ₹9-10L x>=3 in 30d; layering
   >=3 hops, decaying, within 120min; round-trip cycle returning >=85%; dormancy
   180d gap then a >=5-txn 10x burst; profile-mismatch volume > 10x declared income.

Idempotent like the rest of the package: deterministic ids (`demo_txn_id`), so a
re-run creates nothing new. Ground-truth `is_laundering` is set honestly (1 for
planted suspicious incl. false negatives, 0 for clean/false-positive).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from random import Random

from sqlalchemy.orm import Session

from db.enums import AccountStatus, ActorType, Channel, EntityType
from db.models.reference import Customer
from db.repositories.reference import AccountRepository, TransactionRepository
from demo_data.config import DEMO_PREFIX, DemoDataConfig
from demo_data.identifiers import demo_account_id_for_customer, demo_txn_id

_CHANNELS = [Channel.UPI, Channel.NEFT, Channel.IMPS, Channel.RTGS]
#: The demo activity window. Wide enough that a dormancy gap (>180 days) fits and
#: the "alerts over time" chart has spread; suspicious bursts cluster in the
#: recent months so they read as "current" on the dashboard.
_WINDOW_START = datetime(2025, 6, 1, tzinfo=UTC)
_RECENT = datetime(2026, 6, 1, tzinfo=UTC)

# Institutional counterparties (salary source, merchants, utilities) that clean
# baseline traffic flows through — created as plain demo business accounts.
_INSTITUTIONS = [
    ("employer", "Infotech Payroll"),
    ("employer", "Gov Salary Disbursement"),
    ("merchant", "BigBazaar Retail"),
    ("merchant", "Reliance Fresh"),
    ("utility", "Tata Power"),
    ("utility", "Airtel Telecom"),
    ("rent", "Prestige Landlord Co"),
]


@dataclass
class PlantedScenario:
    """One planted case (or a false negative that produces no case). `tier` is
    the demo teaching category, not a system field."""

    key: str
    typology: str  # structuring | layering | round_trip | dormancy | profile_mismatch | funnel_mule
    tier: str  # L1 | L2 | FN | FP
    account_ids: list[str]
    title: str
    narrative: str
    is_true_positive: bool = True


@dataclass
class _Emitter:
    """Persists transactions with deterministic, collision-free ids."""

    repo: TransactionRepository
    actor_type: ActorType
    actor_id: str | None
    rng: Random
    _seq: int = field(default=0)

    def emit(
        self,
        src: str,
        dst: str,
        amount: float,
        when: datetime,
        *,
        is_laundering: int,
        channel: Channel | None = None,
    ) -> None:
        self._seq += 1
        txn_id = demo_txn_id(src, dst, self._seq)
        if self.repo.get(txn_id) is not None:
            return
        self.repo.create(
            txn_id=txn_id,
            timestamp=when,
            source_account=src,
            dest_account=dst,
            amount=round(amount, 2),
            channel=channel or self.rng.choice(_CHANNELS),
            is_laundering=is_laundering,
            ingested_at=when,
            txn_type="transfer",
            from_bank="UBIN0DEMO1",
            to_bank="UBIN0DEMO1",
            actor_type=self.actor_type,
            actor_id=self.actor_id,
        )


def _seed_institutions(
    session: Session, rng: Random, *, actor_type: ActorType, actor_id: str | None
) -> dict[str, list[str]]:
    """Create the institutional counterparty accounts, grouped by role."""
    repo = AccountRepository(session)
    by_role: dict[str, list[str]] = {}
    for i, (role, name) in enumerate(_INSTITUTIONS):
        acc_id = f"{DEMO_PREFIX}ACC-INST-{i:02d}"
        if repo.get(acc_id) is None:
            repo.create(
                account_id=acc_id,
                customer_id=None,
                account_type="current",
                bank_name=name,
                bank_id="UBIN0DEMO1",
                branch_city="Mumbai",
                status=AccountStatus.ACTIVE,
                actor_type=actor_type,
                actor_id=actor_id,
            )
        by_role.setdefault(role, []).append(acc_id)
    return by_role


def _baseline(
    emitter: _Emitter, account_id: str, income: float, inst: dict[str, list[str]]
) -> None:
    """Clean, in-profile activity: monthly salary in, rent + a few merchant/
    utility payments out. Sized to declared income so total volume stays well
    under the 10x profile-mismatch ratio, amounts nowhere near the ₹9-10L
    structuring band, spread evenly so nothing looks like a burst."""
    rng = emitter.rng
    monthly = max(income / 12.0, 20_000.0)
    months = 6  # a half-year of history — enough for the timeline, keeps volume sane
    for m in range(months):
        when = _WINDOW_START + timedelta(days=30 * m + rng.randint(0, 5))
        emitter.emit(
            rng.choice(inst["employer"]), account_id, monthly * rng.uniform(0.95, 1.05), when,
            is_laundering=0, channel=Channel.NEFT,
        )
        # rent + 1 small spend, kept comparable in magnitude to salary so no
        # single amount reads as a >3-sigma "spike".
        emitter.emit(
            account_id, rng.choice(inst["rent"]), monthly * rng.uniform(0.25, 0.35),
            when + timedelta(days=2), is_laundering=0,
        )
        sink = rng.choice(inst["merchant"] + inst["utility"])
        emitter.emit(
            account_id, sink, monthly * rng.uniform(0.10, 0.20),
            when + timedelta(days=rng.randint(3, 20)), is_laundering=0,
        )


def _acc(customer: Customer) -> str:
    return demo_account_id_for_customer(customer.customer_id)


# ── typology builders (amounts/timing mirror the proven golden scenarios) ──


def _structuring(emitter: _Emitter, source: str, dests: list[str], when: datetime, n: int) -> None:
    """`n` deposits in the ₹9.3-9.8L band (just under the ₹10L CTR line) from one
    source to distinct dests over ~3 weeks. Trips amount_band_count (>=3 in 30d)."""
    rng = emitter.rng
    for k in range(n):
        # ₹9.3-9.85 lakh — just under the ₹10 lakh CTR line (band is [900k, 1M]).
        emitter.emit(
            source, dests[k % len(dests)], rng.uniform(930_000, 985_000),
            when + timedelta(days=k * 4 + rng.randint(0, 2)), is_laundering=1,
            channel=Channel.branch_cash,
        )


def _layering(emitter: _Emitter, chain: list[str], when: datetime, top: float = 4_000_000) -> None:
    """Rapid decreasing-amount hop chain within ~90 min. Trips chain (>=3 hops,
    decay>=0.5, span<=120min)."""
    amt = top
    t = when
    for i in range(len(chain) - 1):
        emitter.emit(chain[i], chain[i + 1], amt, t, is_laundering=1, channel=Channel.RTGS)
        amt *= 0.68
        t += timedelta(minutes=emitter.rng.randint(8, 22))


def _round_trip(
    emitter: _Emitter, cycle: list[str], when: datetime, top: float = 2_500_000
) -> None:
    """Funds circle back to origin retaining >=85%. Trips cycle detection."""
    amt = top
    t = when
    ring = [*cycle, cycle[0]]
    for i in range(len(ring) - 1):
        emitter.emit(ring[i], ring[i + 1], amt, t, is_laundering=1, channel=Channel.IMPS)
        amt *= 0.95  # ends at ~0.86 of top over a 3-hop ring — above the 0.85 return floor
        t += timedelta(hours=emitter.rng.randint(2, 10))


def _funnel_mule(
    emitter: _Emitter, senders: list[str], mule: str, chain: list[str], when: datetime
) -> None:
    """Fan-in (several senders -> one mule) then the mule forwards through a
    decreasing chain. The forwarding half is a valid layering chain and trips it;
    the whole thing is the classic mule signature an L2 analyst reconstructs."""
    for s in senders:
        emitter.emit(s, mule, emitter.rng.uniform(800_000, 1_200_000), when, is_laundering=1)
    _layering(emitter, [mule, *chain], when + timedelta(minutes=30), top=1_500_000)


def _dormancy(emitter: _Emitter, account_id: str, peer: str) -> None:
    """One small old transaction, a >200-day silence, then a burst of 6 large
    transactions. Trips inactivity_then_burst (180d gap, >=5 txns, 10x)."""
    emitter.emit(peer, account_id, 50_000, _WINDOW_START + timedelta(days=10), is_laundering=0)
    burst = _RECENT + timedelta(days=20)
    for k in range(6):
        emitter.emit(
            account_id, peer, 500_000, burst + timedelta(hours=k * 3), is_laundering=1,
        )


def _profile_mismatch(
    emitter: _Emitter, account_id: str, sources: list[str], income: float
) -> None:
    """Account receives ~15x its declared annual income in a handful of inflows —
    volume/income ratio well over the 10x threshold, on an account that HAS a
    declared profile (so the gated detector fires)."""
    target = income * 15.0
    rng = emitter.rng
    n = 5
    for k in range(n):
        emitter.emit(
            rng.choice(sources), account_id, target / n * rng.uniform(0.85, 1.15),
            _RECENT + timedelta(days=k * 3), is_laundering=1,
        )


def _fn_structuring(emitter: _Emitter, source: str, dest: str, when: datetime) -> None:
    """FALSE NEGATIVE: only 2 near-threshold deposits — below the min-count-3
    structuring floor, so it is NOT flagged, though it IS laundering (ground
    truth =1). A human reviewing the source's timeline would still spot it."""
    for k in range(2):
        emitter.emit(
            source, dest, emitter.rng.uniform(940_000, 970_000),
            when + timedelta(days=k * 6), is_laundering=1, channel=Channel.branch_cash,
        )


# ── orchestration ──────────────────────────────────────────────────────────

#: How many of each scenario to plant. Tunable — this is the knob that keeps the
#: alert count "reasonable" while still showing enough variety to be credible.
_COUNTS = {
    "structuring": 16,   # L1
    "profile_mismatch": 14,  # L1
    "dormancy": 6,       # L1
    "layering": 6,       # L2
    "round_trip": 5,     # L2
    "funnel_mule": 4,    # L2
    "fn_structuring": 4,  # false negative (no case)
    "fp_business": 2,    # false positive (flags, but legit on inspection)
}


class _Allocator:
    """Hands out KYC-pool accounts. `primary()` consumes an account as a scenario
    actor (no clean baseline); `borrow()` returns a random clean account to act as
    a counterparty (still gets baseline — a normal customer who merely received a
    suspicious deposit)."""

    def __init__(self, accounts: list[str], rng: Random) -> None:
        self._accounts = accounts
        self._rng = rng
        self._cursor = 0
        self.primary_used: set[str] = set()

    def primary(self, n: int = 1) -> list[str]:
        out = self._accounts[self._cursor : self._cursor + n]
        self._cursor += n
        self.primary_used.update(out)
        return out

    def borrow(self) -> str:
        # a clean account from the tail of the pool (never a primary actor)
        return self._rng.choice(self._accounts[len(self._accounts) // 2 :])


def generate_pilot_transactions(
    session: Session,
    kyc_pool: list[Customer],
    cfg: DemoDataConfig,
    rng: Random,
    *,
    actor_type: ActorType,
    actor_id: str | None,
) -> list[PlantedScenario]:
    """Lay the clean baseline + planted scenarios over the KYC pool. Returns the
    planted scenarios (for case wiring / documentation). Idempotent."""
    inst = _seed_institutions(session, rng, actor_type=actor_type, actor_id=actor_id)
    emitter = _Emitter(TransactionRepository(session), actor_type, actor_id, rng)

    # Draw general scenario actors (chains, cycles, mules) from the HIGHER-income
    # end of the pool, so moving lakhs through them is not itself a 10x income
    # mismatch — that keeps `income_mismatch` firing only on the dedicated
    # profile-mismatch scenarios (low-income individuals, picked explicitly below)
    # instead of double-flagging every mule. Sorted descending; profile-mismatch
    # and structuring actors are selected by predicate, not this cursor.
    pool = sorted(kyc_pool, key=lambda c: -(c.declared_annual_income or 0.0))
    accounts = [_acc(c) for c in pool]
    income_of = {_acc(c): float(c.declared_annual_income or 0.0) for c in pool}
    low_income = [_acc(c) for c in pool
                  if c.entity_type == EntityType.INDIVIDUAL and 0 < income_of[_acc(c)] <= 500_000]
    businesses = [_acc(c) for c in pool if c.entity_type == EntityType.BUSINESS]

    alloc = _Allocator(accounts, rng)
    scenarios: list[PlantedScenario] = []

    def add(key, typology, tier, ids, title, narrative, tp=True) -> None:
        scenarios.append(PlantedScenario(key, typology, tier, ids, title, narrative, tp))

    # profile_mismatch (L1) — low-income individuals receiving crores
    for i in range(min(_COUNTS["profile_mismatch"], len(low_income))):
        acc = low_income[i]
        alloc.primary_used.add(acc)
        _profile_mismatch(emitter, acc, [alloc.borrow() for _ in range(3)], income_of[acc])
        add(f"pm-{i}", "profile_mismatch", "L1", [acc],
            "Income-profile mismatch",
            f"Account received ~15x its declared annual income (₹{income_of[acc]:,.0f}).")

    # structuring (L1) — businesses depositing under the CTR line
    biz = [b for b in businesses if b not in alloc.primary_used]
    for i in range(min(_COUNTS["structuring"], len(biz))):
        src = biz[i]
        alloc.primary_used.add(src)
        dests = [alloc.borrow() for _ in range(4)]
        _structuring(emitter, src, dests, _RECENT + timedelta(days=i), n=rng.randint(3, 5))
        add(f"str-{i}", "structuring", "L1", [src],
            "Structuring below the CTR threshold",
            "Multiple ₹9-10L deposits, each just under the ₹10L reporting line.")

    # dormancy (L1)
    for i in range(_COUNTS["dormancy"]):
        (acc,) = alloc.primary(1)
        _dormancy(emitter, acc, alloc.borrow())
        add(f"dorm-{i}", "dormancy", "L1", [acc],
            "Dormant account reactivation",
            "Long-dormant account erupted with a burst of large transfers.")

    # layering (L2) — exactly 4 accounts (3 hops = the detector minimum) so the
    # chain produces one clean detection, not a fan of overlapping sub-chains.
    for i in range(_COUNTS["layering"]):
        chain = alloc.primary(4)
        _layering(emitter, chain, _RECENT + timedelta(days=10 + i))
        add(f"lay-{i}", "layering", "L2", chain,
            "Multi-hop layering chain",
            "Rapid decreasing-amount chain through intermediaries within minutes.")

    # round_trip (L2)
    for i in range(_COUNTS["round_trip"]):
        cycle = alloc.primary(3)
        _round_trip(emitter, cycle, _RECENT + timedelta(days=20 + i))
        add(f"rt-{i}", "round_trip", "L2", cycle,
            "Round-trip / circular flow",
            "Funds circled back to origin retaining most of their value.")

    # funnel_mule (L2)
    for i in range(_COUNTS["funnel_mule"]):
        mule_and_chain = alloc.primary(4)
        mule, chain = mule_and_chain[0], mule_and_chain[1:]
        senders = [alloc.borrow() for _ in range(3)]
        _funnel_mule(emitter, senders, mule, chain, _RECENT + timedelta(days=25 + i))
        add(f"mule-{i}", "funnel_mule", "L2", mule_and_chain,
            "Funnel / mule ring",
            "Several senders funnelled into one mule that forwarded onward.")

    # false negatives — suspicious but under the radar (no case is expected)
    for i in range(_COUNTS["fn_structuring"]):
        (src,) = alloc.primary(1)
        _fn_structuring(emitter, src, alloc.borrow(), _RECENT + timedelta(days=i))
        add(f"fn-{i}", "structuring", "FN", [src],
            "Structuring under detection floor (false negative)",
            "Only 2 near-threshold deposits — below the min-count-3 rule, so NOT flagged.",
            tp=True)

    # false positives — a legit high-volume business that trips a detector
    for i in range(_COUNTS["fp_business"]):
        fp_src = next((b for b in businesses if b not in alloc.primary_used), None)
        if fp_src is None:
            break
        alloc.primary_used.add(fp_src)
        # 3 large-but-legit settlements just in the band — trips structuring, but
        # the customer is a genuine bullion trader (explainable on inspection).
        _structuring(emitter, fp_src, [alloc.borrow() for _ in range(3)],
                     _RECENT + timedelta(days=i), n=3)
        add(f"fp-{i}", "structuring", "FP", [fp_src],
            "High-volume trader (false positive)",
            "Trips structuring, but volume matches a genuine bullion-trading profile.",
            tp=False)

    # clean baseline for every non-primary account (the credibility anchor)
    for acc in accounts:
        if acc not in alloc.primary_used:
            _baseline(emitter, acc, income_of[acc], inst)

    return scenarios

