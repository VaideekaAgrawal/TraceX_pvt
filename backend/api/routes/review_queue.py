"""`/rule-proposals` — admin review queue for new detection rules
(ROADMAP Phase 12, the human-in-the-loop half of the feedback loop).

Any authenticated user may *propose* a detection rule (an investigator who keeps
seeing an unflagged edge case, say); only `ADMIN_COMPLIANCE` may review the
queue and approve or reject. Approving mints an enabled `RuleDefinition` from the
proposal's DSL at the default starting confidence — after which the Phase 12
feedback loop (`detection.rules.feedback`) takes over and moves that confidence
under real verdicts. The proposal row is never deleted, only transitioned, so the
queue doubles as the audit trail of who approved what and why.

A proposal's DSL is structurally validated (`detection.rules.engine.
validate_rule_dsl`) both at submission and again at approval, so a malformed rule
can never be minted into a live `RuleDefinition` that would silently fail every
detection run.
"""
from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from db.enums import ReviewStatus, UserRole
from db.models.base import utcnow
from db.models.platform import User
from db.repositories.detection import RuleDefinitionRepository, RuleProposalRepository
from db.session import get_db
from detection.rules.engine import validate_rule_dsl
from detection.rules.seed import DEFAULT_RULE_CONFIDENCE
from foundation.auth import actor_type_for_role, get_current_user, require_role

router = APIRouter(prefix="/rule-proposals", tags=["review-queue"])


class ProposalModel(BaseModel):
    proposal_id: str
    name: str
    dsl: dict
    tier: int
    rationale: str
    status: str
    proposed_by: str
    reviewed_by: str | None
    review_note: str | None
    created_rule_id: str | None


class ProposeRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    dsl: dict
    tier: int = Field(ge=1, le=2)
    rationale: str = Field(min_length=1, max_length=2000)


class RejectRequest(BaseModel):
    note: str = Field(min_length=1, max_length=2000)


def _to_model(p) -> ProposalModel:
    return ProposalModel(
        proposal_id=p.proposal_id, name=p.name, dsl=p.dsl, tier=p.tier,
        rationale=p.rationale, status=str(p.status), proposed_by=p.proposed_by,
        reviewed_by=p.reviewed_by, review_note=p.review_note,
        created_rule_id=p.created_rule_id,
    )


def _load_pending(proposal_id: str, db: Session):
    repo = RuleProposalRepository(db)
    proposal = repo.get(proposal_id)
    if proposal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "proposal not found")
    if proposal.status != ReviewStatus.PENDING:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"proposal is {proposal.status}, not PENDING — already reviewed",
        )
    return proposal


@router.post("", response_model=ProposalModel, status_code=status.HTTP_201_CREATED)
def propose_rule(
    body: ProposeRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProposalModel:
    """Propose a new detection rule for admin review (any authenticated user)."""
    try:
        validate_rule_dsl(body.dsl)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    proposal = RuleProposalRepository(db).create(
        proposal_id=f"RP-{uuid4().hex[:12].upper()}",
        name=body.name, dsl=body.dsl, tier=body.tier, rationale=body.rationale,
        proposed_by=user.user_id,
        actor_type=actor_type_for_role(user.role), actor_id=user.user_id,
    )
    db.commit()
    return _to_model(proposal)


@router.get("", response_model=list[ProposalModel])
def list_proposals(
    status_filter: ReviewStatus = ReviewStatus.PENDING,
    _: User = Depends(require_role(UserRole.ADMIN_COMPLIANCE)),
    db: Session = Depends(get_db),
) -> list[ProposalModel]:
    """The review queue (compliance only). Defaults to PENDING; pass
    `?status_filter=APPROVED|REJECTED` for the decided history."""
    return [_to_model(p) for p in RuleProposalRepository(db).list_by_status(status_filter)]


@router.post("/{proposal_id}/approve", response_model=ProposalModel)
def approve_proposal(
    proposal_id: str,
    user: User = Depends(require_role(UserRole.ADMIN_COMPLIANCE)),
    db: Session = Depends(get_db),
) -> ProposalModel:
    """Approve a PENDING proposal: mint an enabled `RuleDefinition` from its DSL
    (at the default starting confidence) and mark the proposal APPROVED."""
    proposal = _load_pending(proposal_id, db)
    try:
        validate_rule_dsl(proposal.dsl)
    except ValueError as exc:
        # The DSL was valid at submission; if something made it invalid since,
        # refuse to mint a broken rule rather than approve it.
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    actor_type = actor_type_for_role(user.role)
    rule_id = f"RULE-{uuid4().hex[:12].upper()}"
    RuleDefinitionRepository(db).create(
        rule_id=rule_id, name=proposal.name, dsl=proposal.dsl, tier=proposal.tier,
        confidence=DEFAULT_RULE_CONFIDENCE, enabled=True, created_by=user.user_id,
        actor_type=actor_type, actor_id=user.user_id,
    )
    updated = RuleProposalRepository(db).update(
        proposal_id, status=ReviewStatus.APPROVED, reviewed_by=user.user_id,
        created_rule_id=rule_id, reviewed_at=utcnow(),
        actor_type=actor_type, actor_id=user.user_id,
    )
    db.commit()
    return _to_model(updated)


@router.post("/{proposal_id}/reject", response_model=ProposalModel)
def reject_proposal(
    proposal_id: str,
    body: RejectRequest,
    user: User = Depends(require_role(UserRole.ADMIN_COMPLIANCE)),
    db: Session = Depends(get_db),
) -> ProposalModel:
    """Reject a PENDING proposal with a required note (no rule is minted)."""
    _load_pending(proposal_id, db)
    actor_type = actor_type_for_role(user.role)
    updated = RuleProposalRepository(db).update(
        proposal_id, status=ReviewStatus.REJECTED, reviewed_by=user.user_id,
        review_note=body.note, reviewed_at=utcnow(),
        actor_type=actor_type, actor_id=user.user_id,
    )
    db.commit()
    return _to_model(updated)
