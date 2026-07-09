# Session Log

Running record of every Claude Code session on this repo, in order. This is the primary continuity mechanism across sessions and across Claude accounts — read the most recent entries at the start of a session (via `/session-start`), append one at the end (via `/session-end`).

Numbering starts fresh here (Session 1) with the introduction of this config/session system. Three earlier, informal AI-assisted sessions happened before this system existed — see `fund-flow-tracker/claude_session/*.md` for their notes (backend audit+fixes, ML tuning, polish pass, all 2026-06-30). They are **not** numbered into this log and should not be assumed relevant to the current refactor without checking `docs/ROADMAP.md` first.

Entry template:

```
## Session N — <type: config | planning | development> — YYYY-MM-DD
**Branch:** <branch worked on, or "main">
**Did:** <1-3 sentences, what changed>
**Left off:** <exact next step — what the next session should do first>
**Blockers / open questions:** <anything that needs a human decision, or "none">
**Commits:** <short hashes or "not yet pushed">
```

---

## Session 1 — config — 2026-07-09
**Branch:** main
**Did:** Set up Claude Code project scaffolding for the multi-session refactor: root `CLAUDE.md` (session model, source-of-truth doc order, known architectural landmines, git workflow, subagent roles), `.claude/agents/` (`spec-guardian`, `tracex-backend`, `tracex-frontend`), `.claude/skills/` (`session-start`, `session-end`), and this log. `docs/ROADMAP.md` created as an empty template only — no phases defined yet, by design.
**Left off:** Next session should be a **planning session**: read `SYSTEM_DEVELOPMENT_PLAN.md` in full, resolve the two still-open decisions (AI Investigation Copilot: build now vs. defer to roadmap; graph engine: finish Neo4j adapter vs. keep NetworkX and pitch migration conceptually — RBAC granularity is already decided: two roles, Investigator/Admin-Compliance), and fill in `docs/ROADMAP.md` with an ordered, checkable phase list before any development session starts.
**Blockers / open questions:** The two open decisions above must be resolved before phase ordering can be finalized (Copilot's guardrail work and Neo4j migration effort materially change sequencing).
**Commits:** not yet pushed

## Session 2 — planning — 2026-07-09
**Branch:** main
**Did:** The planning session. Resolved all three open decisions and recorded the pivot to a **greenfield rebuild** (archive old system, port only the trained detection engine + graph/rules/RL, design fresh). Five locked decisions written to `SYSTEM_DEVELOPMENT_PLAN.md` §9 (greenfield; three-layer backend Detection/Investigation/AI-Orchestration; deterministic-guarded tool-using Recommendation Engine; external-LLM gateway with PII redaction; case-scoped ego-graphs) and §8 flipped to RESOLVED. Authored `docs/ROADMAP.md` as a 14-phase plan (0, 1, 1B, 2–12) and `docs/DATA_SCHEMA.md` (23-table system schema + enums + PII redaction map + demo/training data strategy §6). Held all docs to a "Sonnet dev session can execute without re-deriving intent" bar.
**Left off:** **Development can begin.** Next session = **development**: run `/session-start`, create branch `phase/0-archive-scaffold` off `main`, execute ROADMAP **Phase 0** (move existing app to `archive/` with a README; catalog salvage components — ML ensemble, graph algos, rule DSL, RL bandit — with file locations; stand up the `backend/` three-layer skeleton + config + test harness + a real CI). Best run on Sonnet via the `tracex-backend` subagent.
**Blockers / open questions:** None block Phase 0. One deferred planning task: a dedicated Opus deep-dive on the AI-orchestration layer (Phase 8 tool catalog + redaction/tokenization design; Phase 9 rule→typology→regulation catalog) should happen just-in-time **before Phase 8**, not now — it'll be sharper with real tables in place.
**Commits:** 3e8cdf6b, b8dca40a (+ this log entry)

## Session 3 — development — 2026-07-09
**Branch:** phase/0-archive-scaffold
**Did:** Executed ROADMAP Phase 0. Moved the entire pre-refactor app (`fund-flow-tracker/`) into `archive/` via `git mv` (history preserved), with `archive/README.md` and `archive/SALVAGE.md` (exact component → old-path → new-home map for Phase 3). Key finding during the archive pass: **no serialized ML model artifact exists on disk anywhere in the old system** — the ensemble trains from `data/` at pipeline-run time, confirming the "retrains from scratch each boot" landmine at the code level. Corrected the plan accordingly: Phase 3 must train once and persist the artifact, not "load an existing trained artifact" as earlier phrasing implied — noted in `SALVAGE.md` and flagged here for visibility. Lifted `data/` to the repo root (live input, not legacy). Stood up `backend/` as the three-layer skeleton (`detection/`, `investigation/`, `orchestration/` + a platform layer implemented as `backend/foundation/` — renamed from the roadmap's literal `platform/` because that shadows a Python stdlib module; `docs/ROADMAP.md` and `SYSTEM_DEVELOPMENT_PLAN.md` §9.2 updated to match), `pyproject.toml`, `foundation/config.py` (pydantic-settings, no hardcoded secret defaults — `validate_secrets()` fails loudly in non-dev envs instead), and a real CI workflow at `.github/workflows/backend-ci.yml` (ruff + mypy + pytest, none `|| true`). Built a local venv and **actually ran all three CI gates before committing** (per this repo's "verify, don't just claim" norm) — caught and fixed two real issues in the process: an `assert False` ruff violation, and a dependency-scope mistake (Phase 0's `pyproject.toml` pulled in numpy/pandas/xgboost/networkx/scikit-learn, which Phase 0 doesn't use and which caused a genuine local resolution conflict on this machine's Python 3.14 — trimmed to only what Phase 0–2 need; ML/graph deps now explicitly deferred to Phase 3, LLM client to Phase 8). Updated `.gitignore` for the new paths. Marked Phase 0's roadmap checklist `done`.
**Left off:** Phase 0 is committed on `phase/0-archive-scaffold` (commit `9cb20456`) but **not yet pushed, and not yet merged to `main`**. Per `CLAUDE.md` git workflow, the next step before merging is to run `/code-review` on the full phase diff (and `/verify` given it has a runtime surface — though the CI gates were already hand-verified this session), then open a PR. Next session should: confirm with the user whether to push the branch, run the review, and merge — then continue to **Phase 1 (Data model & persistence foundation)** off updated `main`, implementing the schema in `docs/DATA_SCHEMA.md` exactly.
**Blockers / open questions:** None for Phase 0 itself. Carried forward: the Phase 8 AI-orchestration deep-dive is still deferred (see Session 2). New: confirm whether archiving the old frontend wholesale (done, per user's explicit "your lean" confirmation this session) is still fine once frontend work actually starts in parallel — it should be, since it was archived as reference not deleted, but worth a sanity check when that track kicks off.
**Commits:** 9cb20456 (not yet pushed)
