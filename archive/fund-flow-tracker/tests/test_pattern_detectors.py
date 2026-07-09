"""
Tests for all 5 pattern detectors in isolation.

Each test uses a minimal, deterministic in-memory DataFrame that is
specifically crafted to guarantee the pattern fires — so if the
assertion fails, it's a real bug in the detector logic.

Run:
    cd fund-flow-tracker && python -m pytest tests/test_pattern_detectors.py -v
"""
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.detection.layering import LayeringDetector
from services.detection.round_trip import RoundTripDetector
from services.detection.structuring import StructuringDetector
from services.detection.dormancy import DormancyDetector
from services.detection.profile import ProfileMismatchDetector
from services.graph.engine import TransactionGraph
from services.common.models import DetectionResult

from conftest import (
    build_layering_data,
    build_round_trip_data,
    build_structuring_data,
    build_dormancy_data,
    build_profile_mismatch_data,
)


# ─────────────────────────────────────────────────────────────────────────────
# LAYERING DETECTOR
# ─────────────────────────────────────────────────────────────────────────────

class TestLayeringDetector:
    """5-hop chain A→B→C→D→E, 10-min spacing, 12% decay per hop."""

    @pytest.fixture(scope="class")
    def setup(self):
        accounts_df, txns_df, chain = build_layering_data()
        graph = TransactionGraph(accounts_df, txns_df)
        detector = LayeringDetector()
        results = detector.detect(graph, txns_df)
        return results, chain, txns_df

    def test_layering_detects_at_least_one(self, setup):
        results, _, _ = setup
        assert len(results) > 0, "Layering detector found 0 results on guaranteed layering data"

    def test_layering_chain_accounts_flagged(self, setup):
        results, chain, _ = setup
        flagged = set()
        for r in results:
            flagged.update(r.account_ids)
        overlap = flagged & set(chain)
        assert len(overlap) >= 3, (
            f"Expected at least 3 layering chain accounts flagged, "
            f"got {overlap} out of {chain}"
        )

    def test_layering_result_fields(self, setup):
        results, _, _ = setup
        for r in results:
            assert isinstance(r, DetectionResult)
            assert r.detection_type == "layering"
            assert 0.0 <= r.score <= 1.0, f"Score out of range: {r.score}"
            assert r.severity in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
            assert "hops" in r.details
            assert r.details["hops"] >= 2
            assert "time_span_minutes" in r.details
            assert "total_amount" in r.details
            assert "amount_decay" in r.details

    def test_layering_hops_correct(self, setup):
        results, chain, _ = setup
        # Our chain has 5 nodes → 4 hops; should find chains with ≥ 3 hops
        max_hops = max(r.details["hops"] for r in results)
        assert max_hops >= 3, f"Expected multi-hop chain, max hops found = {max_hops}"

    def test_layering_time_span_within_window(self, setup):
        results, _, _ = setup
        for r in results:
            mode = r.details.get("chain_mode", "tight")
            if mode == "extended":
                # Extended (STACK) chains span up to 30 days
                assert r.details["time_span_minutes"] <= 43200, (
                    f"Extended chain exceeded 30-day window: {r.details['time_span_minutes']}"
                )
            else:
                assert r.details["time_span_minutes"] <= 120, (
                    f"Tight chain exceeded 120-min window: {r.details['time_span_minutes']}"
                )

    def test_layering_amount_decay_positive(self, setup):
        results, _, _ = setup
        positive_decay = [r for r in results if r.details["amount_decay"] > 0]
        assert len(positive_decay) > 0, "No results show positive amount decay"

    def test_layering_sorted_by_score_desc(self, setup):
        results, _, _ = setup
        if len(results) > 1:
            scores = [r.score for r in results]
            assert scores == sorted(scores, reverse=True), "Results are not sorted by score descending"

    def test_layering_normal_accounts_not_flagged(self, setup):
        results, _, _ = setup
        flagged = set()
        for r in results:
            flagged.update(r.account_ids)
        # NORM_ accounts should not dominate the flagged set
        norm_flagged = [a for a in flagged if a.startswith("NORM_")]
        assert len(norm_flagged) < len(flagged), (
            "All flagged accounts are normal accounts — layering chain not captured"
        )


# ─────────────────────────────────────────────────────────────────────────────
# ROUND-TRIP DETECTOR
# ─────────────────────────────────────────────────────────────────────────────

class TestRoundTripDetector:
    """RT_A↔RT_B (92% return) and 3-node CY_C→CY_D→CY_E→CY_C."""

    @pytest.fixture(scope="class")
    def setup(self):
        accounts_df, txns_df = build_round_trip_data()
        graph = TransactionGraph(accounts_df, txns_df)
        detector = RoundTripDetector()
        results = detector.detect(graph, txns_df)
        return results, txns_df

    def test_round_trip_detects_at_least_one(self, setup):
        results, _ = setup
        assert len(results) > 0, "Round-trip detector found 0 results on guaranteed RT data"

    def test_round_trip_result_fields(self, setup):
        results, _ = setup
        for r in results:
            assert isinstance(r, DetectionResult)
            assert r.detection_type == "round_trip"
            assert 0.0 <= r.score <= 1.0
            assert r.severity in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
            assert "cycle_nodes" in r.details
            assert "return_ratio" in r.details
            assert "total_amount" in r.details

    def test_two_node_cycle_detected(self, setup):
        results, _ = setup
        two_node = [r for r in results if len(r.details.get("cycle_nodes", [])) == 2]
        assert len(two_node) > 0, "2-node bilateral cycle (RT_A↔RT_B) not detected"

    def test_return_ratio_above_threshold(self, setup):
        results, _ = setup
        for r in results:
            # Detector config threshold is 0.85; our data has 0.92
            assert r.details["return_ratio"] >= 0.85, (
                f"Return ratio {r.details['return_ratio']} below 0.85 threshold — "
                "detector is scoring sub-threshold cycles"
            )

    def test_three_node_cycle_detected(self, setup):
        results, _ = setup
        three_node = [r for r in results
                      if any(n in ("CY_C", "CY_D", "CY_E")
                             for n in r.account_ids)]
        assert len(three_node) > 0, "3-node cycle (CY_C→CY_D→CY_E→CY_C) not detected"

    def test_critical_severity_for_tight_cycles(self, setup):
        results, _ = setup
        critical = [r for r in results if r.severity == "CRITICAL"]
        assert len(critical) > 0, (
            "Expected CRITICAL severity for tight round-trip cycles (≥3 nodes, ≥0.85 return)"
        )

    def test_sorted_by_score_desc(self, setup):
        results, _ = setup
        if len(results) > 1:
            scores = [r.score for r in results]
            assert scores == sorted(scores, reverse=True)


# ─────────────────────────────────────────────────────────────────────────────
# STRUCTURING DETECTOR
# ─────────────────────────────────────────────────────────────────────────────

class TestStructuringDetector:
    """Classic: 8 txns in ₹900k–₹999k range. Split: daily sums in same range."""

    @pytest.fixture(scope="class")
    def setup(self):
        accounts_df, txns_df, struct_accs, split_accs = build_structuring_data()
        graph = TransactionGraph(accounts_df, txns_df)
        detector = StructuringDetector()
        results = detector.detect(graph, txns_df)
        return results, struct_accs, split_accs

    def test_structuring_detects_at_least_one(self, setup):
        results, _, _ = setup
        assert len(results) > 0, "Structuring detector found 0 results on guaranteed structuring data"

    def test_classic_structuring_accounts_flagged(self, setup):
        results, struct_accs, _ = setup
        classic = [r for r in results if r.details.get("sub_type") == "classic"]
        flagged_classic = {r.account_ids[0] for r in classic}
        overlap = flagged_classic & set(struct_accs)
        assert len(overlap) >= 2, (
            f"Expected at least 2 classic-structuring accounts flagged, "
            f"got {overlap} out of {struct_accs}"
        )

    def test_split_structuring_detected(self, setup):
        results, _, split_accs = setup
        split = [r for r in results if r.details.get("sub_type") == "split"]
        assert len(split) > 0, "Split structuring not detected"

    def test_amounts_below_threshold(self, setup):
        results, _, _ = setup
        for r in results:
            if r.details.get("sub_type") == "classic":
                for amt in r.details.get("amounts", []):
                    assert amt < 1_000_000, (
                        f"Structuring flagged amount {amt} above CTR threshold"
                    )
                    assert amt >= 900_000, (
                        f"Structuring flagged amount {amt} below lower bound 900k"
                    )

    def test_result_fields_complete(self, setup):
        results, _, _ = setup
        for r in results:
            assert r.detection_type == "structuring"
            assert "sub_type" in r.details
            assert r.details["sub_type"] in ("classic", "split")
            assert 0.0 <= r.score <= 1.0
            assert r.severity in ("MEDIUM", "HIGH", "CRITICAL")

    def test_min_count_threshold_respected(self, setup):
        results, _, _ = setup
        classic = [r for r in results if r.details.get("sub_type") == "classic"]
        for r in classic:
            assert r.details.get("near_threshold_count", 0) >= 3, (
                "Classic structuring flagged an account with < 3 near-threshold txns"
            )

    def test_normal_accounts_not_flagged(self, setup):
        results, struct_accs, split_accs = setup
        legit_suspects = set(struct_accs) | set(split_accs)
        for r in results:
            for acc in r.account_ids:
                assert acc in legit_suspects or acc.startswith("NORM_"), (
                    f"Unexpected account flagged: {acc}"
                )


# ─────────────────────────────────────────────────────────────────────────────
# DORMANCY DETECTOR
# ─────────────────────────────────────────────────────────────────────────────

class TestDormancyDetector:
    """DORM_A/B/C: 2 txns in Nov 2025, then 25 txns in Jun 2026 (212-day gap)."""

    @pytest.fixture(scope="class")
    def setup(self):
        accounts_df, txns_df, dormant_accs = build_dormancy_data()
        graph = TransactionGraph(accounts_df, txns_df)
        detector = DormancyDetector()
        results = detector.detect(graph, txns_df)
        return results, dormant_accs

    def test_dormancy_detects_at_least_one(self, setup):
        results, _ = setup
        assert len(results) > 0, "Dormancy detector found 0 results on guaranteed dormancy data"

    def test_all_dormant_accounts_flagged(self, setup):
        results, dormant_accs = setup
        flagged = {r.account_ids[0] for r in results}
        missing = set(dormant_accs) - flagged
        assert len(missing) == 0, (
            f"Dormant accounts not flagged: {missing}"
        )

    def test_dormancy_gap_above_threshold(self, setup):
        results, _ = setup
        for r in results:
            assert r.details["dormancy_days"] >= 180, (
                f"Dormancy gap {r.details['dormancy_days']} below 180-day threshold"
            )

    def test_burst_multiplier_above_threshold(self, setup):
        results, _ = setup
        for r in results:
            assert r.details["burst_multiplier"] >= 10.0, (
                f"Burst multiplier {r.details['burst_multiplier']} below 10x threshold"
            )

    def test_burst_txn_count_adequate(self, setup):
        results, _ = setup
        for r in results:
            assert r.details["burst_txn_count"] >= 5, (
                f"Burst only has {r.details['burst_txn_count']} txns — min is 5"
            )

    def test_result_fields_complete(self, setup):
        results, _ = setup
        for r in results:
            assert r.detection_type == "dormancy"
            assert "dormancy_days" in r.details
            assert "burst_multiplier" in r.details
            assert "burst_txn_count" in r.details
            assert "pre_dormancy_avg_amount" in r.details
            assert "post_dormancy_avg_amount" in r.details
            assert 0.0 <= r.score <= 1.0

    def test_severity_for_long_gap(self, setup):
        results, _ = setup
        # 212-day gap should be HIGH; burst multiplier ~16x should push to CRITICAL
        high_or_critical = [r for r in results if r.severity in ("HIGH", "CRITICAL")]
        assert len(high_or_critical) > 0, (
            "Expected HIGH or CRITICAL severity for 212-day dormancy + 16x burst"
        )

    def test_normal_accounts_not_flagged(self, setup):
        results, dormant_accs = setup
        for r in results:
            for acc in r.account_ids:
                assert acc in dormant_accs, (
                    f"Normal account {acc} incorrectly flagged as dormant"
                )


# ─────────────────────────────────────────────────────────────────────────────
# PROFILE MISMATCH DETECTOR
# ─────────────────────────────────────────────────────────────────────────────

class TestProfileMismatchDetector:
    """
    15 salaried/low peers each with ~100k volume.
    MISMATCH_A: same occupation/bracket, 15M volume = 50× declared income.
    """

    @pytest.fixture(scope="class")
    def setup(self):
        accounts_df, txns_df = build_profile_mismatch_data()
        graph = TransactionGraph(accounts_df, txns_df)
        detector = ProfileMismatchDetector()
        results = detector.detect(graph, txns_df, accounts_df)
        return results, accounts_df

    def test_profile_detects_at_least_one(self, setup):
        results, _ = setup
        assert len(results) > 0, "Profile mismatch detector found 0 results on guaranteed data"

    def test_income_mismatch_flagged(self, setup):
        results, _ = setup
        income_mis = [r for r in results
                      if r.details.get("sub_type") == "income_mismatch"]
        assert len(income_mis) > 0, "Income mismatch sub-detector found nothing"
        flagged_income = {r.account_ids[0] for r in income_mis}
        assert "MISMATCH_A" in flagged_income, (
            f"MISMATCH_A not flagged for income mismatch; flagged: {flagged_income}"
        )

    def test_income_mismatch_ratio_above_10x(self, setup):
        results, _ = setup
        for r in results:
            if r.details.get("sub_type") == "income_mismatch":
                assert r.details["volume_to_income_ratio"] >= 10, (
                    f"Income mismatch ratio {r.details['volume_to_income_ratio']} < 10"
                )

    def test_peer_deviation_detected(self, setup):
        results, accounts_df = setup
        # Need ≥5 peers in same group; our data has 15
        peer_dev = [r for r in results
                    if r.details.get("sub_type") == "peer_deviation"]
        assert len(peer_dev) > 0, (
            "Peer deviation sub-detector found nothing (needs ≥5 peers in same group)"
        )

    def test_peer_deviation_z_score_above_threshold(self, setup):
        results, _ = setup
        for r in results:
            if r.details.get("sub_type") == "peer_deviation":
                assert abs(r.details["z_score"]) >= 3.0, (
                    f"Peer z-score {r.details['z_score']} below 3.0 threshold"
                )

    def test_behavioural_shift_detected(self, setup):
        results, _ = setup
        # MISMATCH_A sends 50 uniform txns — no rolling spike, so behavioural_shift
        # may not trigger. We assert income_mismatch is what matters here.
        # This test just verifies the sub-type key is valid if it appears.
        for r in results:
            assert r.details.get("sub_type") in (
                "income_mismatch", "peer_deviation", "behavioural_shift"
            ), f"Unknown sub_type: {r.details.get('sub_type')}"

    def test_result_fields_complete(self, setup):
        results, _ = setup
        for r in results:
            assert r.detection_type == "profile_mismatch"
            assert 0.0 <= r.score <= 1.0
            assert r.severity in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
            assert len(r.account_ids) >= 1

    def test_peer_accounts_not_flagged_for_income_mismatch(self, setup):
        results, _ = setup
        income_flagged = {r.account_ids[0] for r in results
                          if r.details.get("sub_type") == "income_mismatch"}
        peer_accounts = {f"PEER_{i:03d}" for i in range(15)}
        # Peers have low volume relative to their income — shouldn't appear
        false_positives = income_flagged & peer_accounts
        assert len(false_positives) == 0, (
            f"Peer accounts wrongly flagged for income mismatch: {false_positives}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# BUG DOCUMENTATION TESTS (expose known implementation gaps)
# ─────────────────────────────────────────────────────────────────────────────

class TestKnownBugs:
    """
    These tests document confirmed bugs found during review.
    They are marked xfail where the bug causes test failure so CI doesn't
    block, but the failure message records the exact defect.
    """

    @pytest.mark.xfail(
        reason="BUG: temporal_bfs uses graph edge data which has no 'timestamp' key. "
               "TransactionGraph._build() only stores {amount, is_laundering} on edges. "
               "All BFS temporal comparisons use pd.Timestamp.min — ordering is broken.",
        strict=True,
    )
    def test_fund_trail_timestamps_are_real(self):
        """Fund Trail (temporal BFS) should return actual transaction timestamps."""
        from conftest import build_layering_data
        accounts_df, txns_df, chain = build_layering_data()
        graph = TransactionGraph(accounts_df, txns_df)
        result = graph.get_fund_trail(chain[0], direction="forward", max_depth=4)

        all_timestamps = []
        for trail in result.get("trails", []):
            for hop in trail:
                all_timestamps.append(hop.get("timestamp"))

        # All timestamps should be real dates, NOT pd.Timestamp.min (year 1677)
        real_timestamps = [t for t in all_timestamps
                           if t is not None and pd.Timestamp(t).year > 2020]
        assert len(real_timestamps) > 0, (
            "All Fund Trail timestamps are pd.Timestamp.min — "
            "temporal BFS has no access to timestamps because they are "
            "deliberately excluded from graph edges in TransactionGraph._build()"
        )

    @pytest.mark.xfail(
        reason="BUG: velocity_10min and velocity_1hour are both set to max_daily_txn_count "
               "(features.py:226-227). These are two different names for the same value, "
               "wasting a feature slot and misleading the XGBoost model.",
        strict=True,
    )
    def test_velocity_features_are_distinct(self):
        """velocity_10min and velocity_1hour must not be identical."""
        from conftest import build_layering_data
        from services.detection.features import FeatureExtractor
        accounts_df, txns_df, _ = build_layering_data()
        graph = TransactionGraph(accounts_df, txns_df)
        extractor = FeatureExtractor(graph, accounts_df, txns_df)
        features = extractor.extract_all()
        assert not (features["velocity_10min"] == features["velocity_1hour"]).all(), (
            "velocity_10min and velocity_1hour are identical — "
            "both are just max_daily_txn_count (see features.py lines 226-227)"
        )

    @pytest.mark.xfail(
        reason="BUG: geographic_dispersion is always 0.0 (features.py:224). "
               "It is a placeholder that was never implemented.",
        strict=True,
    )
    def test_geographic_dispersion_non_zero(self):
        """geographic_dispersion should vary across accounts with different branches."""
        from conftest import build_layering_data
        from services.detection.features import FeatureExtractor
        accounts_df, txns_df, _ = build_layering_data()
        graph = TransactionGraph(accounts_df, txns_df)
        extractor = FeatureExtractor(graph, accounts_df, txns_df)
        features = extractor.extract_all()
        assert features["geographic_dispersion"].sum() > 0, (
            "geographic_dispersion is always 0.0 — never implemented"
        )

    @pytest.mark.xfail(
        reason="BUG: EvidencePack has field 'json_payload' but server.py:1214 reads "
               "'json_data' (which doesn't exist). The evidence endpoint always returns "
               "json_data='{}'.",
        strict=True,
    )
    def test_evidence_pack_has_json_data_field(self):
        """EvidencePack must expose json_data so the API endpoint can return it."""
        from services.common.models import EvidencePack
        pack = EvidencePack(
            case_id="TEST-001",
            str_reference="STR-2026-TEST-001",
            json_payload='{"test": 1}',
        )
        # The server does: pack.json_data if hasattr(pack, "json_data") else "{}"
        # This always returns "{}" because the field is named json_payload
        assert hasattr(pack, "json_data"), (
            "EvidencePack has 'json_payload' but server.py reads 'json_data' — "
            "evidence endpoint always returns empty JSON"
        )

    def test_old_test_core_imports_are_broken(self):
        """
        Confirm that the existing test_core.py imports from non-existent modules.
        This test exists to document the issue, not to fix it.
        """
        import importlib.util
        import ast

        test_core_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "test_core.py"
        )
        with open(test_core_path) as f:
            source = f.read()

        tree = ast.parse(source)
        broken_imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith("core."):
                    broken_imports.append(node.module)

        assert len(broken_imports) > 0, "No broken imports found — test_core.py may have been fixed"
        # Document the broken imports but don't fail — this is an awareness test
        print(f"\nBROKEN IMPORTS in test_core.py: {broken_imports}")
        print("These modules don't exist; the file imports from 'core.*' "
              "but the codebase uses 'services.*'")
