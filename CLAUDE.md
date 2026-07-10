# TraceX — Project Rules for Claude Code

TraceX is a graph-first, ML-powered, AI-explained AML investigation platform, built for a pilot pitch to Union Bank of India and seed funding at Global Fintech Fest. Backend: FastAPI + pandas/networkx/XGBoost/IsolationForest under `fund-flow-tracker/`. Frontend: Next.js 15/16 + TypeScript under `fund-flow-tracker/frontend/`.

**This repo is mid-refactor.** The owner is dissatisfied with both the backend and frontend as they stand and intends to rebuild most of the system. Treat existing code as a *behavioral reference* (what the system currently does, and why some of it is wrong), not as a design to preserve. Do not assume "it already works this way" means "it should stay this way."

## Session model — read this first

Work on this project happens across many sequential Claude Code sessions, sometimes run from a different machine or a different Claude account. Git is the only thing that reliably carries state between sessions — **nothing persists except what is committed and pushed.** There are three kinds of sessions:

1. **Config session** — sets up/maintains this file, `.claude/agents/`, `.claude/skills/`, and the docs scaffolding below. Not for feature planning or implementation.
2. **Planning session** — produces/updates `docs/ROADMAP.md`: turns the reference spec into an ordered, checkable phase list, and resolves open architectural decisions (see `docs/ROADMAP.md` for the current list). Not for implementation.
3. **Development session(s)** — implements one phase (or part of one) from `docs/ROADMAP.md`, working on that phase's branch.

At the start of **every** session, run `/session-start` (see `.claude/skills/session-start`). At the end of every session that changed anything, run `/session-end`. These read/write `docs/SESSION_LOG.md` so the next session — on this account or another — knows exactly where things stand without re-deriving it from the diff or the whole codebase.

## Source-of-truth documents — read in this order of authority

1. **`SYSTEM_DEVELOPMENT_PLAN.md`** (repo root) — the authoritative spec. It reconciles the raw requirements doc against the actual codebase (feature status table, known gaps, reasoning, open decisions). This is what to read to understand target architecture and *why*.
2. **`docs/ROADMAP.md`** — the phase-by-phase execution plan derived from the above (produced by the planning session). This is what to read to know what to build *next* and in what order.
3. **`systemrequirements.txt`** (repo root) — the original raw requirements doc `SYSTEM_DEVELOPMENT_PLAN.md` was derived from. It's superseded by the plan above — only consult it if you need the unfiltered original feature description; never treat it as an independent spec that could disagree with the plan.
4. **`fund-flow-tracker/claude_session/*.md`** — historical notes from three prior AI-assisted sessions (backend audit/fixes, ML tuning, polish pass, all dated 2026-06-30). Useful for archaeology (why a piece of code looks the way it does, what was already tried and why) but they describe **pre-refactor, feature-patch work** — do not pull tasks from them into the current roadmap without checking against `docs/ROADMAP.md` first; large parts of what they touched may be rebuilt from scratch.
5. **`docs/METRICS.md`** — the running ledger of every quantitative metric this project has produced (dataset sizes, ML model performance, CI/test counts and timings, pipeline run outputs, live-verified behavior numbers). Not read-for-context like the docs above — it's a write target: **any session that produces or changes a metric must add/update its row here before the session ends** (part of `/session-end`, see that skill). Superseded values are struck through and dated, never silently deleted, so a metric regressing is visible instead of erased. This is what stops metric drift like the README-vs-`cross_questions.md` XGBoost figure mismatch (landmine below, now reconciled) from recurring.

Do not re-read all of these in full every session. `docs/SESSION_LOG.md` + the current phase section of `docs/ROADMAP.md` should be enough context to resume work; go back to `SYSTEM_DEVELOPMENT_PLAN.md` only for the specific section relevant to the phase you're on.

## Known architectural landmines (carried forward — do not treat as fixed unless the current roadmap phase says so)

- **No auth wired in.** `infrastructure/security.py` has JWT/RBAC logic that `api/server.py` never imports. RBAC target: **two roles** (Investigator, Admin/Compliance) — decided; do not re-litigate.
- **Hardcoded JWT secret** (`CHANGE_ME_IN_PRODUCTION`) — k8s manifest already expects `secretKeyRef`; app code needs to stop hardcoding it.
- **Two parallel case stores** (`InvestigationService`'s in-memory `CaseManager` vs. a separate SQLite `cases` table) — must unify to one source of truth before extending any case-centric feature.
- **In-memory state lost on restart**: case/alert state, ML model (retrains from scratch each boot), event log, RL bandit state — persistence is a prerequisite for several roadmap items, not a nice-to-have.
- **AI guardrail pattern is feature-specific, not global.** The existing per-account LLM explanation is defensible (facts injected server-side, low temperature, labeled AI-generated, cached) because it can't be manipulated by attacker-controlled input. Any new AI feature that accepts free-text or reads narration/purpose fields (e.g. a future investigation copilot) needs its own explicit guardrail design — the existing pattern does not automatically transfer.
- **CI can't fail** — `.github/workflows/ci.yml` lint/typecheck/build steps use `|| true`.
- **Metric inconsistency** between `README.md` and `docs/cross_questions.md` (XGBoost F1/AUC-ROC figures disagree) — reconcile before either is cited externally.

## Git workflow (multi-session, multi-account)

- Remote: `origin` → `VaideekaAgrawal/TraceX_pvt`, default branch `main`. Already set up — no init needed.
- **Branch per roadmap phase**, not per session: `phase/<n>-<short-slug>` (e.g. `phase/2-case-store-unification`). A development session works on the branch for whatever phase it's continuing; if none exists yet for that phase, create it off latest `main`.
- Commit at meaningful checkpoints within a session, not just at the very end — a session that gets interrupted should not lose work that isn't on disk in git.
- Before opening a PR / merging a phase branch to `main`: run `/code-review` (and `/verify` if the change has a runtime surface) on the full phase diff.
- Merge phase branches via PR, even solo — it's a review checkpoint and keeps `main` always in a demoable state.
- Never force-push `main`. Never skip hooks. Never commit `.env`/credential files.
- Any session — regardless of which machine or Claude account is running it — must `git pull` at the start (handled by `/session-start`) and leave the tree committed/pushed at the end (handled by `/session-end`). Do not leave uncommitted work at the end of a session unless explicitly told to.

## Subagents

Custom project subagents live in `.claude/agents/`:
- **`spec-guardian`** — read-only checker. Run it before merging a phase to confirm the diff doesn't reintroduce a known landmine (above), doesn't contradict `SYSTEM_DEVELOPMENT_PLAN.md`'s design reasoning, and doesn't silently expand scope beyond the current roadmap phase.
- **`tracex-backend`** — implements backend (Python/FastAPI/services) changes for a given roadmap task, with the landmines and guardrail patterns above pre-loaded so it doesn't need to re-derive them.
- **`tracex-frontend`** — implements frontend (Next.js/TypeScript) changes for a given roadmap task, with the current page inventory and the target L1/L2 investigation-workspace UX direction pre-loaded.

Use the built-in `Explore` agent (or a `fork`) for open-ended searches/surveys instead of burning main-session context reading files end to end. Use `Plan` mode for anything where the implementation approach itself needs to be decided before touching code. Don't spawn a custom subagent for something a built-in one already covers well.

## General rules

- Don't fix a "known landmine" opportunistically mid-unrelated-task — if it's not in the current roadmap phase, note it in `docs/SESSION_LOG.md` and move on. Scope creep across a 10+ session refactor compounds fast.
- Prefer correctness and small, reviewable diffs over broad opportunistic rewrites, even though the long-term goal is a large rewrite — get there phase by phase, not in one uncontrolled pass.
- If a roadmap phase's scope turns out to be wrong or too big once you're in the code, stop and flag it in `docs/SESSION_LOG.md` rather than silently improvising a different scope.
