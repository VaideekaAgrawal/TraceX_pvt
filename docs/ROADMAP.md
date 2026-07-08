# TraceX Refactor Roadmap

**Status: template only — not yet filled in.** This file is the output of the **planning session**, not the config session. It exists now so the planning session has a fixed shape to fill in rather than inventing one, and so `CLAUDE.md` / `docs/SESSION_LOG.md` have something concrete to point at. Do not add phase content here during a config session.

## What the planning session should do

1. Read `SYSTEM_DEVELOPMENT_PLAN.md` in full (not just the summary sections).
2. Resolve the open decisions below — get explicit answers from the project owner, don't assume.
3. Turn the plan's feature list + gap analysis + "Key Departures" section into an ordered phase list using the template below. Sequence by the plan's own stated reasoning (fix security/data-integrity gaps and unify the case store before extending case-centric features; sequence net-new features by reuse-of-existing-infrastructure cost before novelty; defer the highest-effort/highest-risk items — Copilot, Relationship Explorer full version — until cheaper reuse-driven items are done).
4. Keep phases small enough to fit one or two development sessions each, given roughly 10-11 sessions total are budgeted for the whole refactor.

## Open decisions (resolve before finalizing phase order)

- [x] **RBAC granularity** — resolved: two roles (Investigator, Admin/Compliance).
- [ ] **AI Investigation Copilot** — build in this refactor, or defer as a roadmap item pitched alongside later RL phases? Changes whether a Copilot phase (with its own prompt-injection guardrail design) appears in this roadmap at all.
- [ ] **Graph engine** — commit to finishing the Neo4j adapter as a real deliverable, or keep NetworkX for the pilot and present Neo4j migration conceptually only? Changes whether a graph-engine-migration phase appears, and how much effort it's budgeted.

## Phase template

Copy this block per phase once planning fills it in:

```
### Phase N — <name>
**Goal:** <one sentence>
**Depends on:** <phase N-1, or "none">
**Branch:** phase/N-<slug>
**Scope (checklist):**
- [ ] <task>
- [ ] <task>
**Explicitly out of scope:** <what a session on this phase should NOT touch, to prevent scope creep>
**Reference:** <section(s) of SYSTEM_DEVELOPMENT_PLAN.md this phase implements>
**Status:** not started | in progress | done
```

## Phases

*(empty — to be filled in by the planning session)*
