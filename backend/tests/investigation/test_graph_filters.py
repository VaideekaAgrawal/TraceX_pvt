"""
`investigation.graph_filters` -- ROADMAP Phase 6 N-hop + filter engine.

`apply_filters` is tested as a pure function (hand-built node/edge dicts, no
DB) per the module's own "pure-function-first, testable without HTTP"
design goal. `annotate_nodes`/`get_filtered_ego_graph` are tested against a
seeded multi-hop DB graph, mirroring `tests/investigation/test_network_risk.
py`'s "independently recompute the same signal, then assert" style for the
one genuinely subtle claim this module makes: role classification is
legitimately different at different radii over the SAME seed data.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from db.enums import (
    ActorType,
    CaseLevel,
    CaseResolution,
    CaseStatus,
    Channel,
    DetectionType,
    Priority,
    RiskLevel,
)
from db.repositories.detection import AlertRepository
from db.repositories.investigation import CaseAccountRepository, CaseRepository
from db.repositories.reference import AccountRepository, TransactionRepository
from detection.scoring.ensemble import RoleClassifier
from investigation.graph_filters import (
    GraphFilters,
    apply_filters,
    build_subgraph_store,
    get_filtered_ego_graph,
)

UTC_TS = datetime(2026, 1, 1, tzinfo=UTC)


def _node(
    account_id: str, *, role: str = "NORMAL", risk: float | None = 50.0,
    prior_sar: bool = False, hop: int = 0,
) -> dict:
    return {
        "account_id": account_id,
        "branch_city": None,
        "role": role,
        "role_confidence": 1.0,
        "current_risk_score": risk,
        "has_prior_sar": prior_sar,
        "hop_distance": hop,
    }


def _edge(
    txn_id: str, src: str, dst: str, amount: float, *,
    channel: str = "UPI", is_laundering: int = 0, ts: datetime = UTC_TS,
) -> dict:
    return {
        "txn_id": txn_id,
        "source_account": src,
        "dest_account": dst,
        "amount": amount,
        "channel": channel,
        "is_laundering": is_laundering,
        "timestamp": ts,
        "from_bank": None,
        "to_bank": None,
    }


# ── apply_filters: pure-function tests (no DB) ───────────────────────────


def test_apply_filters_no_filters_returns_everything() -> None:
    nodes = [_node("C"), _node("A"), _node("B")]
    edges = [_edge("T1", "C", "A", 100.0), _edge("T2", "B", "C", 50.0)]

    filtered_nodes, filtered_edges = apply_filters(nodes, edges, "C", GraphFilters())

    assert {n["account_id"] for n in filtered_nodes} == {"C", "A", "B"}
    assert {e["txn_id"] for e in filtered_edges} == {"T1", "T2"}


def test_apply_filters_suspicious_only() -> None:
    nodes = [_node("C"), _node("A"), _node("B")]
    edges = [
        _edge("T1", "C", "A", 100.0, is_laundering=1),
        _edge("T2", "B", "C", 50.0, is_laundering=0),
    ]

    filtered_nodes, filtered_edges = apply_filters(
        nodes, edges, "C", GraphFilters(suspicious_only=True)
    )

    assert {e["txn_id"] for e in filtered_edges} == {"T1"}
    assert {n["account_id"] for n in filtered_nodes} == {"C", "A"}  # B pruned with its only edge


def test_apply_filters_amount_range() -> None:
    nodes = [_node("C"), _node("A"), _node("B")]
    edges = [_edge("T1", "C", "A", 100.0), _edge("T2", "B", "C", 5_000.0)]

    _, min_filtered = apply_filters(nodes, edges, "C", GraphFilters(min_amount=1_000.0))
    assert {e["txn_id"] for e in min_filtered} == {"T2"}

    _, max_filtered = apply_filters(nodes, edges, "C", GraphFilters(max_amount=1_000.0))
    assert {e["txn_id"] for e in max_filtered} == {"T1"}


def test_apply_filters_time_window() -> None:
    nodes = [_node("C"), _node("A")]
    early = datetime(2026, 1, 1, tzinfo=UTC)
    late = datetime(2026, 6, 1, tzinfo=UTC)
    edges = [_edge("T1", "C", "A", 100.0, ts=early), _edge("T2", "C", "A", 100.0, ts=late)]

    _, filtered_edges = apply_filters(
        nodes, edges, "C", GraphFilters(start=datetime(2026, 3, 1, tzinfo=UTC))
    )
    assert {e["txn_id"] for e in filtered_edges} == {"T2"}

    _, end_filtered = apply_filters(
        nodes, edges, "C", GraphFilters(end=datetime(2026, 3, 1, tzinfo=UTC))
    )
    assert {e["txn_id"] for e in end_filtered} == {"T1"}


def test_apply_filters_channels() -> None:
    nodes = [_node("C"), _node("A"), _node("B")]
    edges = [
        _edge("T1", "C", "A", 100.0, channel="UPI"),
        _edge("T2", "B", "C", 50.0, channel="branch_cash"),
    ]

    _, filtered_edges = apply_filters(nodes, edges, "C", GraphFilters(channels=["branch_cash"]))
    assert {e["txn_id"] for e in filtered_edges} == {"T2"}


def test_apply_filters_direction_only_touches_center_adjacent_edges() -> None:
    nodes = [_node("C"), _node("A"), _node("B"), _node("X"), _node("Y")]
    edges = [
        _edge("OUT1", "C", "A", 100.0),  # outbound from center
        _edge("IN1", "B", "C", 100.0),  # inbound to center
        _edge("FAR1", "X", "Y", 100.0),  # doesn't touch center -- 2+ hops away
    ]

    _, out_edges = apply_filters(nodes, edges, "C", GraphFilters(direction="out"))
    assert {e["txn_id"] for e in out_edges} == {"OUT1", "FAR1"}  # FAR1 passes through unfiltered

    _, in_edges = apply_filters(nodes, edges, "C", GraphFilters(direction="in"))
    assert {e["txn_id"] for e in in_edges} == {"IN1", "FAR1"}


def test_apply_filters_roles() -> None:
    nodes = [_node("C", role="NORMAL"), _node("A", role="MULE"), _node("B", role="SOURCE")]
    edges = [_edge("T1", "C", "A", 100.0), _edge("T2", "B", "C", 50.0)]

    filtered_nodes, filtered_edges = apply_filters(nodes, edges, "C", GraphFilters(roles=["MULE"]))

    # C (center) survives the touched-by-edge prune but is NOT exempt from
    # the node-level role filter -- it fails it (role=NORMAL), so both edges
    # lose an endpoint and disappear too.
    assert {n["account_id"] for n in filtered_nodes} == {"A"}
    assert filtered_edges == []


def test_apply_filters_prior_sar_only() -> None:
    nodes = [_node("C", prior_sar=True), _node("A", prior_sar=False), _node("B", prior_sar=True)]
    edges = [_edge("T1", "C", "A", 100.0), _edge("T2", "B", "C", 50.0)]

    filtered_nodes, filtered_edges = apply_filters(
        nodes, edges, "C", GraphFilters(prior_sar_only=True)
    )
    assert {n["account_id"] for n in filtered_nodes} == {"C", "B"}
    assert {e["txn_id"] for e in filtered_edges} == {"T2"}  # T1 lost A's endpoint


def test_apply_filters_and_combination() -> None:
    nodes = [_node("C", risk=90.0), _node("A", risk=90.0), _node("B", risk=10.0)]
    edges = [
        _edge("T1", "C", "A", 5_000.0, is_laundering=1, channel="UPI"),
        _edge("T2", "B", "C", 5_000.0, is_laundering=1, channel="UPI"),
    ]

    filtered_nodes, filtered_edges = apply_filters(
        nodes, edges, "C",
        GraphFilters(suspicious_only=True, min_amount=1_000.0, min_risk_score=50.0),
    )
    # Both edges pass the edge-level AND; B then fails min_risk_score, so
    # its edge (T2) is dropped at the node-pruning step.
    assert {n["account_id"] for n in filtered_nodes} == {"C", "A"}
    assert {e["txn_id"] for e in filtered_edges} == {"T1"}


def test_apply_filters_center_survives_isolation() -> None:
    nodes = [_node("C"), _node("A")]
    edges = [_edge("T1", "C", "A", 100.0)]

    filtered_nodes, filtered_edges = apply_filters(
        nodes, edges, "C", GraphFilters(min_amount=1_000.0)  # filters out the only edge
    )
    assert {n["account_id"] for n in filtered_nodes} == {"C"}
    assert filtered_edges == []


def test_apply_filters_direction_self_loop_passes_under_either_direction() -> None:
    """Regression test (code-review finding, Phase 6): a self-loop
    transaction on `center` is simultaneously incoming and outgoing to
    itself, so it must survive under EITHER `direction` filter, not be
    unconditionally dropped by both."""
    nodes = [_node("C")]
    edges = [_edge("LOOP", "C", "C", 100.0)]

    _, out_edges = apply_filters(nodes, edges, "C", GraphFilters(direction="out"))
    assert {e["txn_id"] for e in out_edges} == {"LOOP"}

    _, in_edges = apply_filters(nodes, edges, "C", GraphFilters(direction="in"))
    assert {e["txn_id"] for e in in_edges} == {"LOOP"}


# ── DB-backed: annotate_nodes / get_filtered_ego_graph ───────────────────


def _seed_account(session: Session, account_id: str) -> None:
    AccountRepository(session).create(
        account_id=account_id, actor_type=ActorType.SYSTEM, actor_id=None
    )


def _seed_txn(session: Session, txn_id: str, src: str, dst: str, amount: float) -> None:
    TransactionRepository(session).create(
        txn_id=txn_id, timestamp=UTC_TS, source_account=src, dest_account=dst,
        amount=amount, channel=Channel.NEFT, is_laundering=0, ingested_at=UTC_TS,
        actor_type=ActorType.SYSTEM, actor_id=None,
    )


def _seed_case(session: Session, case_id: str, primary: str, account_ids: list[str]) -> None:
    CaseRepository(session).create(
        case_id=case_id, primary_account_id=primary, status=CaseStatus.IN_PROGRESS,
        level=CaseLevel.L2, priority=Priority.P2, actor_type=ActorType.SYSTEM, actor_id=None,
    )
    for account_id in account_ids:
        CaseAccountRepository(session).add_account(
            case_id=case_id, account_id=account_id, actor_type=ActorType.SYSTEM, actor_id=None
        )


def test_get_filtered_ego_graph_no_filter_matches_raw_ego(session: Session) -> None:
    for account_id in ("CENTER", "HOP1A", "HOP1B"):
        _seed_account(session, account_id)
    session.commit()
    _seed_txn(session, "T1", "CENTER", "HOP1A", 100.0)
    _seed_txn(session, "T2", "HOP1B", "CENTER", 50.0)
    session.commit()
    _seed_case(session, "CASE1", "CENTER", ["CENTER", "HOP1A", "HOP1B"])
    session.commit()

    result = get_filtered_ego_graph(
        session, "CASE1", "CENTER", radius=1, filters=GraphFilters(),
        case_account_ids=["CENTER", "HOP1A", "HOP1B"],
    )

    assert {n["account_id"] for n in result["nodes"]} == {"CENTER", "HOP1A", "HOP1B"}
    assert {e["txn_id"] for e in result["edges"]} == {"T1", "T2"}
    assert result["center"] == "CENTER"
    assert result["radius"] == 1


def test_get_filtered_ego_graph_radius_clamped_to_max() -> None:
    from investigation.graph_filters import MAX_RADIUS

    assert MAX_RADIUS == 4  # documented safety-valve value the plan specifies


def test_get_filtered_ego_graph_center_survives_when_it_has_zero_transactions(
    session: Session,
) -> None:
    """Regression test (code-review finding, Phase 6, highest severity):
    `NetworkXGraphStore._build()` only seeds isolated accounts-df nodes when
    the WHOLE case's transaction set is empty, not per-account -- so a
    case-linked account with zero transactions, in a case where OTHER
    linked accounts DO have transactions, used to be silently dropped from
    the N-hop graph response entirely (`get_ego_graph` returned it with
    `nodes: []`), breaking `apply_filters`' documented "center always
    survives" guarantee. `CENTER` here has no transactions at all; `A`/`B`
    do (between themselves, not touching `CENTER`) so the case's overall
    transaction set is non-empty."""
    for account_id in ("CENTER", "A", "B"):
        _seed_account(session, account_id)
    session.commit()
    _seed_txn(session, "T1", "A", "B", 100.0)  # doesn't touch CENTER at all
    session.commit()
    _seed_case(session, "CASE1", "CENTER", ["CENTER", "A", "B"])
    session.commit()

    result = get_filtered_ego_graph(
        session, "CASE1", "CENTER", radius=2, filters=GraphFilters(),
        case_account_ids=["CENTER", "A", "B"],
    )

    assert [n["account_id"] for n in result["nodes"]] == ["CENTER"]
    assert result["edges"] == []
    assert result["center"] == "CENTER"


def test_annotate_nodes_prior_sar_is_network_wide(session: Session) -> None:
    """`has_prior_sar` reuses `investigation.previous_alerts`'s pattern but
    extended to EVERY node in the ego-graph, not just the case's own
    accounts (ROADMAP Phase 6: the network-wide reach `previous_alerts.py`
    explicitly defers here)."""
    for account_id in ("CENTER", "NEIGHBOR"):
        _seed_account(session, account_id)
    session.commit()
    _seed_txn(session, "T1", "CENTER", "NEIGHBOR", 100.0)
    session.commit()

    # A prior, closed TRUE_POSITIVE_SAR case whose primary account is
    # NEIGHBOR -- NOT one of the current case's own linked accounts.
    CaseRepository(session).create(
        case_id="OLD_CASE", primary_account_id="NEIGHBOR", status=CaseStatus.CLOSED_TP,
        level=CaseLevel.L1, priority=Priority.P1, actor_type=ActorType.SYSTEM, actor_id=None,
    )
    CaseRepository(session).update(
        "OLD_CASE", resolution=CaseResolution.TRUE_POSITIVE_SAR,
        actor_type=ActorType.SYSTEM, actor_id=None,
    )
    AlertRepository(session).create(
        alert_id="OLD_ALERT", detection_type=DetectionType.round_trip,
        primary_account_id="NEIGHBOR", account_ids=["NEIGHBOR"], score=0.9, risk_score=95.0,
        severity=RiskLevel.CRITICAL, priority=Priority.P1, status="closed", source="pipeline",
        case_id="OLD_CASE", actor_type=ActorType.SYSTEM, actor_id=None,
    )
    session.commit()

    _seed_case(session, "CASE1", "CENTER", ["CENTER"])  # case only formally links CENTER
    session.commit()

    result = get_filtered_ego_graph(
        session, "CASE1", "CENTER", radius=1, filters=GraphFilters(),
        case_account_ids=["CENTER"],
    )

    by_id = {n["account_id"]: n for n in result["nodes"]}
    assert by_id["CENTER"]["has_prior_sar"] is False
    assert by_id["NEIGHBOR"]["has_prior_sar"] is True  # network-wide, not case-account-only


def test_role_is_relative_to_ego_radius_over_same_seed(session: Session) -> None:
    """The core design-decision proof (ROADMAP plan): role classification
    over the ego-subgraph is legitimately different at different radii for
    the SAME underlying seed data -- a second, radius-scoped computation
    distinct from `investigation.network_risk`'s case-wide one."""
    for account_id in ("CENTER", "HOP1A", "HOP2A"):
        _seed_account(session, account_id)
    session.commit()
    _seed_txn(session, "T1", "CENTER", "HOP1A", 1_000.0)
    _seed_txn(session, "T2", "HOP1A", "HOP2A", 9_000.0)  # only visible at radius >= 2
    session.commit()
    _seed_case(session, "CASE1", "CENTER", ["CENTER", "HOP1A", "HOP2A"])
    session.commit()

    case_account_ids = ["CENTER", "HOP1A", "HOP2A"]
    result_r1 = get_filtered_ego_graph(
        session, "CASE1", "CENTER", radius=1, filters=GraphFilters(),
        case_account_ids=case_account_ids,
    )
    result_r2 = get_filtered_ego_graph(
        session, "CASE1", "CENTER", radius=2, filters=GraphFilters(),
        case_account_ids=case_account_ids,
    )

    role_r1 = next(n["role"] for n in result_r1["nodes"] if n["account_id"] == "HOP1A")
    role_r2 = next(n["role"] for n in result_r2["nodes"] if n["account_id"] == "HOP1A")

    # Independently recompute both, mirroring test_network_risk.py's own
    # "recompute the underlying signal, then assert" style.
    from investigation.case_graph import build_case_graph_store

    graph = build_case_graph_store(session, case_account_ids)
    ego1 = graph.get_ego_graph("CENTER", radius=1)
    ego2 = graph.get_ego_graph("CENTER", radius=2)
    expected_r1 = RoleClassifier().classify_all(build_subgraph_store(ego1))["HOP1A"]["role"]
    expected_r2 = RoleClassifier().classify_all(build_subgraph_store(ego2))["HOP1A"]["role"]

    assert role_r1 == expected_r1
    assert role_r2 == expected_r2
    assert role_r1 != role_r2, "role must differ between a tight and wide radius over the same seed"
    # Pinned to the concrete values this fixture is engineered to produce,
    # so a change in `RoleClassifier`'s formula that happens to still leave
    # role_r1 != role_r2 (but produces the WRONG roles) doesn't silently
    # pass this test.
    assert role_r1 == "SINK"
    assert role_r2 == "NORMAL"

    # hop_distance is inline on every node, relative to `center`.
    by_id_r2 = {n["account_id"]: n for n in result_r2["nodes"]}
    assert by_id_r2["CENTER"]["hop_distance"] == 0
    assert by_id_r2["HOP1A"]["hop_distance"] == 1
    assert by_id_r2["HOP2A"]["hop_distance"] == 2
