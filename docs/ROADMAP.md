# TraceX Backend Refactor Roadmap

**Status: filled in by Planning Session (2026-07-09).** This is the phase-by-phase execution plan that development sessions work from, derived from `SYSTEM_DEVELOPMENT_PLAN.md` and the five committed decisions below. It supersedes the empty template. Frontend runs in parallel on its own track later; this roadmap is **backend**. **The frontend track now has its own roadmap: `docs/FRONTEND_ROADMAP.md` (Phases 13+, continuing this file's numbering).**

**Budget:** ~21–24 sessions over 7–8 days (~3 combined sessions/day), backend-weighted, frontend parallel later. Phases are sized to 1–2 sessions each.

---

## Committed decisions (this session — do not re-litigate)

1. **Greenfield rebuild.** The existing system is archived (properly stored + documented), not extended. We lift the components worth keeping — ML ensemble, graph algorithms, rule-engine DSL, RL/LinUCB bandit — and design fresh in clean layers. Everything else (case store, auth, API surface, state handling, guardrails) is built new.
2. **Three-layer backend** (+ a thin platform layer):
   - **Detection & Intelligence** — ported engine (ML, graph, rules, RL) behind clean interfaces.
   - **Investigation** — case lifecycle, unified durable case store, L1/L2 state machine, assignment/SLA, evidence, audit trail, watchlist, reporting/STR, case-scoped graph service.
   - **AI Orchestration** — shared AI substrate + Recommendation Engine + Copilot. Built **last**, on top of the other two.
   - **Platform** — auth/RBAC, DB/persistence, config, LLM gateway, guardrail middleware.
3. **Recommendation Engine = deterministic-guarded, tool-using reasoner.** An always-on deterministic rule set (defines valid next steps + typology/regulation anchors) + tools that *compute* exact facts (graph metrics, fund-flow %, txn aggregates, prior-SAR/shared-entity lookups) + an LLM that reasons over the full case evidence & graph but is bounded by the rules and grounded in tool-computed facts. Never a bare LLM call. Every recommendation logged with its driving facts (auditable). Cross-questioning re-invokes rules + tools.
4. **LLM posture: external API now, gateway-abstracted + secured.** OpenRouter today, behind an **LLM gateway with PII redaction/tokenization** (names, account numbers, PAN pseudonymized before egress, re-hydrated on return). A self-hosted model can drop in via the same gateway if the bank later mandates on-prem-only.
5. **Case-scoped ego-graphs — never the global graph.** Every graph is the investigated account + its N-hop connected neighborhood (optionally time-windowed). L1 = simplified 1-hop money-flow read; L2 = expand hops 1/2/3/N, always anchored on case accounts. This is simultaneously the security boundary (no cross-case leakage), the LLM-context bound (accuracy), the scale strategy (bounded subgraph regardless of total size → NetworkX suffices for pilot), and the usability fix. **Graph engine:** NetworkX now behind a `GraphStore` adapter; Neo4j is the funded-production swap, pitched via the migration path.

---

## Committed decisions — AI substrate (planning session, 2026-07-13 — do not re-litigate)

These lock Phase 8's previously-open questions and **refine decision 4 above**. They are grounded in the project's actual data (verified this session — see *Data reality* below), not in the abstract.

6. **LLM gateway = the `openai` SDK against a configurable `base_url`; OpenRouter today.** Not the Anthropic SDK, not raw `httpx`. Rationale: the OpenAI chat-completions schema *is* the portable provider interface — OpenRouter, vLLM, TGI and Ollama all speak it — so a bank-mandated on-prem swap becomes a `base_url` change, not a rewrite. Deliberately **no further provider-abstraction layer** on top: it would buy nothing the SDK does not already give, and a lowest-common-denominator wrapper would forfeit tool-calling and structured outputs, which the whole substrate depends on. Model for the pitch: a best-quality proprietary model via OpenRouter (verify `tools` is in `supported_parameters` via `GET /api/v1/models` before committing the default string — do not assume). `orchestration/llm_client.py`'s raw-`httpx` POST is **replaced**, not wrapped.
7. **Caching = response-level only.** The existing `find_cached_interaction` most-recent-wins lookup over `ai_interactions` is the entire caching story. Provider-native *prompt* caching is deliberately **not** designed for: it is vendor-specific and would forfeit exactly the portability decision 6 exists to buy. Do not reintroduce it.
8. **Grounding is an enforced gate, not a prompt instruction.** Tools return structured fact dicts that accumulate into a per-interaction **fact bundle**; the model returns structured output in which every claim carries the fact key it came from; a **deterministic post-generation validator rejects any claim whose citation does not resolve to a fact in the bundle** (and, in Phase 9, any action not in the deterministic catalog). *The model cannot assert a number it was not handed.* `ai_interactions.facts` / `tools_called` / `rule_anchors` — schema-ready since Phase 1 and null ever since — become always-populated.
9. **PII posture = zero egress, enforced by assertion, fail-closed.** This **refines decision 4**: not pseudonymize-and-re-hydrate. Tools are *shaped* so PII is never in the return value (`customer_id`, `risk_rating`, `pep_status`, `kyc_status`, `income_bracket` — never `name`/`pan`/`aadhaar`/`phone`), and a gate over every prompt-bound fact bundle **raises** on a PII value rather than silently stripping it. *"It never left our perimeter"* is a provable claim to a bank; *"we de-identified it"* is a materially weaker one. Tokenize/re-hydrate is **designed** in Phase 8 but **built in Phase 10**, where the Copilot genuinely needs an investigator to see a name.
10. **Attacker-controllable free text stays out of every prompt.** `transactions.narration` / `purpose` are **0-populated in the real dataset** (verified) — so the exclusion costs zero features, and the Phase 5 regression test enforcing it stays green at no cost. The only *live* free-text surface is `notes.body` (investigator-written); its guardrail is a **Phase 10** problem, not Phase 8's.
11. **Demo data is a first-class pitch asset, kept strictly separable.** The `DEMO-`-prefixed Phase 1B seed (KYC/PAN/phone/device/relationships + 7 golden scenarios) is what makes the Relationship Explorer, the L1 KYC surfaces, and Phase 9's recommendations demonstrable **at all** — without it the only discoverable relationships are `income_bracket`/`branch` noise at confidence 0.25–0.35 (Session 11 verified: 3,713 + 1,620 of them). Pitch framing is two-tier and **stated aloud**: *detection engine trained and validated at full scale on IBM's public AML benchmark; investigation features demonstrated on engineered scenarios with planted ground truth.* Never imply real bank data.

### Data reality (verified 2026-07-13 — stop re-deriving this)

Queried directly against `data/tracex.db`:

| | |
|---|---|
| Customers | 166,207 — IBM HI-Small synthetic entities (`Corporation #33520`, `Sole Proprietorship #50438`) |
| `customers.pan` / `aadhaar` / `phone` populated | **0** |
| Transactions | 8,002 |
| `transactions.narration` / `purpose` populated | **0** |

**There is no real customer PII in this project.** The three sources are IBM AML HI-Small (a public synthetic benchmark), a hand-built India-adapted mock (`data/tracex_test_day1.csv` — accounts literally named `PMFRAUD01`), and the `DEMO-` Phase 1B seed. The 🔒PII columns registered in `db/pii.py` are aspirational except where the demo seed fills them.

**Consequence:** PII egress during the pitch build is a **design and narrative** concern, not a legal one. Build the zero-egress path because it is what production requires and what the pitch claims — not because a data subject is at risk today. This also means Phase 8 can be built and experimented against freely without redaction being a blocker on its own construction.

---

## Target architecture (greenfield skeleton)

```
backend/
  foundation/     # the "Platform" layer: auth+RBAC, config, secrets, DB session,
                  # LLM gateway, guardrails. Named `foundation/` not `platform/` in
                  # code — `platform` is a Python stdlib module name; the layer is
                  # still called "Platform layer" in all docs/prose.
  detection/      # PORTED: ML ensemble, graph algos, rule-engine DSL, RL bandit
  investigation/  # NEW: case store, alert->case, L1/L2 FSM, evidence, audit,
                  #      watchlist, reporting/STR, case-scoped GraphStore/ego-graph
  orchestration/  # NEW: AI substrate (tool layer + audit), rec engine, copilot
  api/            # thin FastAPI routers over the three layers; auth on every route
  db/             # schema, migrations, repositories
  tests/
archive/          # the previous system, frozen + documented
```

**Invariants that hold across all phases:**
- Durable state only — nothing critical lives in memory across restart (cases, alerts, model, bandit state, audit log all persist).
- Auth on every route from the moment the API exists — no "add auth later" phase.
- The LLM never decides or invents facts; it phrases/discusses server-computed facts (guardrail invariant, applies to both agents).
- Every investigator action and every AI action is written to one queryable audit log.
- All graph work goes through the case-scoped `GraphStore` interface — no direct global-graph access.

---

## Phase list

Legend: **Status** = not started | in progress | done.

### Phase 0 — Archive & greenfield scaffold
**Goal:** Freeze the old system and stand up the empty three-layer skeleton with tooling.
**Depends on:** none
**Branch:** phase/0-archive-scaffold
**Scope (checklist):**
- [x] Move the existing app into `archive/` with a short `archive/README.md` (what it was, what we're keeping, why we left it).
- [x] Catalog the components to port (ML ensemble, graph algos, rule DSL, RL bandit) with their file locations — a "salvage list" the later port phases consume. See `archive/SALVAGE.md`; also corrects earlier planning language — no serialized model artifact exists, Phase 3 trains once and persists rather than "loading an existing" one.
- [x] Create the `backend/` package skeleton (layers above), dependency management, settings/config module, test harness, and a CI skeleton (real, not `|| true`). Platform layer implemented as `backend/foundation/` (not `platform/`, a stdlib name). All three CI gates (ruff, mypy, pytest) verified passing locally before commit.
- [x] Decide and document the DB engine for pilot (SQLite single-node) vs. the prod path (Postgres) behind a repository interface. Documented in `docs/DATA_SCHEMA.md` §0; reflected in `backend/foundation/config.py` default (`sqlite:///./data/tracex.db`). Repository layer itself is built in Phase 1.
**Explicitly out of scope:** porting any real logic; DB schema tables (Phase 1); auth (Phase 2).
**Reference:** §1, §7 (greenfield decision), §5 (CI/CD).
**Status:** done

### Phase 1 — Data model & persistence foundation
**Goal:** The durable backbone every other phase writes to. **Detailed schema design is the immediate next planning activity the owner will drive before this phase is built.**
**Depends on:** Phase 0
**Branch:** phase/1-data-foundation
**Scope (checklist):**
- [x] Implement the system-level schema (customers, accounts, transactions, alerts, cases, evidence, notes, users/roles, audit_log, watchlist, model_runs, rl_state) — per the dedicated schema-design doc. All 20 enums + 21 tables from `docs/DATA_SCHEMA.md` §2-3 as SQLAlchemy 2.0 models under `backend/db/models/`; `backend/db/pii.py` records the 🔒PII column allow-map for Phase 8.
- [x] Migrations + repository layer (one source of truth; no direct-SQLite-vs-in-memory split ever again). Alembic wired in `backend/alembic/` (initial migration verified up/down against real SQLite); `backend/db/repositories/` has one repo class per table, each enforcing the `audit_log` SHA-256 hash-chain write-through internally (`docs/DATA_SCHEMA.md` §0 audit invariant) — callers never write audit rows themselves.
- [x] Seed/ingest path for the synthetic dataset with upload validation (size/MIME/row-count). `backend/db/ingest.py` parses `data/HI-Small_accounts.csv` + `data/tracex_test_day1.csv` into customers/accounts/transactions, idempotent via `ingestion_log` (file-hash + per-row deterministic `txn_id`), validates extension/size/columns/row-count before touching the DB. Run against the real files: 166,207 customers, 518,889 accounts, 8,002 transactions, audit chain verified over 693,102 rows.
- [x] Persistence for model artifacts and RL bandit state (no retrain/reset on boot). `model_runs`/`rl_arm_state` tables + `ModelRunRepository`/`RlArmStateRepository` give a durable path; the actual training/bandit algorithms port in Phase 3.
**Explicitly out of scope:** business logic over the tables (later phases); UI.
**Reference:** §2 (two-case-store finding), §5 (scalability, upload validation).
**Status:** done

### Phase 1B — Demo & Training Data Studio
**Goal:** A reproducible generator producing the data that makes every feature demo flawlessly and makes the reuse-driven features actually work — kept strictly separate from the real ingest path.
**Depends on:** Phase 1 (schema exists)
**Branch:** phase/1b-demo-data
**Scope (checklist):**
- [x] **Training/reference data:** seed a corpus of historical `cases` + `case_feature_vector` + `resolution` (so Similar Cases retrieval returns real matches), and seed `detection_feedback` events (so the RL queue looks learned, not cold-start). Done: `backend/demo_data/historical_cases.py` — 50 pre-closed cases (~50/35/15 FP/TP_SAR/MONITORING mix), each with a real 16-dim `case_feature_vector` (via `LinUCBAgent.build_context`) and a `detection_feedback` row; `LinUCBAgent.receive_feedback` genuinely trains the persisted `rl_arm_state` (single persist after the loop, not per-case).
- [x] **KYC/customer mock:** populate `pep_status`, `sanction_status`, `kyc_status`, occupation-vs-income mismatch on demo customers. Done: `backend/demo_data/kyc_customers.py` — 200 demo customers+accounts (~4% PEP, ~2% sanctioned, full `KycStatus` spread, ~15% occupation/income mismatch).
- [x] **Relationship networks:** generate accounts with **no direct transaction link** but shared `pan`/`phone`/`employer`/`address` (+ `income_bracket`/`branch_city` as extra demo variety beyond the locked list) → drives the Relationship Explorer "hidden mule network" reveal. **Deviation from decision 4:** ships without `device`/`nominee` — no such columns exist anywhere in `Customer`/`Account` (confirmed via full-repo grep); adding them was explicitly considered and declined by the user this session in favor of shipping without, consistent with Phase 7's own already-planned v1 scope (name/branch/income/PAN only). Done: `backend/demo_data/relationships.py` — 8 clusters of 2-4 customers, zero transactions between cluster members; does not write to the `relationships` table itself (that's Phase 7's discovery job).
- [x] **Golden edge-case scenarios:** one curated network per typology (clean layering, structuring-across-branches, circular/round-trip, dormancy reactivation, profile mismatch, sanction match, funnel mule), each with a **known-correct investigation path** and a written feature-explanation, so the Recommendation Engine + Copilot demo deterministically. Done: `backend/demo_data/golden_scenarios.py` + `docs/GOLDEN_SCENARIOS.md` — all 7 scenarios use *real* fabricated transactions verified live to trigger their intended `DetectionType` through the actual rule engine + alert pipeline (not just labels).
- [x] Tag all demo data (reserved `DEMO-` account-id prefix, isolated via `ingestion_log`); make generation seeded/reproducible; document each scenario → feature(s) showcased → expected output → edge case proved. Done: `backend/demo_data/identifiers.py` (deterministic `DEMO-`-prefixed ids), 4 `ingestion_log` marker rows (one per sub-generator) gating idempotent re-runs, `backend/scripts/generate_demo_data.py` CLI, fixed RNG seed per generator.
**Explicitly out of scope:** retraining the core detection engine (kept as-is, Phase 3); real bank data.
**Reference:** `docs/DATA_SCHEMA.md` §6; §4.1/§4.2 (Similar Cases, Relationship Explorer).
**Status:** done

### Phase 2 — Auth, RBAC & security baseline
**Goal:** Two roles wired into every route from the start; secrets done right.
**Depends on:** Phase 1
**Branch:** phase/2-auth-rbac
**Scope (checklist):**
- [x] JWT auth + two roles (Investigator; Admin/Compliance) enforced as route dependencies — Investigators triage/escalate, Admin/Compliance closes cases, approves SAR, edits rules.
- [x] JWT secret + all secrets from env/secret store (no hardcoded default anywhere).
- [x] Data-scoping middleware: an investigator only reaches their own assigned cases (the enforcement point the Copilot later relies on).
**Explicitly out of scope:** a third L1/L2 role (decided against — two roles); SSO/enterprise IdP (roadmap, not pilot).
**Reference:** §5 (RBAC, Security), landmines in `CLAUDE.md`.
**Status:** done

### Phase 3 — Detection & Intelligence layer (port)
**Goal:** Bring the good engine over, cleanly interfaced and persistent.
**Depends on:** Phase 1
**Branch:** phase/3-detection-port
**Scope (checklist):**
- [x] Port ML ensemble (IsolationForest + XGBoost) behind a `Scorer` interface. **Correction (found during Phase 0, see `archive/SALVAGE.md`): no serialized model artifact exists anywhere in the archive — the old system retrained XGBoost from `data/` at every pipeline run, which is the exact "retrains from scratch each boot" landmine this rebuild exists to fix. Do not go looking for an existing artifact to load. Instead: port the detector/feature-engineering/ensemble-weighting *logic* unchanged from `archive/fund-flow-tracker/services/detection/ensemble.py` (reusing the tuned hyperparameters/weights documented in `archive/fund-flow-tracker/infrastructure/config.py` — do not re-derive them from defaults), train once against the root-level `data/` set, and persist the resulting artifact to `model_runs`/`artifact_path` so it is never retrained on boot again.** Persist version + metrics per run; reconcile the README vs. cross_questions metric discrepancy. Done: `backend/detection/scoring/{ensemble,training}.py` (`AnomalyDetector`/`FraudClassifier`/`RoleClassifier`/`EnsembleScorer` + `train_and_persist()` promote-on-success orchestration), `backend/scripts/train_detection_model.py` (provisioning CLI). `docs/cross_questions.md`'s stale ~72%/~0.88 figures corrected to the archive's documented PR-AUC=0.64, Precision=0.778, Recall=0.609, F1=0.683, CV AUC=0.933 (README already matched these); `docs/DATA_SCHEMA.md` §6(a)'s stale "already trained, port the serialized artifacts" language corrected to match.
- [x] Port graph algorithms behind the `GraphStore` interface; implement **case-scoped ego-graph extraction** (N-hop, time-windowable) as the only way graphs are built. Done: `backend/detection/graph/{store,networkx_store}.py`.
- [x] Port rule-engine DSL (11 primitives, Tier-2 composition) + dry-run. Done: `backend/detection/rules/engine.py`.
- [x] Port RL/LinUCB bandit with persistent state. Done: `backend/detection/rl/bandit.py` (DB-backed via `RlArmStateRepository`, single `arm_id="global"`).
**Explicitly out of scope:** new detectors/typologies; Neo4j (adapter interface only, NetworkX impl); wiring alerts→cases (Phase 4).
**Reference:** §1 (three pillars), §5 (graph engine, ML governance).
**Status:** done

### Phase 4 — Alert generation, case lifecycle & audit trail
**Goal:** The spine: detection output becomes prioritized alerts → single case store → assignment/SLA → L1/L2 state machine, with everything audited.
**Depends on:** Phases 2, 3
**Branch:** phase/4-case-lifecycle
**Scope (checklist):**
- [x] Alert generation from detection results (id, type, risk, confidence, timestamp). `investigation/alerts.py::generate_alerts_from_detection` (+ ported `make_deterministic_alert_id`), fed by `detection/rules/seed.py`'s idempotent built-in-rule seed (a small addition beyond the literal Phase 4 plan file list — needed so `RuleEngine.run_all` has something to alert on against a fresh DB; see `docs/SESSION_LOG.md`).
- [x] AI Prioritization Queue wired as its own stage (reuse ported RL bandit). `investigation/prioritization.py::rank_alert_queue` — 200-alert candidate cap (mirrors the archive), groups same-account alerts to feed `LinUCBAgent.build_context` real multi-alert pattern signal.
- [x] Case creation + workload-based auto-assignment + SLA timer + status machine (New→Assigned→In Progress→Awaiting Review→Escalated/Closed). `investigation/fsm.py` (FSM + `transition_case`), `investigation/assignment.py` (`auto_assign`, plain open-case-count workload per `DATA_SCHEMA.md`, `list_overdue_cases`), `investigation/cases.py` (`create_case_from_alert`, `close_case` incl. RL feedback tie-in, no rule-confidence adjustment — that's Phase 12), `investigation/config.py` (`SlaPolicy`, invented-but-documented defaults).
- [x] Unified, queryable **audit trail** subsystem — every investigator + system action (alert opened, graph expanded, evidence pinned, note added, decision changed, escalation). `AlertRepository.mark_opened` (audit-only, no domain-field change), `EvidenceRepository.pin` (`evidence_pinned`), `CaseRepository.update`'s new `action` override (`case_assigned`/`escalated`/`decision_changed`/...), `NoteRepository.create` already logged `note_created` (left as-is). **`graph_expanded` is NOT instrumented** — no case-scoped graph-view persistence entity exists yet (Phase 3's `GraphStore` is in-memory/session-scoped) and no endpoint calls it; that lands with Phase 6's L2 graph work.
**Verification:** `scripts/run_detection_pipeline.py` — CLI end-to-end orchestrator (stages 1→4: score → rules → alerts → ranked queue → auto-case-create/assign), mirroring `scripts/train_detection_model.py`'s precedent. Run live against real ingested data on a throwaway DB (`docs/SESSION_LOG.md` has the actual output).
**Explicitly out of scope:** L1/L2 feature panels (Phases 5–6); AI actions (that audit hook lands in Phase 8); HTTP/API routes (Phase 5+); automatic SLA-breach escalation (tracking only, no autonomous trigger — no spec backing); rule-engine confidence adjustment on feedback (Phase 12).
**Reference:** §3 (lifecycle), §5 (case management, audit trail).
**Status:** done

### Phase 5 — L1 triage feature set
**Goal:** Everything an investigator needs for a 15–30 min triage on one case.
**Depends on:** Phase 4
**Branch:** phase/5-l1-triage
**Scope (checklist):**
- [x] Data-assembly endpoints: alert summary, customer snapshot, geo risk, transaction summary, transaction purpose/consistency, previous-alert summary. `api/routes/cases.py` (`GET /cases/{case_id}/summary/alerts`, `/accounts/{account_id}/{customer-snapshot,geo-risk,transaction-summary,transaction-purpose,previous-alerts}`); `investigation/account_facts.py::transaction_stats` (shared with the AI explanation panel), `investigation/previous_alerts.py::summarize` (deliberately scoped to `primary_account_id` only — network-wide reach is Phase 6/7). No invented "purpose consistency" heuristic — data assembly only, per spec (no formula exists anywhere to port).
- [x] Simplified money-flow ego-graph (1-hop source→customer→beneficiaries read). `investigation/case_graph.py` (`build_case_graph_store` — case-scoped `NetworkXGraphStore`, dedup by `txn_id`; `shape_money_flow` — aggregated, grouped-by-counterparty sources/beneficiaries over `NetworkXGraphStore.get_ego_graph(radius=1)`). `GET /cases/{case_id}/accounts/{account_id}/money-flow`.
- [x] **Network Risk Score** — package existing centrality/cycle/SAR-adjacent signals into one explained number. `investigation/network_risk.py::compute_network_risk` — reuses `RoleClassifier.classify_all` (mule count), `NetworkXGraphStore.detect_cycles`/`.compute_centrality` (all ported unchanged, Phase 3) + the same prior-SAR lookup pattern as `previous_alerts.py`; weighted, capped sub-scores clamped to 100 (documented judgment-call weights, no formula existed to port). `HIGH_PAGERANK_THRESHOLD`/`HIGH_BETWEENNESS_THRESHOLD` promoted to named constants in `detection/scoring/ensemble.py` (2nd real caller). `GET /cases/{case_id}/network-risk` (lazy-fill + persist once), `POST /network-risk/recompute`. Deliberately omits "density"/"money concentration" (spec prose only, no formula anywhere) — documented deferred refinement.
- [x] Port + label the existing fact-injected AI account explanation (guardrail pattern intact). `orchestration/account_explanation.py` — explicit Phase-5 stopgap (module docstring), NOT the Phase 8 substrate: direct `httpx` OpenRouter call ported near-verbatim from the archive, facts assembled server-side only, `Transaction.narration`/`purpose` deliberately excluded (regression-tested). Cache reuses the existing `ai_interactions` table (`AiInteractionRepository.list_for_case_and_agent`, new) — no new table, no in-memory dict, durable across restart. `GET /cases/{case_id}/accounts/{account_id}/explanation?force=`.
- [x] L1 decision endpoint: Close-as-FP | Request-info | Escalate, with notes + reason → audit + feedback hooks. `POST /cases/{case_id}/decision` — `escalate`/`request_info` open to any case-scoped Investigator (`transition_case` to `ESCALATED`/`AWAITING_REVIEW`); `close_fp` FSM-legal from three statuses but RBAC-gated to `ADMIN_COMPLIANCE` only (checked per-decision-value in the route body, not a blanket role dependency, so escalate/request_info stay open to Investigators on the same route) — `investigation.cases.close_case` gets `DetectionFeedback`+RL feedback for free; escalate/request_info intentionally do not (no reward mapping for a non-closing transition). `InvalidTransitionError` → 409. Optional `note` recorded via `NoteRepository` after a successful transition.
**Explicitly out of scope:** conversational AI (Phase 10); N-hop graph (Phase 6); narrative report (Phase 11); Similar Historical Cases (Phase 7); Investigation Path Recommendation (Phase 9).
**Verification:** implemented, then a high-effort `/code-review` (8 finder angles + 1-vote verify) found and fixed 10 confirmed issues — most notably the Network Risk Score's centrality signal originally used absolute thresholds tuned for the full transaction graph, saturating "high centrality" for nearly every case (fixed to percentile-relative thresholds within the case's own graph), and AI-explanation failures were being cached and served back as if genuine (fixed with a typed exception separating failure from success) — see `docs/SESSION_LOG.md` for the full list. Post-fix: all three CI gates (ruff/mypy/pytest) plus a live end-to-end run against the real ingested dataset (166,207 customers / 518,573 accounts / 8,002 transactions) on a throwaway DB copy: trained the ensemble, ran the full detection pipeline, provisioned real users, then drove every new route over `TestClient` against real pipeline-generated cases — 27 checks including Network Risk Scores now showing real variance (32.0–44.0 across sampled cases, not pinned near the cap), the AI-explanation cache-corruption fix confirmed live (repeated failed calls stay `cached=False`, zero `AiInteraction` rows persisted for failures), the account-scope 404, RBAC 403s, and the full decision flow (Investigator escalate → 200, escalate-from-`ESCALATED` → 409, Investigator close_fp → 403, Admin close_fp → 200 with a real `DetectionFeedback` row) — see `docs/SESSION_LOG.md` for details. Merged via PR #7.
**Reference:** §4.1.
**Status:** done

### Phase 6 — L2 deep investigation
**Goal:** Analyst-grade tools on the case-scoped graph.
**Depends on:** Phase 5
**Branch:** phase/6-l2-deep
**Scope (checklist):**
- [x] N-hop graph exploration (expand/collapse) with the full filter set (suspicious-only, risk/amount threshold, time window, channel/direction, source/mule/sink role, prior-SAR) — all over the ego-graph. `investigation/graph_filters.py` (`GraphFilters`, `apply_filters`, `annotate_nodes`, `build_subgraph_store`, `get_filtered_ego_graph`) applies every filter over `NetworkXGraphStore.get_ego_graph`'s previously-unfiltered output; role/risk/prior-SAR are computed fresh per ego-subgraph (a second, radius-scoped role computation distinct from `network_risk.py`'s case-wide one). "International" filter explicitly deferred (no country/jurisdiction field anywhere in the schema — documented, not faked). `GET /cases/{case_id}/accounts/{account_id}/graph` also closes the Phase 4 `graph_expanded` audit-hook deferral (`CaseRepository.mark_graph_expanded`).
- [x] Complete customer profile + complete/searchable transaction analysis + historical behaviour analysis. `investigation/customer_profile.py` (beneficial owner/linked cards-loans-deposits/risk-score trend explicitly omitted — no backing schema, surfaced via `omitted_fields`); `investigation/transaction_search.py` + `TransactionRepository.search_for_accounts`/`count_for_accounts` (hard security invariant: account scope is always `CaseAccountRepository.list_account_ids_for_case`-derived, never caller-supplied — no server-side CSV export, flagged not built); `investigation/behavior_analysis.py` (5 of 7 spec items — monthly spending, cash deposit trend, transfer trend, dormancy/reactivation, velocity increase; salary mismatch/seasonal trends deferred, no backing data/formula, surfaced via `"deferred"` in the response). Routes: `GET .../profile`, `GET /cases/{case_id}/transactions/search`, `GET .../accounts/{account_id}/transactions/search`, `GET .../accounts/{account_id}/behavior`.
- [x] Timeline reconstruction + timeline↔graph sync data contract (bidirectional highlight; UI consumes later). `investigation/timeline.py::build_timeline` — every event's `txn_id` is the same key the graph response's edges carry, so a frontend correlates purely by that shared key (no join table). `GET /cases/{case_id}/accounts/{account_id}/timeline`.
- [x] Pattern explanation (typology + evidence + confidence) reusing the fact-injection pattern. `orchestration/pattern_explanation.py` — facts sourced only from the already-persisted `Alert` row (never a live re-run of detection); cache keyed on a deterministic `pattern_signature` (sha256 of detection_type + sorted account_ids) sharing the `ai_interactions`/`AiAgent.RECOMMENDATION` namespace with `account_explanation`; first real writer of `AiInteraction.rule_anchors`; identical failure/non-caching contract to `explain_account` (regression-tested). `orchestration/llm_client.py` extracted from `account_explanation.py` (2nd real caller, zero behavior change) to back both. `GET /cases/{case_id}/alerts/{alert_id}/pattern-explanation?force=`.
- [x] Evidence management (bookmark txns/accounts, pin evidence, notes, snapshots). `api/routes/l2.py` only — zero new repository/persistence methods (`EvidenceRepository`/`NoteRepository` already covered everything). `POST/GET /cases/{case_id}/evidence`, `PATCH .../evidence/{evidence_id}/pin`, `POST/GET /cases/{case_id}/notes`. "Collaborate" = the existing `added_by`/`author_id` + timestamp audit trail; document attachment = `file_path` metadata only (no upload/storage infra exists anywhere in this codebase — flagged, not built).
**Explicitly out of scope:** graph replay animation (frontend, later); Copilot (Phase 10); Relationship Explorer full version (Phase 7 stub only).
**Verification:** implemented, then a high-effort `/code-review` (8 finder angles + verify pass) found and fixed 10 confirmed issues — most notably the N-hop graph response silently dropping the center account when it had zero transactions (fixed by synthesizing a minimal center node), a pattern-explanation cache key collision that could serve one alert's stale explanation under a different alert's identity (fixed by keying the cache on `alert_id`), and a self-loop transaction being unconditionally excluded by either `direction` filter (fixed) — see `docs/SESSION_LOG.md` for the full list. Post-fix, a live end-to-end run against the real ingested dataset (166,207 customers / 518,573 accounts / 8,002 transactions) on a throwaway DB copy surfaced one more real bug the unit tests hadn't caught: `GET .../graph` 500'd on real transactions with a blank `from_bank`/`to_bank` (pandas represents the missing value as `float('nan')`, which failed `GraphEdge`'s `str | None` Pydantic validation) — fixed at the API-shaping boundary with a regression test, then re-verified. Final state: all three CI gates green (379 tests, 97% coverage), and a live pass driving every new route via `TestClient` against real pipeline-generated cases confirming all 5 correctness fixes hold (center-node synthesis, self-loop direction, pattern-explanation cache correctness, defense-in-depth scope checks, the NaN fix) plus the full route surface (graph/profile/transaction-search/behavior/timeline/pattern-explanation/evidence/notes) — see `docs/SESSION_LOG.md` for details. Merged via PR (link once opened).
**Reference:** §4.2.
**Status:** done

### Phase 7 — Reuse-driven intelligence: Similar Cases, Path Rec groundwork, Relationship Explorer v1
**Goal:** The cheap-because-reused net-new features, before the expensive AI agents.
**Depends on:** Phase 6
**Branch:** phase/7-reuse-intelligence
**Scope (checklist):**
- [x] Similar Historical Cases — cosine similarity over the RL 16-dim feature vector; return outcome + typology. Implemented, see `investigation/cases.py` (`case_rl_features` promoted public — second real caller — and `close_case` now upserts a `CaseFeatureVector` for every real closed case, reusing the exact context already fed to the bandit, closing the "only 50 demo cases have a vector" corpus gap), `db/repositories/investigation.py::CaseFeatureVectorRepository.list_resolved`, `investigation/similar_cases.py` (`compute_query_vector` — on-the-fly, never persisted for an open case; `find_similar_cases` — no similarity floor, top-k clamped 1-20), `GET /cases/{case_id}/similar-cases?top_k=` (`api/routes/cases.py`).
- [x] Relationship Explorer v1 — the cheap shared-attribute version (fuzzy name + branch + income; device/IP only if data exists), as a case-scoped relationship graph. Implemented, see `investigation/relationship_discovery.py::discover_relationships` (PAN 0.95 / fuzzy-name ratio / income-bracket 0.35 / branch-city 0.25 confidence scheme; `CustomerRepository.list_relationship_candidate_pool` gates the candidate pool on `pan IS NOT NULL OR income_bracket IS NOT NULL` — the real-data scale fix, ~200 demo customers vs. 166,207 real ones with no KYC fields at all; `MAX_CANDIDATE_POOL_SIZE=5000` safety valve raises rather than silently truncating), `RelationshipRepository.find_existing`/`list_for_entities`, `investigation/relationship_graph.py::build_case_relationship_graph` (case customers + 1-hop, read-only), `GET /cases/{case_id}/relationships` (`api/routes/l2.py`, closing Phase 6's stub). Global batch job, not lazy-fill-per-case (module docstring has the reasoning) — invoked via `scripts/discover_relationships.py` (CLI) and `demo_data/seed.py`'s 5th marker-gated stage (no HTTP-triggered discovery this phase; a future admin route is flagged, not built).
- [x] Path-recommendation **data plumbing** only: expose the computed signals (fund-flow %, shared device count, prior-SAR adjacency) as structured facts the Phase 9 engine will consume as tools. Implemented, see `investigation/case_graph.py::add_flow_percentages` (pure helper alongside `shape_money_flow`) and `investigation/path_facts.py::compute_path_recommendation_facts` — fund-flow % (radius=1 around `primary_account_id`), shared-attribute adjacency (this phase's own `build_case_relationship_graph` output, unchanged), prior-SAR adjacency (Phase 6's `graph_filters.get_filtered_ego_graph`/`annotate_nodes`) assembled from one `get_filtered_ego_graph` call rather than re-deriving the ego-graph pipeline. No HTTP route — plain dataclasses only, Phase 8's tool layer doesn't exist yet to consume this.
**Explicitly out of scope:** the reasoning/LLM layer of path recommendation (Phase 9); watchlist (Phase 11).
**Verification:** implemented, then a high-effort `/code-review` (8 finder angles + verify pass) found 12 candidates; 8 confirmed fixes applied — most notably `CaseFeatureVectorRepository.list_resolved` missing an `ORDER BY` under its `LIMIT` (made Similar Cases' ranking non-deterministic once the corpus exceeds the cap — fixed), `relationship_graph.build_case_relationship_graph` silently returning an empty graph for an unknown `case_id` instead of raising like its two sibling Phase 7 modules (fixed), entity_a/entity_b canonical ordering enforced only by caller convention rather than centrally in `RelationshipRepository` (centralized into `create()`/`find_existing()`), and an N+1 query loop in `relationship_discovery._branch_cities` (fixed via a new batched `AccountRepository.list_by_customer_ids`) — see `docs/SESSION_LOG.md` for the full list, including 2 findings deliberately deferred as documented known limitations (stale relationship rows aren't invalidated when the underlying shared value changes; `value_hash` is an unsalted hash of low-entropy PII, both needing a real design decision rather than a solo same-session fix). Post-fix: all three CI gates green (410 tests). Live `/verify` against the real ingested dataset (166,207 customers / 518,573 accounts / 8,002 transactions) plus the demo data studio (200 KYC customers, 8 relationship clusters, 50 historical cases) on a throwaway DB: trained the ensemble, ran the full detection pipeline, provisioned real users, then drove the new surface — `GET .../similar-cases` showed real similarity variance on an open case and, after closing two real cases via the actual decision endpoint, both correctly appeared in a third case's corpus at similarity 1.0 (confirming `close_case`'s new `CaseFeatureVector` upsert and corpus growth); the candidate pool for relationship discovery correctly gated to 213 real customers (not 166K); `GET .../money-flow` now surfaces `pct_of_total`, summing to 100% per direction on real transaction data; `build_case_relationship_graph` correctly revealed 35 hidden out-of-case customers linked via a discovered `name` relationship; `compute_path_recommendation_facts` held (no crash/div-by-zero) across both zero-transaction demo cases and 51-edge real pipeline cases, with fund-flow percentages summing to exactly 100% per bucket, and correctly raised `ValueError` for an unknown case_id.
**Reference:** §4.1 (Similar Cases, Path Rec), §4.2 (Relationship Explorer), §7 #5.
**Status:** done

### Phase 8 — AI substrate (shared foundation for both agents)
**Goal:** Build once what both the Recommendation Engine and Copilot stand on — and make *grounded, auditable, no-PII-egress* a property **enforced in code**, not promised in a prompt.
**Depends on:** Phase 4 (audit), Phase 7 (structured facts) — both merged.
**Branch:** phase/8-ai-substrate
**Decisions:** 6–11 above are locked. Read them before starting; do not re-open them.
**Scope (checklist):**
- [ ] **LLM gateway** (`orchestration/gateway.py`) — `openai` SDK against `settings.llm_base_url` (OpenRouter). SDK-native retry (`max_retries`) and timeout; typed exceptions (`RateLimitError` / `APIStatusError` / `APIConnectionError`) mapped onto the existing `ExplanationUnavailableError` contract, so the Phase 5 landmine (*a failed call persisted as a cached success, then served back as `cached: True` forever*) stays fixed. **Replaces** `orchestration/llm_client.py`'s raw-`httpx` POST; `account_explanation` / `pattern_explanation` migrate onto it with behavior unchanged.
- [ ] **Settings + secrets** — add `llm_base_url`; extend `Settings.validate_secrets()` to require the LLM API key **and** a new `pii_hmac_key` in staging/prod (`foundation/config.py`'s own docstring already defers exactly this to Phase 8). Verify the default model string against OpenRouter's `GET /api/v1/models` for `tools` in `supported_parameters` before committing it — a model that silently lacks function-calling kills the whole substrate.
- [ ] **Tool layer** (`orchestration/tools/`) — a **fixed** catalog. Each tool wraps an **already-built** Phase 5–7 function (no new computation), carries a strict JSON schema (`strict: true`, `additionalProperties: false`), and returns a structured fact dict — **never prose**. `case_id` is **bound at construction, never a model-supplied argument** — the model cannot choose which case it looks at. Account-id arguments go through the existing `require_case_scoped_account`, so an out-of-case request returns a tool **error**, not data: case-scoping enforced in code, not in the prompt. Catalog (all twelve already exist): case summary · account facts · money flow (with `pct_of_total`) · filtered ego-graph · network risk · similar cases · relationships · path-recommendation facts · timeline · behavior analysis · transaction search · previous alerts.
- [ ] **Grounding contract** (`orchestration/grounding.py`) — the **centrepiece of this phase, not a sub-task**. Defines the per-interaction fact bundle; the structured-output schema in which every model claim carries the fact key it came from; and the **deterministic validator** that rejects any claim whose citation does not resolve. See decision 8.
- [ ] **PII egress gate** (`orchestration/redaction.py`) — a fail-closed assertion over every prompt-bound fact bundle, checked against `db/pii.py::PII_COLUMNS`. **Raises** on a PII value; never silently strips (a silent strip cannot be proven; a raise can). Populates `ai_interactions.redacted`. Belt *and* braces: the tools are separately shaped so PII isn't in the return value to begin with. Note `Relationship.value_hash` already delivers this for free — the AI sees `shared_attribute: "pan", confidence: 0.95, 3 entities` and **never the PAN**.
- [ ] **`_value_hash` → HMAC-SHA256** keyed on `pii_hmac_key` — resolves Session 11's deferred item (an unsalted SHA256 of a low-entropy identifier like a PAN is brute-forceable if the DB ever leaks). Relationship rows are *derived*, so this is a regenerate via `scripts/discover_relationships.py`, **not** a migration.
- [ ] **Demo identifier safety** (`demo_data/kyc_customers.py`) — `_synthetic_pan` currently emits the **exact real PAN format** (5 letters + 4 digits + 1 letter), and PAN carries **no checksum**, so a generated value can collide with a real person's; `_synthetic_phone` likewise emits a real Indian mobile format. Make both deliberately format-**invalid** (keep the string length so the UI still reads right — the Relationship Explorer matches on *equality*, so format is functionally irrelevant). Aadhaar (`1`-prefixed → structurally impossible, real Aadhaar never starts 0 or 1) and email (`.invalid`, an IANA-reserved TLD) are **already safe** — leave them alone. Shipping valid-format PANs from an AML compliance product is indefensible in the room we are pitching to.
- [ ] **AI-action audit** — `facts` / `tools_called` / `rule_anchors` always-populated **by the gateway**, not per-caller. The `audit_log` hash chain already fires automatically through `BaseRepository._create` (`action="ai_interaction_created"`) — this is **not** a new mechanism, it is filling three columns that have been sitting null since Phase 1.
**Explicitly out of scope:** the agents themselves (Phases 9–10); provider-native prompt caching (decision 7); the pseudonymize/re-hydrate *implementation* (designed here, built in Phase 10); the `notes.body` free-text guardrail (Phase 10).
**Deferred, deliberately:** stale `relationships` rows are never invalidated when the underlying shared value changes (Session 11). Not on the demo path — PAN exists only in the demo seed, which is regenerated wholesale — and fixing it properly means deciding whether to break the repository's append-only design. Logged, not fixed.
**Reference:** §5 (AI Guardrails); decisions 3 & 4, as refined by decisions 6–11.
**Status:** not started

### Phase 9 — Recommendation Engine (deterministic-guarded reasoner)
**Goal:** The intelligent "what next" agent that reasons over full evidence + graph, defensibly. **The rules define the action space; the LLM only ranks and explains within it — it can never invent an action, and (per decision 8) it can never assert a number it was not handed.**
**Depends on:** Phase 8 (gateway, tool layer, grounding contract, PII gate)
**Branch:** phase/9-recommendation-engine
**Scope (checklist):**
- [ ] **Deterministic action catalog + rule set** — the valid next steps, each mapped to a typology **and** a regulatory anchor (FATF recommendation / RBI expectation). This catalog *is* the action space; nothing outside it can be recommended.
- [ ] **Rule grounding** — a rule firing emits a **structured evidence record**, not a verdict string: rule id, the threshold tested, the **observed value**, the exact accounts/transactions that triggered it, the typology, the regulation. This is what populates `rule_anchors`, and it is what makes a recommendation reconstructable by a regulator *without trusting the model at all*.
- [ ] **Ranking policy** — deterministic / evidence-weighted first, structured so the RL feature vector can drive it later.
- [ ] **Reasoning + explanation** over the case ego-graph and evidence, bounded by the rules and grounded in Phase 8's tool-computed fact bundle.
- [ ] **Structured output + validation gate** — recommendations returned as JSON: `action_id` (**must** exist in the catalog), rationale, `cited_facts` (**must** resolve in the fact bundle), `rule_anchor`, confidence. Anything failing either check is **rejected before it reaches the investigator** — the guardrail is a code path, not a prompt.
- [ ] **Cross-question dialogue** — investigator challenges a recommendation; the engine re-invokes rules + tools and defends with cited facts, appended to the same audited `ai_interactions` thread.
**Explicitly out of scope:** the personal/cross-case Copilot (Phase 10); workflow-pattern learning (roadmap, `docs/RL_USP.md`).
**Reference:** §4.1 (Path Rec), decisions 3 & 8, §5 (guardrails).
**Status:** not started

### Phase 10 — Investigation Copilot (personal workspace agent)
**Goal:** The "does stuff for me" assistant — cross-case, investigator-personal.
**Depends on:** Phases 8, 9
**Branch:** phase/10-copilot
**Scope (checklist):**
- [ ] Fixed tool catalog: find/filter *my* cases; "what changed since last login" digest (over the audit log); read/write case-specific notes; grounded Q&A over the current case ego-graph.
- [ ] Hard RBAC scoping to the investigator's own cases (Phase 2 enforcement).
- [ ] Guardrails from Phase 8 applied end-to-end; clearly-AI-labeled, facts independently viewable.
- [ ] **PII pseudonymize / re-hydrate — inherited from Phase 8 (decision 9), built here.** This is the one place the zero-egress invariant legitimately has to bend: an investigator asking *"what else is Rajesh connected to?"* needs a name back. Deterministic per-request token map (`CUST_A1` ↔ `customer_id`), held in-request, re-hydrated on return, **never persisted**. Phase 8 designs it; Phase 10 is the first caller that actually needs it.
- [ ] **`notes.body` free-text guardrail — inherited from Phase 8 (decision 10), built here.** `notes.body` is the project's only *live* attacker-influenced free-text surface (`narration`/`purpose` are 0-populated). The Copilot both reads and writes notes, so it needs its own explicit guardrail design — per `CLAUDE.md`, the existing per-account-explanation pattern **does not automatically transfer** to a feature that ingests free text.
**Explicitly out of scope:** actions that mutate case decisions (Copilot assists; decisions stay with the investigator/Admin roles).
**Reference:** §4.2 (Copilot), §5 (guardrails), decision 3.
**Status:** not started

### Phase 11 — Reporting, narrative & watchlist
**Goal:** Close the case with a defensible artifact; persistent risky-entity monitoring.
**Depends on:** Phase 6 (evidence), Phase 8 (AI substrate)
**Branch:** phase/11-reporting-watchlist
**Scope (checklist):**
- [ ] Case-level auto-narrative (executive summary, findings, evidence, txns of interest, network analysis, notes, recommendation) — extend the fact-injection pattern to multi-account, editable before submit.
- [ ] STR/SAR generation (port + extend the FIU-IND PDF+JSON+SHA-256 flow) fed by the narrative + evidence.
- [ ] Watchlist management (`WatchlistScreener` from `IMPROVEMENTS_STRATEGY.md`) — mark entities; future alerts touching them auto-escalate priority.
**Explicitly out of scope:** regulatory e-filing integration (roadmap).
**Reference:** §4.2 (narrative), §4.3, §4.2 (watchlist).
**Status:** not started

### Phase 12 — Feedback loop, continuous learning & production hardening
**Goal:** Close the lifecycle loop and make the maturity claims true.
**Depends on:** all prior
**Branch:** phase/12-feedback-hardening
**Scope (checklist):**
- [ ] Wire investigator verdicts → RL reward + rule-engine confidence + Admin review queue for new rules/edge cases (the full §3 loop).
- [ ] Model governance surfacing (version/lineage/metrics via `/api/model-metrics`).
- [ ] CI/CD tightened (drop `|| true`, coverage gate, image build/push per k8s manifest); data-retention policy documented.
- [ ] Deployment wiring toward the existing k8s manifest (secrets, non-root, health/HPA).
**Explicitly out of scope:** Neo4j migration build (funded-prod, conceptual for now); workflow-pattern RL beyond reward wiring.
**Reference:** §3 (feedback), §5 (ML governance, CI/CD, scalability), §6 (deployment).
**Status:** not started

---

## Sequencing rationale (why this order)

- **Foundation before features:** persistence (1) → auth (2) → engine port (3) → lifecycle spine (4), so no feature is ever built on in-memory or unauthenticated ground (the two worst landmines from the old system).
- **Reuse before novelty:** the RL feature vector powers Network Risk, Similar Cases, and Path Rec — those land (5, 7) before the expensive AI agents.
- **AI substrate once, agents after:** gateway + redaction + tools + guardrails + AI-audit (8) is shared, so the Recommendation Engine (9) and Copilot (10) don't each reinvent guardrails — directly satisfies "each new AI feature needs its own guardrail design" by making it a layer.
- **Case-scoped graph is a Phase 3 primitive,** so every later graph feature (5, 6, 7, 9, 10) inherits the security/scale/usability boundary for free.

## Open items deferred to roadmap (not this refactor)
- Neo4j production migration (build); Graph Replay animation (frontend); workflow-pattern continuous learning (`docs/RL_USP.md` later phases); enterprise SSO; regulatory e-filing.
