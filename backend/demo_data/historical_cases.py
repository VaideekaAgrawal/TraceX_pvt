"""
Training/reference data (ROADMAP Phase 1B checklist item 1): a historical
corpus of ~`cfg.num_historical_cases` closed `cases` + `case_feature_vector`
+ `detection_feedback` rows, so Similar Historical Cases retrieval (cosine
similarity over the RL 16-dim feature space, `docs/DATA_SCHEMA.md` §3.3
`case_feature_vector`) has real matches to return and the RL bandit's
`rl_arm_state` looks genuinely learned instead of cold-start.

Reuses, does not reinvent (`CLAUDE.md` "reuse before rebuild"):
  - `investigation.rl_features.base_rl_feature_dict` + `detection.rl.bandit.
    LinUCBAgent.build_context` for the 16-dim context vector each case's
    `case_feature_vector.vector` is built from.
  - `investigation.rl_features.CLOSING_REWARD` (promoted this phase from
    `investigation.cases._CLOSING_REWARD`) for the resolution->reward
    mapping.
  - `investigation.cases.CLOSING_TRANSITIONS`/`SETS_CLOSED_AT` (promoted this
    phase from the same module's `_CLOSING_TRANSITIONS`/`_SETS_CLOSED_AT` --
    this generator is a second real caller that needs the identical
    resolution->terminal-status mapping and "which resolutions set
    `closed_at`" semantics `close_case` uses, so historical cases stay
    internally consistent with what a live close would have produced.
    Public, but left in `investigation.cases` rather than relocated to
    `rl_features.py` -- they're FSM-shaped, not RL-shaped, unlike
    `CLOSING_REWARD`) for the resolution->terminal-status mapping.

These are pre-closed, historical rows -- `Case.status` is set directly at
`create()` time (legal: the Phase 4 FSM-bypass fix locked down `update()`,
not initial row creation) rather than walked through `investigation.fsm.
transition_case`'s live NEW->ASSIGNED->...->CLOSED_* transition sequence, but
one `CaseStatusHistory` row is still written per case (via
`CaseStatusHistoryRepository.record_transition`, not status-write-gated --
it's an append-only log, not an enforcement point) for audit/reporting
consistency with every other case in the system.

Backdating: `CaseRepository.create()` now accepts an explicit `created_at`
(added this phase specifically for this caller) so a historical training
corpus doesn't show every case "created" in the same second the generator
happened to run -- backdating goes through the normal, audited `create()`
call, not a caller-side ORM bypass. `case.updated_at` still reflects real
generation time after the subsequent `case_repo.update()` call below
(`UpdatedAtMixin`'s `onupdate=utcnow` has no backdating knob) -- a
pre-existing, broader gap not unique to this generator, accepted as-is (see
the comment at that call site).
"""
from __future__ import annotations

import random
from datetime import timedelta

from db.enums import ActorType, CaseLevel, CaseResolution, Priority
from db.models.base import utcnow
from db.models.investigation import Case
from db.models.reference import Customer
from db.repositories.detection import DetectionFeedbackRepository
from db.repositories.investigation import (
    CaseFeatureVectorRepository,
    CaseRepository,
    CaseStatusHistoryRepository,
)
from demo_data.config import DemoDataConfig
from demo_data.identifiers import demo_account_id_for_customer, demo_case_id
from demo_data.kyc_customers import weighted_choice
from detection.rl.bandit import LinUCBAgent
from investigation.cases import CLOSING_TRANSITIONS, SETS_CLOSED_AT
from investigation.rl_features import CLOSING_REWARD, base_rl_feature_dict

_TYPOLOGIES = ["layering", "round_trip", "structuring", "dormancy", "profile_mismatch"]

_RESOLUTION_REASONS: dict[CaseResolution, str] = {
    CaseResolution.FALSE_POSITIVE: "Demo historical case: reviewed, activity explained by "
    "legitimate business purpose.",
    CaseResolution.TRUE_POSITIVE_SAR: "Demo historical case: confirmed suspicious activity, "
    "SAR filed.",
    CaseResolution.ENHANCED_MONITORING: "Demo historical case: inconclusive, placed under "
    "enhanced monitoring.",
}


def _weighted_resolutions(cfg: DemoDataConfig, rng: random.Random) -> list[CaseResolution]:
    """Exactly `cfg.num_historical_cases` resolutions at (approximately) the
    configured mix. `ENHANCED_MONITORING` absorbs the rounding remainder (so
    the list length always matches the config exactly, unlike naively
    rounding all three independently)."""
    n = cfg.num_historical_cases
    n_fp = round(n * cfg.pct_false_positive)
    n_tp = round(n * cfg.pct_true_positive_sar)
    n_mon = max(n - n_fp - n_tp, 0)
    resolutions = (
        [CaseResolution.FALSE_POSITIVE] * n_fp
        + [CaseResolution.TRUE_POSITIVE_SAR] * n_tp
        + [CaseResolution.ENHANCED_MONITORING] * n_mon
    )
    rng.shuffle(resolutions)
    return resolutions[:n]


def _risk_score_for(resolution: CaseResolution, rng: random.Random) -> float:
    if resolution is CaseResolution.TRUE_POSITIVE_SAR:
        return round(rng.uniform(60.0, 95.0), 2)
    if resolution is CaseResolution.FALSE_POSITIVE:
        return round(rng.uniform(15.0, 55.0), 2)
    return round(rng.uniform(45.0, 80.0), 2)  # ENHANCED_MONITORING


def _priority_for(resolution: CaseResolution, rng: random.Random) -> Priority:
    if resolution is CaseResolution.TRUE_POSITIVE_SAR:
        return weighted_choice(rng, [(Priority.P1, 0.6), (Priority.P2, 0.4)])
    if resolution is CaseResolution.FALSE_POSITIVE:
        return weighted_choice(rng, [(Priority.P3, 0.5), (Priority.P4, 0.5)])
    return weighted_choice(rng, [(Priority.P2, 0.5), (Priority.P3, 0.5)])


def seed_historical_cases(
    session,
    cfg: DemoDataConfig,
    rng: random.Random,
    kyc_pool: list[Customer],
    *,
    actor_type: ActorType,
    actor_id: str | None,
) -> list[Case]:
    """Create (idempotently, get-before-create per case) `cfg.
    num_historical_cases` pre-closed demo cases drawing `primary_account_id`
    from `kyc_pool`'s paired accounts, each with a `case_status_history` row,
    a `case_feature_vector` (16-dim, via the shared RL context builder), a
    `detection_feedback` row, and a genuine `LinUCBAgent.receive_feedback`
    call so the persisted `rl_arm_state` is actually trained by this corpus."""
    if not kyc_pool:
        raise ValueError(
            "seed_historical_cases requires a non-empty kyc_pool -- run "
            "kyc_customers.seed_kyc_customers first"
        )

    case_repo = CaseRepository(session)
    history_repo = CaseStatusHistoryRepository(session)
    feature_repo = CaseFeatureVectorRepository(session)
    feedback_repo = DetectionFeedbackRepository(session)
    agent = LinUCBAgent(session, actor_type=actor_type, actor_id=actor_id)

    resolutions = _weighted_resolutions(cfg, rng)
    now = utcnow()

    cases: list[Case] = []
    for i, resolution in enumerate(resolutions, start=1):
        case_id = demo_case_id(i)
        existing = case_repo.get(case_id)
        if existing is not None:
            cases.append(existing)
            continue

        customer = kyc_pool[(i - 1) % len(kyc_pool)]
        account_id = demo_account_id_for_customer(customer.customer_id)

        typology = rng.choice(_TYPOLOGIES)
        created_at = now - timedelta(days=rng.randint(30, 400))
        to_status = CLOSING_TRANSITIONS[resolution]
        closed_at = (
            created_at + timedelta(days=rng.randint(1, 30))
            if resolution in SETS_CLOSED_AT
            else None
        )
        risk_score = _risk_score_for(resolution, rng)
        priority = _priority_for(resolution, rng)
        level = weighted_choice(rng, [(CaseLevel.L1, 0.75), (CaseLevel.L2, 0.25)])

        case = case_repo.create(
            case_id=case_id,
            primary_account_id=account_id,
            title=f"Demo historical case — {typology.replace('_', ' ').title()}",
            status=to_status,
            level=level,
            priority=priority,
            typology=typology,
            risk_score=risk_score,
            created_at=created_at,
            actor_type=actor_type,
            actor_id=actor_id,
        )

        # `case.updated_at` will still show real generation time after this
        # call (`UpdatedAtMixin`'s `onupdate=utcnow` has no backdating knob,
        # unlike `created_at` which `CaseRepository.create()` now accepts
        # explicitly) -- a pre-existing, broader gap not unique to this
        # generator, and out of scope to fully fix here. Accepted as-is:
        # `updated_at` reflects the real moment this write happened, which
        # is semantically defensible even for backdated historical rows.
        case = case_repo.update(
            case_id,
            actor_type=actor_type,
            actor_id=actor_id,
            resolution=resolution,
            resolution_reason=_RESOLUTION_REASONS[resolution],
            closed_at=closed_at,
        )

        history_repo.record_transition(
            case_id=case_id,
            from_status=None,
            to_status=to_status,
            changed_by=None,
            reason="demo historical case seed",
            changed_at=closed_at or created_at,
            actor_type=actor_type,
            actor_id=actor_id,
        )

        feature_dict = {
            "account_id": account_id,
            **base_rl_feature_dict(risk_score=risk_score, patterns=[typology]),
        }
        context = agent.build_context(feature_dict)

        feature_repo.upsert(
            case_id=case_id,
            vector=context.tolist(),
            typology=typology,
            outcome=resolution,
            computed_at=closed_at or created_at,
            actor_type=actor_type,
            actor_id=actor_id,
        )

        reward = CLOSING_REWARD[resolution]
        feedback_repo.create(
            case_id=case_id,
            verdict=resolution,
            reward=reward,
            created_by=actor_id or "system",
            created_at=closed_at or created_at,
            actor_type=actor_type,
            actor_id=actor_id,
        )

        # `persist=False` -- accumulate every case's feedback into the
        # agent's in-memory A/b across this whole loop and persist once at
        # the end (`agent.flush_state()` below), instead of a full
        # `RlArmStateRepository.upsert()` (flush + audit-chain SELECT)
        # against the single `arm_id="global"` row on every one of the
        # `cfg.num_historical_cases` iterations -- only the final
        # post-loop state is ever consumed.
        agent.receive_feedback(
            account_id, context, is_true_positive=reward > 0, persist=False
        )

        cases.append(case)

    agent.flush_state()
    return cases
