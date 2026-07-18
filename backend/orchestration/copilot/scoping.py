"""Copilot case-scoping — ROADMAP Phase 10.

The Copilot is cross-case, so — unlike Phase 9's engine, which binds one case at
construction — its RBAC boundary is *the set of cases this user may touch*. Every
case-specific tool validates its `case_id` argument against this set, so the model
cannot roam outside the user's own work no matter what case id it names.

The scoping mirrors `GET /cases` (Phase 15, decision 8), reusing
`CaseRepository.list_filtered` rather than a second query shape:

  - **INVESTIGATOR** → cases assigned to them (`assigned_to == user_id`).
  - **ADMIN_COMPLIANCE** → the maker-checker review queue: cases in
    `AWAITING_REVIEW` or `ESCALATED` (their actionable set, not "assigned to me").

This is a personal-workspace boundary by design: an admin's Copilot helps with
what is waiting on their review, not with the entire bank's case load.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from db.enums import CaseStatus, UserRole
from db.models.platform import User
from db.repositories.investigation import CaseRepository

# An admin/compliance reviewer's Copilot is scoped to what is waiting on them.
_ADMIN_QUEUE_STATUSES = [CaseStatus.AWAITING_REVIEW, CaseStatus.ESCALATED]


def accessible_case_ids(session: Session, user: User) -> set[str]:
    """The case ids this user's Copilot may read/act on. Empty set = no cases
    (a brand-new investigator with nothing assigned) — the engine declines to
    call the model in that case, there being nothing to work on."""
    repo = CaseRepository(session)
    if user.role == UserRole.ADMIN_COMPLIANCE:
        cases = repo.list_filtered(statuses=_ADMIN_QUEUE_STATUSES)
    else:
        cases = repo.list_filtered(assigned_to=user.user_id)
    return {c.case_id for c in cases}
