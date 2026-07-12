"""
Similar Historical Cases (ROADMAP Phase 7, `SYSTEM_DEVELOPMENT_PLAN.md`
§4.1) -- cosine similarity over the RL 16-dim case feature vector
(`detection.rl.bandit.LinUCBAgent.build_context`), reusing the exact same
context-building pipeline `investigation.cases.close_case` uses to train
the bandit, not a new feature-extraction pipeline (`CLAUDE.md` "reuse
before rebuild").

The corpus this queries is every `case_feature_vector` row with a non-null
`outcome` (`CaseFeatureVectorRepository.list_resolved`) -- written once, by
`close_case`, when a case is actually resolved. The QUERY case's own vector
is never persisted this way, even if it happens to already be closed by the
time someone looks up its similar cases -- it's always recomputed on-the-fly
here (`compute_query_vector`), since a closed query case's persisted row
would otherwise need to be excluded from its own corpus scan anyway (it's
`exclude_case_id`'d out either way), and an open case has no such row to
read in the first place. Recomputing 16 floats of arithmetic on every call
is cheap enough that this isn't a real cost trade-off.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
from sqlalchemy.orm import Session

from db.enums import ActorType, CaseResolution
from db.models.investigation import Case
from db.repositories.investigation import CaseFeatureVectorRepository, CaseRepository
from detection.rl.bandit import LinUCBAgent
from investigation.cases import case_rl_features

#: Clamp bounds for the `top_k` caller/route parameter -- same "documented
#: judgment call, no formula to derive one from" posture as
#: `investigation.graph_filters.MAX_RADIUS`.
_MIN_TOP_K = 1
_MAX_TOP_K = 20


@dataclass
class SimilarCase:
    case_id: str
    similarity: float
    typology: str | None
    outcome: CaseResolution | None
    computed_at: datetime


def compute_query_vector(
    session: Session, case: Case, *, actor_type: ActorType, actor_id: str | None
) -> list[float]:
    """The query case's own 16-dim context vector, built via the same
    `LinUCBAgent.build_context`/`case_rl_features` pipeline `close_case`
    uses to persist a resolved case's vector. Read-only use of the agent
    here: constructing it reuses `build_context` only -- `_load_state()`
    (constructor) reads `rl_arm_state`, but this function never calls
    `update()`/`receive_feedback()`, so nothing is written back."""
    agent = LinUCBAgent(session, actor_type=actor_type, actor_id=actor_id)
    context = agent.build_context(case_rl_features(case))
    return context.tolist()


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Standard cosine similarity; returns 0.0 (not NaN) if either vector
    is all-zero -- guards the div-by-zero a genuinely all-default/no-signal
    context vector would otherwise trigger."""
    va = np.array(a, dtype=float)
    vb = np.array(b, dtype=float)
    norm_a = float(np.linalg.norm(va))
    norm_b = float(np.linalg.norm(vb))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(va, vb) / (norm_a * norm_b))


def find_similar_cases(
    session: Session,
    case_id: str,
    *,
    top_k: int = 5,
    actor_type: ActorType,
    actor_id: str | None,
) -> list[SimilarCase]:
    """Cosine-rank every resolved case in the corpus (`CaseFeatureVector
    Repository.list_resolved`) against `case_id`'s own (freshly computed)
    query vector, return the top `top_k`, most-similar-first.

    No similarity floor in v1 -- returns the corpus's actual top-k
    regardless of how weak the strongest match is (documented judgment
    call: no formula for a "good enough" similarity threshold exists
    anywhere in this codebase or its spec, mirroring Network Risk Score's
    own "no formula existed" posture for its weights).

    Raises `ValueError` if `case_id` doesn't exist (matches this codebase's
    existing convention, e.g. `investigation.fsm.transition_case`)."""
    case = CaseRepository(session).get(case_id)
    if case is None:
        raise ValueError(f"case {case_id!r} does not exist")

    clamped_top_k = max(_MIN_TOP_K, min(top_k, _MAX_TOP_K))
    query_vector = compute_query_vector(session, case, actor_type=actor_type, actor_id=actor_id)

    corpus = CaseFeatureVectorRepository(session).list_resolved(exclude_case_id=case_id)
    scored = [
        SimilarCase(
            case_id=row.case_id,
            similarity=round(_cosine_similarity(query_vector, row.vector), 4),
            typology=row.typology,
            outcome=row.outcome,
            computed_at=row.computed_at,
        )
        for row in corpus
    ]
    return sorted(scored, key=lambda s: s.similarity, reverse=True)[:clamped_top_k]
