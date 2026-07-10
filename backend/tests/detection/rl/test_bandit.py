from __future__ import annotations

import numpy as np

from db.repositories.detection import RlArmStateRepository
from detection.rl.bandit import GLOBAL_ARM_ID, LinUCBAgent


def _account(**overrides) -> dict:
    base = {
        "risk_score": 80,
        "anomaly_score": 60,
        "fraud_probability": 0.7,
        "patterns": ["layering", "round_trip"],
        "role": "MULE",
        "total_amount": 500_000,
        "counterparties": 10,
        "declared_annual_income": 500_000,
        "total_in_flow": 1_000_000,
        "total_out_flow": 1_000_000,
        "channel_diversity": 2,
    }
    base.update(overrides)
    return base


def test_build_context_is_16_dim_and_bounded(session) -> None:
    agent = LinUCBAgent(session)
    ctx = agent.build_context(_account())
    assert ctx.shape == (16,)
    assert len(LinUCBAgent.FEATURE_NAMES) == 16
    # bias term is always 1.0
    assert ctx[-1] == 1.0
    assert 0.0 <= ctx[0] <= 1.0  # risk_score_norm


def test_fresh_agent_starts_at_identity_zero(session) -> None:
    agent = LinUCBAgent(session)
    assert np.array_equal(agent.A, np.identity(agent.d))
    assert np.array_equal(agent.b, np.zeros(agent.d))


def test_score_returns_expected_uncertainty_ucb(session) -> None:
    agent = LinUCBAgent(session, alpha=1.0)
    ctx = agent.build_context(_account())
    expected, uncertainty, ucb = agent.score(ctx)
    assert isinstance(expected, float)
    assert uncertainty >= 0.0
    assert ucb == expected + agent.alpha * uncertainty


def test_update_shifts_expected_reward_toward_positive_feedback(session) -> None:
    agent = LinUCBAgent(session)
    ctx = agent.build_context(_account())
    expected_before, _, _ = agent.score(ctx)
    agent.update(ctx, reward=1.0)
    expected_after, _, _ = agent.score(ctx)
    assert expected_after > expected_before


def test_update_persists_to_rl_arm_state(session) -> None:
    agent = LinUCBAgent(session)
    ctx = agent.build_context(_account())
    agent.update(ctx, reward=1.0)
    # update()/_save_state() only flush -- callers own the commit (same
    # convention as every repository in this codebase).
    session.commit()

    repo = RlArmStateRepository(session)
    state = repo.get(GLOBAL_ARM_ID)
    assert state is not None
    assert np.array(state.a_matrix).shape == (16, 16)
    assert np.array(state.b_vector).shape == (16,)


def test_fresh_instance_reloads_persisted_state_not_identity(session) -> None:
    """The actual landmine this port exists to fix: a second, independent
    LinUCBAgent instance must resume from durably persisted state instead
    of resetting to identity/zero."""
    agent1 = LinUCBAgent(session)
    ctx = agent1.build_context(_account())
    agent1.update(ctx, reward=1.0)
    agent1.update(agent1.build_context(_account(risk_score=20)), reward=-0.3)
    # Caller commits -- update()/_save_state() only flush.
    session.commit()

    agent2 = LinUCBAgent(session)
    assert np.allclose(agent2.A, agent1.A)
    assert np.allclose(agent2.b, agent1.b)
    assert not np.array_equal(agent2.A, np.identity(agent2.d))


def test_rank_accounts_sorts_by_ucb_descending(session) -> None:
    agent = LinUCBAgent(session)
    accounts = [
        {"account_id": "LOW", **_account(risk_score=5, anomaly_score=5, fraud_probability=0.01,
                                          patterns=[], role="NORMAL")},
        {"account_id": "HIGH", **_account(risk_score=95, anomaly_score=90, fraud_probability=0.95)},
    ]
    ranked = agent.rank_accounts(accounts)
    assert [r["account_id"] for r in ranked] == ["HIGH", "LOW"]
    assert ranked[0]["rl_ucb_score"] >= ranked[1]["rl_ucb_score"]


def test_receive_feedback_reward_signs(session) -> None:
    agent = LinUCBAgent(session)
    ctx = agent.build_context(_account())
    tp_result = agent.receive_feedback("ACC1", ctx, is_true_positive=True)
    assert tp_result["reward"] == 1.0

    fp_result = agent.receive_feedback("ACC2", ctx, is_true_positive=False)
    assert fp_result["reward"] == -0.3

    assert agent.tp_count == 1
    assert agent.fp_count == 1
    assert agent.total_feedback == 2


def test_get_stats_learning_status_progression(session) -> None:
    agent = LinUCBAgent(session)
    assert agent.get_stats()["learning_status"].startswith("Bootstrapping")
    ctx = agent.build_context(_account())
    for _ in range(10):
        agent.update(ctx, reward=1.0)
    assert agent.get_stats()["learning_status"].startswith("Learning")


def test_reset_returns_to_identity_and_persists(session) -> None:
    agent = LinUCBAgent(session)
    ctx = agent.build_context(_account())
    agent.update(ctx, reward=1.0)
    agent.reset()
    session.commit()
    assert np.array_equal(agent.A, np.identity(agent.d))
    assert agent.total_feedback == 0

    fresh = LinUCBAgent(session)
    assert np.array_equal(fresh.A, np.identity(fresh.d))


def test_different_arm_ids_are_independent(session) -> None:
    agent_a = LinUCBAgent(session, arm_id="arm-a")
    LinUCBAgent(session, arm_id="arm-b")  # seed arm-b's row too, unused otherwise
    ctx = agent_a.build_context(_account())
    agent_a.update(ctx, reward=1.0)
    session.commit()

    reloaded_b = LinUCBAgent(session, arm_id="arm-b")
    assert np.array_equal(reloaded_b.A, np.identity(reloaded_b.d))
    assert not np.array_equal(agent_a.A, np.identity(agent_a.d))
