---
name: session-start
description: Run at the very start of any TraceX work session, before doing anything else — including sessions run from a different machine or a different Claude account. Pulls latest git state and orients on where the previous session left off, without re-reading the whole codebase. Use when the user says "start session", "let's continue", "pick up where we left off", or at the start of any config/planning/development session on this repo.
---

Run these steps in order, reporting results concisely as you go:

1. **Sync git state.** Run `git status` and `git pull`. If `git pull` reports conflicts or the working tree wasn't clean before pulling, stop and surface this to the user before doing anything else — do not attempt to resolve it silently.
2. **Read continuity docs, not the codebase.** Read, in this order:
   - `CLAUDE.md` (if not already loaded)
   - `docs/SESSION_LOG.md` — focus on the last 1-3 entries, not the full history
   - `docs/ROADMAP.md` — specifically whatever phase is marked "in progress" or is next after the last "done" phase
3. **Report a short orientation** to the user before starting work: what the last session did, what it left off at, what phase/branch you're now on, and any open blockers from the log. Keep this to a few sentences — it's a status check, not a summary of the whole project.
4. **Check the branch.** If the next task belongs to a roadmap phase with an existing `phase/N-*` branch, check it out (after confirming the working tree is clean). If the phase has no branch yet, create one off latest `main` per the convention in `CLAUDE.md`, and say so.
5. Only after the above, start the actual task the user asked for (or, if they didn't specify one, ask what they want to work on given the "left off" pointer from step 3).

Do not read `SYSTEM_DEVELOPMENT_PLAN.md` or `systemrequirements.txt` in full during this step — pull specific sections later, only once you know which phase/task you're actually working on.
