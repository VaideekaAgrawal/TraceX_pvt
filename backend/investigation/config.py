"""
SLA policy for the case lifecycle (ROADMAP Phase 4).

SLA durations are genuinely unspecified anywhere in the docs -- confirmed via
grep across `systemrequirements.txt` and `SYSTEM_DEVELOPMENT_PLAN.md` (only
"SLA Timer Starts" appears, as a workflow-stage label, with no actual
duration attached to it). The values below are therefore an
invented-but-reasonable default pending a real product decision, not a
hidden assumption -- called out explicitly here (and in
`docs/SESSION_LOG.md`) rather than silently baked into `assignment.py`.

Scope is tracking only (ROADMAP Phase 4 plan): `sla_due_at` is computed once,
at assignment time, from the case's `priority`; `list_overdue_cases()`
(`investigation/assignment.py`) makes overdue cases queryable. There is no
automatic status-transition/escalation on breach -- that would be an
autonomous trigger with no explicit spec backing, out of this phase's scope.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from db.enums import Priority


@dataclass(frozen=True)
class SlaPolicy:
    """Per-`Priority` SLA duration. P1 (most urgent) gets the shortest
    window; P4 the longest."""

    durations: dict[Priority, timedelta] = field(
        default_factory=lambda: {
            Priority.P1: timedelta(hours=4),
            Priority.P2: timedelta(hours=24),
            Priority.P3: timedelta(hours=72),
            Priority.P4: timedelta(days=7),
        }
    )

    def duration_for(self, priority: Priority) -> timedelta:
        return self.durations[priority]


DEFAULT_SLA_POLICY = SlaPolicy()
