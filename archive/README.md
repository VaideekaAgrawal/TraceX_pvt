# Archive — Pre-Refactor TraceX

This is the **frozen, pre-greenfield-rebuild** version of TraceX. It was moved here whole (via `git mv`, history preserved) at the start of the backend greenfield rebuild — see `SYSTEM_DEVELOPMENT_PLAN.md` §9 and `docs/ROADMAP.md` Phase 0 for the decision and reasoning.

## What this is

The original hackathon/pilot build: a FastAPI backend (`api/`, `services/`, `infrastructure/`) with a genuinely strong detection/ML/graph core, plus a Next.js frontend (`frontend/`), wired together as a set of analytics pages rather than a case-centric investigation product.

## Why it was archived, not extended

Per `SYSTEM_DEVELOPMENT_PLAN.md` §2 and §9: the detection/ML/graph/rule-engine core is good and worth keeping, but the system around it had architectural landmines too deep to refactor incrementally in the time budgeted — no auth wired into any route despite JWT/RBAC code existing unused, two parallel case stores with no single source of truth, in-memory state lost on every restart (including the ML model, which retrained from scratch each boot), a partial/implicit audit trail, and AI guardrails that were feature-specific rather than a reusable layer. The owner's call: archive this cleanly, lift only the components worth keeping, and design the investigation platform and AI orchestration layer fresh. See `SALVAGE.md` for exactly what is being ported and where it lands.

## What NOT to assume

Do not treat anything in here as "how it should stay." Per `CLAUDE.md`: this is a **behavioral reference** — what the system currently does, and why some of it is wrong — not a design to preserve. If new backend code differs from what's here, that's very likely intentional, not a regression.

## Still-useful docs preserved in place

`archive/fund-flow-tracker/claude_session/*.md`, `README.md`, `CHANGES_PRODUCTION_UPGRADE.md`-equivalent notes, and `k8s/` manifests remain here for archaeology and because the k8s manifests already describe a target production shape (§2 of the system plan) worth consulting again once the new backend nears deployment.

## What was NOT archived

`data/` (the source CSVs — `HI-Small_accounts.csv`, `HI-Small_Patterns.txt`, `tracex_test_day1.csv`, and the source zip) was lifted to the repo root (`/data`) instead of archived, because it is live input to the new system (ingestion, Phase 1B demo/training data), not legacy code.
