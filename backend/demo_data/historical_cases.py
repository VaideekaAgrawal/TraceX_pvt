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
  - `investigation.cases._CLOSING_TRANSITIONS`/`_SETS_CLOSED_AT` (imported
    directly -- module-private by convention, not by enforced boundary; this
    is the same "reuse before rebuild" reasoning as the `CLOSING_REWARD`
    promotion, just for a two-line mapping stable enough not to warrant its
    own public promotion) for the resolution->terminal-status mapping and
    "which resolutions set `closed_at`" semantics, so historical cases are
    internally consistent with what `close_case` would have produced for the
    same resolution.

These are pre-closed, historical rows -- `Case.status` is set directly at
`create()` time (legal: the Phase 4 FSM-bypass fix locked down `update()`,
not initial row creation) rather than walked through `investigation.fsm.
transition_case`'s live NEW->ASSIGNED->...->CLOSED_* transition sequence, but
one `CaseStatusHistory` row is still written per case (via
`CaseStatusHistoryRepository.record_transition`, not status-write-gated --
it's an append-only log, not an enforcement point) for audit/reporting
consistency with every other case in the system.

Backdating judgment call: `CaseRepository.create()`/`update()` do not expose
`created_at` as a settable field anywhere (`CreatedAtMixin`'s Python-side
`default=utcnow` is the only way that column is normally populated,
matching every other table in this schema -- `created_at` is bookkeeping,
not a mutable domain field). A historical training corpus that all shows
`created_at` = "whenever this generator happened to run" would look
obviously synthetic in a demo (every case "created" in the same second).
Narrow, documented exception: after `case_repo.create()` returns the
already-audited row, this module sets `case.created_at` directly on the ORM
object + flushes, bypassing `_update()`'s audit-row append -- deliberately,
because `created_at` isn't a domain-state field the audit invariant's "every
write a human/AI causes" reasoning is protecting (no investigator/AI ever
"changes" a creation timestamp as a real action) and every other field this
module writes (`resolution`/`resolution_reason`/`closed_at`) still goes
through the normal audited `case_repo.update()` call.
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
from detection.rl.bandit import LinUCBAgent
from investigation.cases import _CLOSING_TRANSITIONS, _SETS_CLOSED_AT  # see module docstring
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
        return rng.choices([Priority.P1, Priority.P2], weights=[0.6, 0.4], k=1)[0]
    if resolution is CaseResolution.FALSE_POSITIVE:
        return rng.choices([Priority.P3, Priority.P4], weights=[0.5, 0.5], k=1)[0]
    return rng.choices([Priority.P2, Priority.P3], weights=[0.5, 0.5], k=1)[0]


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
        to_status = _CLOSING_TRANSITIONS[resolution]
        closed_at = (
            created_at + timedelta(days=rng.randint(1, 30))
            if resolution in _SETS_CLOSED_AT
            else None
        )
        risk_score = _risk_score_for(resolution, rng)
        priority = _priority_for(resolution, rng)
        level = rng.choices([CaseLevel.L1, CaseLevel.L2], weights=[0.75, 0.25], k=1)[0]

        case = case_repo.create(
            case_id=case_id,
            primary_account_id=account_id,
            title=f"Demo historical case — {typology.replace('_', ' ').title()}",
            status=to_status,
            level=level,
            priority=priority,
            typology=typology,
            risk_score=risk_score,
            actor_type=actor_type,
            actor_id=actor_id,
        )
        # Documented exception -- see module docstring's "Backdating
        # judgment call".
        case.created_at = created_at
        session.flush()

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

        agent.receive_feedback(account_id, context, is_true_positive=reward > 0)

        cases.append(case)

    return cases
