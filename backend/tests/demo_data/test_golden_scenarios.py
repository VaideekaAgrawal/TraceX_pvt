"""
Verifies every golden scenario's fabricated transactions actually trip its
`expected_detection_type`'s real pattern detector under
`detection.config.DEFAULT_DETECTION_CONFIG`'s real thresholds -- not just
described in prose (`golden_scenarios.py`'s module docstring / ROADMAP
Phase 1B verification step 3).
"""
from __future__ import annotations

import random

from sqlalchemy.orm import Session

from db.enums import ActorType
from demo_data.golden_scenarios import SCENARIOS, seed_golden_scenarios
from detection.data import accounts_touched_by, load_accounts_df, load_transactions_df
from detection.detectors.dormancy import DormancyDetector
from detection.detectors.layering import LayeringDetector
from detection.detectors.profile import ProfileMismatchDetector
from detection.detectors.round_trip import RoundTripDetector
from detection.detectors.structuring import StructuringDetector
from detection.graph.networkx_store import NetworkXGraphStore
from detection.types import DetectionResult

_ACTOR_ID = "test-golden-scenarios"

_DETECTORS = {
    "layering": lambda gs, tdf, adf: LayeringDetector().detect(gs, tdf),
    "structuring": lambda gs, tdf, adf: StructuringDetector().detect(gs, tdf),
    "round_trip": lambda gs, tdf, adf: RoundTripDetector().detect(gs, tdf),
    "dormancy": lambda gs, tdf, adf: DormancyDetector().detect(gs, tdf),
    "profile_mismatch": lambda gs, tdf, adf: ProfileMismatchDetector().detect(gs, tdf, adf),
}


def _fires_on(results: list[DetectionResult], account_ids: set[str]) -> bool:
    return any(set(str(a) for a in r.account_ids) & account_ids for r in results)


def test_every_golden_scenario_triggers_its_expected_detection_type(session: Session) -> None:
    rng = random.Random(1)
    results = seed_golden_scenarios(
        session, rng, actor_type=ActorType.SYSTEM, actor_id=_ACTOR_ID
    )
    session.commit()
    assert len(results) == len(SCENARIOS) == 7

    scenario_accounts = {r.key: set(r.account_ids) for r in results}

    transactions_df = load_transactions_df(session)
    accounts_df = load_accounts_df(session, accounts_touched_by(transactions_df))
    graph_store = NetworkXGraphStore(accounts_df, transactions_df)

    fired: dict[str, list[DetectionResult]] = {
        dtype: fn(graph_store, transactions_df, accounts_df) for dtype, fn in _DETECTORS.items()
    }

    for scenario in SCENARIOS:
        detector_results = fired[scenario.expected_detection_type]
        accounts = scenario_accounts[scenario.key]
        assert _fires_on(detector_results, accounts), (
            f"scenario {scenario.key!r} did not trigger a "
            f"{scenario.expected_detection_type!r} detection touching any of "
            f"its own accounts {sorted(accounts)}"
        )
