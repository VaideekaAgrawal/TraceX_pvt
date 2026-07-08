# Salvage Catalog — What Ports From the Archive, and Where It Lands

Concrete component → old path → new home map for the greenfield rebuild. This is the input list for **ROADMAP Phase 3 (Detection & Intelligence layer port)**. Everything not listed here is either superseded by the new investigation/AI-orchestration layers (`docs/ROADMAP.md` Phases 1–2, 4–12) or left behind entirely (see "Not salvaged" below).

All old paths are relative to `archive/fund-flow-tracker/`.

## Detection & Intelligence layer (→ `backend/detection/`)

| Component | Old path | Salvage note | New home (target) |
|---|---|---|---|
| ML ensemble (IsolationForest + XGBoost) | `services/detection/ensemble.py` | **Port the training/scoring logic, not a saved artifact — none exists.** XGBoost is trained on real labelled data at pipeline-run time (`gpu_hist` if CUDA available), not loaded from a serialized file. See "Important note on the trained model" below. | `backend/detection/scoring/ensemble.py` behind a `Scorer` interface |
| 5 pattern detectors | `services/detection/{layering,round_trip,structuring,dormancy,profile}.py`, `fan_out.py` | Port logic as-is; these are the individually-good detectors referenced throughout the system plan. | `backend/detection/detectors/` |
| Feature engineering | `services/detection/features.py` | Port; also the source of the 16-dim feature vector reused by Similar Cases / Path Rec. | `backend/detection/features.py` |
| Rule Engine DSL (11 primitives, Tier-2 composition) | `services/detection/rule_engine.py` | Port as-is — a genuinely strong, already-well-documented piece (see its own docstring). Feeds `rule_definitions` table. | `backend/detection/rules/engine.py` |
| Per-account AI explanation (fact-injected, low-temp, cached) | `services/detection/explainability.py` | Port the **pattern** (facts injected server-side, not generated; low temperature; labeled AI-generated; cached) into the new AI substrate (Phase 8) as the template both new agents follow. | `backend/orchestration/` (Phase 8), referenced not copied verbatim |
| Graph engine (NetworkX MultiDiGraph, centrality, cycles, ego-graph) | `services/graph/engine.py`, `services/graph/service.py` | Port behind the new `GraphStore` interface. `infrastructure/database.py::get_ego_graph(account_id, radius)` already proves the ego-graph primitive works — reuse that shape, rebuild the case-scoping around it (decision 5). | `backend/detection/graph/` (NetworkX impl of `GraphStore`) |
| LinUCB contextual bandit | `services/rl/bandit.py` | Port the algorithm; **add persistence** — old version's `A`/`b` matrices are not durably saved across restarts, this was an explicit landmine (`rl_arm_state` table exists specifically to fix it). | `backend/detection/rl/bandit.py` + `rl_arm_state` persistence |

### Important note on the trained model
There is **no serialized model artifact on disk** (`.pkl`/`.joblib`) anywhere in the archive — confirmed by direct inspection during Phase 0. "The trained detection engine" refers to the **training/scoring code and calibrated weights/thresholds in `ensemble.py`**, which retrains XGBoost from `data/` on each pipeline run today. This matches the known landmine "ML model retrains from scratch each boot" in `CLAUDE.md`.

**Correction to earlier planning language:** Phase 3 should **train once against the (now-root) `data/` set and persist the resulting artifact** (`model_runs.artifact_path`) — not "load an existing trained artifact," since none exists. The detector *logic* (feature engineering, ensemble weighting, the 5 pattern detectors) is what's being kept unchanged; only the packaging (persist vs. retrain-on-boot) changes.

## Investigation layer — reference only, not ported as-is (→ `backend/investigation/`, rebuilt per `docs/DATA_SCHEMA.md`)

| Old component | Old path | Disposition |
|---|---|---|
| In-memory `CaseManager` | `services/investigation/case_manager.py` | **Not ported.** One of the two case stores being unified away — read for behavior reference only (what fields/transitions it modeled), rebuilt against the `cases`/`case_status_history` schema. |
| SQLite `cases` table + `InvestigationService` | `services/investigation/service.py`, `infrastructure/database.py` (cases methods) | **Not ported as-is.** Same reason — the second of the two parallel stores. `infrastructure/database.py`'s DB-adapter *interface shape* (abstract methods) is a reasonable reference for the new repository layer's method surface. |
| Evidence handling | `services/investigation/evidence.py` | Reference only — the new `evidence` table (Phase 1) and Phase 6 build fresh against it. |
| JWT/RBAC (fully implemented, never wired in) | `infrastructure/security.py` | **The logic itself is salvageable** — port it, but this time actually import it into the API routes (Phase 2). This was flagged as the single most damaging finding in the system plan (§2): "the code sits right there, unused." |
| Ingestion / CSV parsing | `services/ingestion/*.py`, `scripts/download_data.py`, `scripts/seed_demo_data.py`, `scripts/ingest_eod.py` | Reference for parsing logic (CSV → `Transaction`/`Account` shape); rebuild against the new schema with upload validation (size/MIME/row-count) added, feeding `ingestion_log`. |
| Canonical data models | `services/common/models.py` | Reference only — enums (`Channel`, `RiskLevel`, `Priority`, `AccountRole`, `DetectionType`) are reused by name in `docs/DATA_SCHEMA.md` §2; dataclasses are superseded by the DB schema + ORM models. **`CaseStatus` is explicitly NOT reused** — replaced by the new FSM enum. |

## Not salvaged (left fully behind)

- **Old frontend** (`frontend/`) — archived whole; the new frontend is built later, parallel to backend, organized by investigation stage (L1/L2) rather than data type per §5 of the system plan. Not a code-reuse source, though its page inventory is documented in `CLAUDE.md`'s `tracex-frontend` subagent notes for UX reference.
- **`services/monitoring/`, `services/realtime/`, `services/pipeline/`, `services/validation/`** — not yet catalogued for salvage; revisit if a later phase (e.g. real-time alert generation in Phase 4) needs them. Not blocking Phase 0.
- **Old CI** (`.github/workflows/ci.yml`, if present under the archived tree) — superseded by the new backend CI (Phase 0), which does not use `|| true`.
- **k8s manifests** (`k8s/`) — not salvaged into the new backend now, but **not discarded either**: they already describe a credible target production shape (3-replica, HPA, PodDisruptionBudget, non-root containers, Neo4j env vars, JWT secret via `secretKeyRef`) per system plan §2. Revisit at Phase 12 (production hardening).

## How to use this catalog

A Phase 3 development session should treat each row above as a checklist item: read the old file at the given path for logic/behavior, then write the new implementation at the target path against the current `docs/DATA_SCHEMA.md` schema and the layer interfaces defined in `backend/` — not a copy-paste port.
