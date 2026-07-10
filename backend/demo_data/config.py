"""
Demo Data Studio configuration -- pool sizes, the reserved id prefix, and the
fixed RNG seed that makes generation reproducible (ROADMAP Phase 1B: "make
generation seeded/reproducible").

`DEMO_SEED` is a fixed literal (not derived from wall-clock time or any
external input), following the same "pin a literal, document why" precedent
`detection/graph/networkx_store.py::get_transaction_chains` already uses for
its own `shuffle_starts` path (`random.Random(42)`) and
`detection/config.py`'s tuned-hyperparameter constants -- a fixed seed here
means the exact same demo dataset (same accounts, same clusters, same golden
scenarios) is produced on every machine/run, which matters for a pitch demo
that has to be identical every time it's rehearsed.
"""
from __future__ import annotations

from dataclasses import dataclass

#: Reserved prefix for every id this package creates -- the isolation marker
#: (alongside per-generator `ingestion_log` rows) that keeps demo data
#: trivially distinguishable from, and never confusable with, real ingested
#: data (`docs/DATA_SCHEMA.md` §6(c)).
DEMO_PREFIX = "DEMO-"

#: Fixed seed, chosen arbitrarily (mirrors the date this phase's planning
#: session ran) -- the load-bearing property is that it never changes, not
#: what the specific number is.
DEMO_SEED = 20260701


@dataclass(frozen=True)
class DemoDataConfig:
    """Pool sizes for each sub-generator. All counts are approximate targets
    (percentage-based splits round to the nearest integer, so actual counts
    may differ from the literal number by a handful) -- see each
    generator's own module docstring for the exact rounding behavior."""

    prefix: str = DEMO_PREFIX

    # -- KYC/customer pool (kyc_customers.py) --
    num_kyc_customers: int = 200
    pct_pep: float = 0.04
    pct_sanctioned: float = 0.02
    pct_income_mismatch: float = 0.15

    # -- Relationship networks (relationships.py) --
    num_relationship_clusters: int = 8
    relationship_cluster_min_size: int = 2
    relationship_cluster_max_size: int = 4

    # -- Historical training corpus (historical_cases.py) --
    num_historical_cases: int = 50
    pct_false_positive: float = 0.50
    pct_true_positive_sar: float = 0.35
    pct_enhanced_monitoring: float = 0.15


DEFAULT_DEMO_DATA_CONFIG = DemoDataConfig()
