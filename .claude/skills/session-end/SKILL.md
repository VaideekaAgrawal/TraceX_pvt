---
name: session-end
description: Run at the end of any TraceX work session that changed anything, before ending the conversation — including when handing off to a different machine or a different Claude account. Commits and pushes work, updates docs/ROADMAP.md checklist state, and appends a session log entry so the next session can resume without re-deriving context. Use when the user says "wrap up", "end session", "let's stop here", or "hand this off".
---

Run these steps in order:

1. **Review the diff.** Run `git status` and `git diff` (staged + unstaged). Summarize what changed in plain terms.
2. **Update `docs/ROADMAP.md`** if the session completed or advanced a checklist item in the current phase — check off finished tasks, update the phase's `Status:` field. Don't mark a phase `done` unless every item in its checklist is actually done.
3. **Update `docs/METRICS.md`** if the session produced or changed any quantitative metric — dataset/ingest counts, ML model performance, CI test counts/coverage/timings, pipeline run outputs, or live-verified behavior numbers from `/verify` or code review. Add a new row, or strike through and date a superseded value (don't delete it). If nothing metric-worthy happened this session, skip this step.
4. **Append an entry to `docs/SESSION_LOG.md`** using the template at the top of that file: session number (increment from the last entry), type (config/planning/development), branch, what was done, exactly what the next session should do first ("Left off"), any open blockers or decisions still needed, and the commit hash(es) once committed.
5. **Stage, commit, and — only after explicit confirmation from the user — push.** Follow the git safety protocol in the system prompt and `CLAUDE.md`: never force-push, never skip hooks, create a new commit rather than amending, and confirm before pushing since this may hand off to someone else's session. If the user hasn't been asked yet this session whether to push, ask before doing it.
6. **Do not leave uncommitted work** at the end of the session unless the user explicitly says to — the next session (possibly on a different account) only sees what's in git.
7. Give a final one-paragraph summary: what shipped, what's left in the current phase, and what the very next action should be.
