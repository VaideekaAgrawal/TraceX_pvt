# TraceX Backend (Greenfield)

The rebuilt backend, per `docs/ROADMAP.md` and `SYSTEM_DEVELOPMENT_PLAN.md` §9. See those docs — and `docs/DATA_SCHEMA.md` for the data model — before writing code here; this README is just "how to run it," not "what to build."

## Layout

```
backend/
  foundation/     # "Platform" layer: auth+RBAC, config, secrets, DB session,
                  # LLM gateway, guardrails. Named foundation/ not platform/ —
                  # `platform` is a Python stdlib module name.
  detection/      # Detection & Intelligence layer (ported from archive/, see
                  # archive/SALVAGE.md): ML ensemble, graph engine, rule DSL, RL bandit.
  investigation/  # Investigation layer: case store, L1/L2 FSM, evidence, audit,
                  # watchlist, reporting/STR, case-scoped graph access.
  orchestration/  # AI Orchestration layer: shared AI substrate, Recommendation
                  # Engine, Copilot. Built last (ROADMAP Phase 8-10).
  api/            # Thin FastAPI routers over the three layers above.
  db/             # Schema, migrations, repositories.
  tests/
```

## Setup

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Running checks (same gates CI runs)

```bash
ruff check .                                                          # lint
mypy foundation detection investigation orchestration api db tests    # typecheck
pytest --cov=. --cov-report=term-missing                              # tests
```

`mypy` is invoked with explicit package names, not `.` — a bare `.` walks whatever venv exists in the working directory and type-checks installed third-party stubs as if they were our own source (hit and debugged during Phase 0). Keep this list in sync with `[tool.mypy] files` in `pyproject.toml` and the `Typecheck` step in `.github/workflows/backend-ci.yml` if a new top-level package is added.

None of these are allowed to be non-blocking (`|| true`) — see `archive/fund-flow-tracker/.github/workflows/ci.yml` for what that looked like and why it was replaced (`.github/workflows/backend-ci.yml` at the repo root is the new one).

## Dependency scope note

`pyproject.toml` intentionally does **not** include the ML/graph stack (numpy, pandas, networkx, scikit-learn, xgboost) yet — those land in Phase 3 when the detection engine is actually ported, not before. Pulling them in during Phase 0 caused a real (if environment-specific) dependency-resolution conflict with no offsetting benefit; keeping each phase's dependencies scoped to what it actually uses avoids that class of problem generally. Same logic applies to the LLM client — added in Phase 8.

## Config

All settings are read from the environment (`backend/foundation/config.py`, `Settings`). Copy `.env.example` (added when the first phase needs real secrets) to `.env` for local dev — never commit `.env`. In any non-`dev` environment, `Settings.validate_secrets()` fails startup loudly if required secrets are missing, rather than falling back to an insecure default — this replaces the old system's hardcoded `JWT_SECRET = "CHANGE_ME_IN_PRODUCTION"` landmine (see `CLAUDE.md`).
