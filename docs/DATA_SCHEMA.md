# TraceX — System Data Schema (Greenfield)

**Status: design, Planning Session 2026-07-09.** This is the authoritative schema for the greenfield backend. It is the concrete spec for **ROADMAP Phase 1 (Data model & persistence foundation)** and the contract every later phase reads/writes. Written to be executed by a development session (Sonnet) **without re-deriving intent** — table names, column names, types, keys, enums, and reasoning are all explicit here.

Grounded in the actual dataset (IBM AML HI-Small adapted for India: `data/tracex_test_day1.csv`, `data/HI-Small_accounts.csv`) and the existing canonical models (`fund-flow-tracker/services/common/models.py`), rebuilt clean.

---

## 0. Conventions (apply to every table)

- **Engine:** SQLite for the pilot, PostgreSQL for production, behind a SQLAlchemy ORM + repository layer (ROADMAP Phase 1). All types below are given as **logical types**; the SQLite/Postgres realization is in the table under each type.
- **Types (logical → SQLite → Postgres):**
  - `TEXT` → `TEXT` → `TEXT`/`VARCHAR`
  - `INT` → `INTEGER` → `INTEGER`/`BIGINT`
  - `MONEY` → `NUMERIC` → `NUMERIC(18,2)` (never float for currency)
  - `REAL` → `REAL` → `DOUBLE PRECISION` (scores/ratios only)
  - `BOOL` → `INTEGER 0/1` → `BOOLEAN`
  - `TS` → `TEXT` ISO-8601 UTC (`YYYY-MM-DDTHH:MM:SSZ`) → `TIMESTAMPTZ`
  - `JSON` → `TEXT` (JSON-encoded) → `JSONB`
  - `ENUM` → `TEXT` + CHECK constraint → native `ENUM` or `TEXT`+CHECK
- **Primary keys:** stable human-readable business IDs for core entities (`customer_id`, `account_id`, `txn_id`, `alert_id`, `case_id`, `user_id`) because AML auditability needs stable references across time. Link/log tables use a surrogate autoincrement `id`.
- **Timestamps:** every table has `created_at TS`; mutable tables also have `updated_at TS`. All UTC.
- **PII tag:** columns marked **🔒PII** must be registered with the LLM-gateway redaction/tokenization middleware (ROADMAP Phase 8, decision 4) — they are pseudonymized before any external-LLM egress and re-hydrated on return. This column list *is* the redaction allow-map; keep it in sync.
- **Soft delete:** domain rows are never hard-deleted (regulatory retention). Use `active BOOL` / status columns. The only hard-delete path is the demo-reset by account prefix (dev only).
- **Audit invariant:** every write that a human or an AI agent causes also appends a row to `audit_log` (ROADMAP invariant). Repositories enforce this, not callers.
- **Case-scoping invariant:** anything graph- or AI-related is keyed by `case_id` and resolves accounts only through that case's scope (decision 5) — no query returns cross-case data.

---

## 1. Entity-relationship overview

```
customers ──1:N── accounts ──1:N(as source/dest)── transactions
    │                  │
    │                  └──N:1── branches (optional lookup)
    │
    └──(shared attrs)── relationships ──(entity pairs)

detection:  transactions/accounts ──► alerts ──N:1──► cases
governance: model_runs, rule_definitions, rl_arm_state, detection_feedback

case (spine):
  cases ──1:N── case_accounts        (accounts in scope)
  cases ──1:N── alerts               (alert.case_id)
  cases ──1:N── case_status_history
  cases ──1:N── evidence
  cases ──1:N── notes
  cases ──1:N── reports (SAR/STR)
  cases ──1:1── case_feature_vector  (for Similar Cases)
  cases ──N:1── users                (assigned_to)
  cases ──1:N── ai_interactions      (rec engine + copilot logs)

platform:  users, audit_log (append-only), watchlist, ingestion_log
```

---

## 2. Enums (single source of truth)

Reuse the existing string enums where noted; **replace `CaseStatus`** with the FSM below.

| Enum | Values | Notes |
|---|---|---|
| `Channel` | UPI, NEFT, RTGS, IMPS, net_banking, mobile_app, ATM, branch_cash, cheque, unknown | reuse existing; map CSV `Payment Format` → this |
| `RiskLevel` | LOW, MEDIUM, HIGH, CRITICAL | reuse |
| `Priority` | P1, P2, P3, P4 | reuse (P1 = most urgent) |
| `AccountRole` | SOURCE, MULE, SINK, NORMAL | reuse; per-case, not global |
| `DetectionType` | layering, round_trip, structuring, dormancy, profile_mismatch | reuse; extend as detectors are added |
| **`CaseStatus`** (NEW) | NEW, ASSIGNED, IN_PROGRESS, AWAITING_REVIEW, ESCALATED, CLOSED_TP, CLOSED_FP, MONITORING | replaces old flat enum; matches ROADMAP Phase 4 FSM |
| `CaseLevel` | L1, L2 | triage vs deep investigation |
| `CaseResolution` | FALSE_POSITIVE, TRUE_POSITIVE_SAR, ENHANCED_MONITORING, ESCALATED_COMPLIANCE, "" | set on close; drives feedback loop |
| `UserRole` | INVESTIGATOR, ADMIN_COMPLIANCE | two roles only (decision, RBAC) |
| `KycStatus` | VERIFIED, PENDING, EXPIRED, REJECTED | customer-level |
| `EddStatus` | NOT_REQUIRED, REQUIRED, IN_PROGRESS, COMPLETE | CDD/EDD |
| `EntityType` | INDIVIDUAL, BUSINESS | customer type |
| `AccountStatus` | ACTIVE, DORMANT, CLOSED, FROZEN | account lifecycle |
| `EvidenceType` | TRANSACTION, ACCOUNT, GRAPH_SNAPSHOT, DOCUMENT, PATTERN, NOTE_REF | evidence pack items |
| `ActorType` | INVESTIGATOR, ADMIN, SYSTEM, AI | audit_log actor kind |
| `AiAgent` | RECOMMENDATION, COPILOT | which agent produced an interaction |
| `ReportType` | SAR, STR | regulatory report |
| `ReportStatus` | DRAFT, FINALIZED, SUBMITTED | report lifecycle |
| `WatchEntityType` | CUSTOMER, ACCOUNT, DEVICE, MERCHANT, COMPANY | watchlist target |
| `NoteSource` | INVESTIGATOR, COPILOT | who authored a note (copilot can write) |

---

## 3. Table specifications

### 3.1 Reference / domain

#### `customers`  — the legal entity (CSV `Entity ID` / `Entity Name`)
| Column | Type | Null | Key | Notes |
|---|---|---|---|---|
| customer_id | TEXT | no | PK | CSV `Entity ID` |
| name | TEXT | no | | 🔒PII — CSV `Entity Name` |
| entity_type | ENUM EntityType | no | | INDIVIDUAL/BUSINESS |
| pan | TEXT | yes | idx | 🔒PII — aspirational (not in current data) |
| aadhaar | TEXT | yes | | 🔒PII — aspirational |
| phone | TEXT | yes | idx | 🔒PII — aspirational |
| email | TEXT | yes | idx | 🔒PII — aspirational |
| address | TEXT | yes | | 🔒PII — aspirational |
| occupation | TEXT | yes | | populated (CSV Source/Dest_Occupation) |
| declared_annual_income | MONEY | yes | | populated (CSV Declared_Income) |
| income_bracket | TEXT | yes | | low/medium/high (derived) |
| employer | TEXT | yes | idx | 🔒PII — aspirational; relationship explorer |
| kyc_status | ENUM KycStatus | no | | default PENDING |
| edd_status | ENUM EddStatus | no | | default NOT_REQUIRED |
| pep_status | BOOL | no | | default 0; aspirational flag |
| sanction_status | BOOL | no | | default 0; aspirational flag |
| risk_rating | ENUM RiskLevel | no | | customer-level baseline risk |
| created_at | TS | no | | |
| updated_at | TS | no | | |

*Reasoning:* one entity → many accounts (HI-Small structure). KYC/PEP/sanction/PAN/etc. are schema-complete now even though the synthetic set doesn't fill them — so L1 "Customer Snapshot" and the Relationship Explorer have their target shape from day one and only need data, not migrations, later. Every identity column is 🔒PII for the redaction map.

#### `accounts`  — a bank account (CSV `Account Number`)
| Column | Type | Null | Key | Notes |
|---|---|---|---|---|
| account_id | TEXT | no | PK | CSV `Account`/`Account Number` (e.g. PMFRAUD01) |
| customer_id | TEXT | yes | FK→customers | nullable: some txn accounts have no KYC record |
| account_type | TEXT | no | | savings/current/… default savings |
| bank_name | TEXT | yes | | CSV `From/To Bank` |
| bank_id | TEXT | yes | | CSV `Bank ID` |
| branch_city | TEXT | yes | idx | |
| status | ENUM AccountStatus | no | | default ACTIVE |
| kyc_tier | TEXT | yes | | full/min |
| opening_date | TS | yes | | account age → dormancy detector |
| expected_monthly_volume | MONEY | yes | | for behaviour-deviation |
| current_risk_score | REAL | yes | | 0–100, latest ensemble score (denormalized cache) |
| created_at | TS | no | | |
| updated_at | TS | no | | |

*Reasoning:* `current_risk_score` is a denormalized cache of the latest `alerts`/detection score so L1 triage doesn't recompute; source of truth is detection output, refreshed on each run.

#### `transactions`  — the atomic unit (CSV rows)
| Column | Type | Null | Key | Notes |
|---|---|---|---|---|
| txn_id | TEXT | no | PK | deterministic hash if source lacks id |
| timestamp | TS | no | idx | CSV `Timestamp` (parse `YYYY/MM/DD HH:MM`) |
| source_account | TEXT | no | FK→accounts, idx | CSV `Account` |
| dest_account | TEXT | no | FK→accounts, idx | CSV `Account.1` |
| amount | MONEY | no | | CSV `Amount Paid` (use paid side) |
| amount_received | MONEY | yes | | CSV `Amount Received` (fx cases) |
| currency | TEXT | no | | default INR |
| channel | ENUM Channel | no | | map CSV `Payment Format` |
| txn_type | TEXT | no | | transfer/deposit/withdrawal default transfer |
| narration | TEXT | yes | | 🔒PII + **attacker-controllable** → sanitize before any prompt (Phase 8) |
| purpose | TEXT | yes | | declared purpose; same guardrail as narration |
| merchant_type | TEXT | yes | | |
| is_laundering | INT | no | | ground-truth label (CSV `Is Laundering`); training only, never shown as fact |
| from_bank | TEXT | yes | | CSV `From Bank` |
| to_bank | TEXT | yes | | CSV `To Bank` |
| reference_id | TEXT | yes | | |
| source_file_hash | TEXT | yes | FK→ingestion_log | provenance |
| ingested_at | TS | no | | |

*Composite indexes:* `(source_account, timestamp)`, `(dest_account, timestamp)` — the two hot paths for ego-graph extraction and timeline reconstruction. *Reasoning:* `narration`/`purpose` are the attacker-controllable fields called out in the guardrail spec — flagged here so Phase 8 sanitization has an exact target list.

---

### 3.2 Detection & governance

#### `alerts`  — detector output for investigator review
| Column | Type | Null | Key | Notes |
|---|---|---|---|---|
| alert_id | TEXT | no | PK | deterministic id (accounts+type+date), see existing `make_deterministic_alert_id` |
| case_id | TEXT | yes | FK→cases, idx | null until a case is created; one alert → one case |
| detection_type | ENUM DetectionType | no | idx | |
| primary_account_id | TEXT | no | FK→accounts | the account the alert centers on |
| account_ids | JSON | no | | all accounts in the pattern |
| score | REAL | no | | 0–1 detector confidence |
| risk_score | REAL | no | idx | 0–100 composite ensemble score |
| severity | ENUM RiskLevel | no | | |
| priority | ENUM Priority | no | | |
| confidence | TEXT | yes | | ConfidenceLevel label |
| status | TEXT | no | | open/assigned/closed |
| rule_ids | JSON | yes | | which `rule_definitions` fired |
| model_run_id | TEXT | yes | FK→model_runs | which model version scored it (governance) |
| source | TEXT | no | | pipeline/realtime |
| created_at | TS | no | idx | |
| last_seen_at | TS | no | | refreshed on re-detection (idempotent) |

*Reasoning:* `model_run_id` ties every alert to the exact model version + metrics that produced it (ML governance, §5). Deterministic `alert_id` prevents duplicate rows on re-detection.

#### `model_runs`  — ML model governance / lineage
| Column | Type | Null | Key | Notes |
|---|---|---|---|---|
| run_id | TEXT | no | PK | |
| model_name | TEXT | no | | e.g. ensemble_v1 |
| model_type | TEXT | no | | isolation_forest / xgboost / ensemble |
| version | TEXT | no | | semantic version |
| trained_at | TS | no | | |
| dataset_hash | TEXT | yes | | training-set provenance |
| metrics | JSON | no | | {f1, auc_roc, precision, recall} — reconcile README vs cross_questions |
| feature_importance | JSON | yes | | |
| artifact_path | TEXT | yes | | serialized model location (persist, no retrain-on-boot) |
| active | BOOL | no | | exactly one active per model_name |

#### `rule_definitions`  — Rule Engine DSL + feedback confidence
| Column | Type | Null | Key | Notes |
|---|---|---|---|---|
| rule_id | TEXT | no | PK | |
| name | TEXT | no | | |
| dsl | JSON | no | | serialized rule (11 primitives, Tier-2 composition) |
| tier | INT | no | | 1 or 2 |
| confidence | REAL | no | | adjusted by detection_feedback loop |
| enabled | BOOL | no | | |
| created_by | TEXT | yes | FK→users | Admin/Compliance only edits |
| created_at / updated_at | TS | no | | |

#### `rl_arm_state`  — LinUCB bandit persistence (no reset on boot)
| Column | Type | Null | Key | Notes |
|---|---|---|---|---|
| arm_id | TEXT | no | PK | arm = action/alert-class the bandit ranks |
| a_matrix | JSON | no | | d×d matrix (d=16) |
| b_vector | JSON | no | | d-vector |
| updated_at | TS | no | | |

*Reasoning:* the bandit's `A`/`b` are all that's needed to resume learning; persisting them fixes the "RL state lost on restart" landmine and is reused by both the queue and (later) Path Recommendation ranking.

#### `detection_feedback`  — investigator verdict → RL reward + rule confidence
| Column | Type | Null | Key | Notes |
|---|---|---|---|---|
| id | INT | no | PK auto | |
| case_id | TEXT | no | FK→cases | |
| alert_id | TEXT | yes | FK→alerts | |
| verdict | ENUM CaseResolution | no | | FP/TP_SAR/etc. |
| reward | REAL | no | | signal fed to `rl_arm_state` |
| rule_ids | JSON | yes | | rules whose confidence was adjusted |
| created_by | TEXT | no | FK→users | |
| created_at | TS | no | | |

---

### 3.3 Investigation spine

#### `cases`  — single source of truth (kills the two-store landmine)
| Column | Type | Null | Key | Notes |
|---|---|---|---|---|
| case_id | TEXT | no | PK | |
| primary_account_id | TEXT | no | FK→accounts | the investigated account (ego-graph anchor) |
| title | TEXT | yes | | |
| status | ENUM CaseStatus | no | idx | FSM |
| level | ENUM CaseLevel | no | | L1/L2 |
| priority | ENUM Priority | no | idx | |
| typology | TEXT | yes | | dominant DetectionType |
| risk_score | REAL | yes | | case-level (from alerts) |
| network_risk_score | REAL | yes | | packaged network score (Phase 5) |
| network_risk_reasons | JSON | yes | | the explained factors behind it |
| assigned_to | TEXT | yes | FK→users, idx | workload-based auto-assign |
| sla_due_at | TS | yes | | SLA timer |
| created_at | TS | no | | |
| updated_at | TS | no | | |
| closed_at | TS | yes | | |
| resolution | ENUM CaseResolution | yes | | set on close |
| resolution_reason | TEXT | yes | | investigator justification |
| evidence_hash | TEXT | yes | | SHA-256 over finalized evidence pack |

*Reasoning:* one row per case, one `assigned_to`, one status — everything case-centric (evidence, notes, SLA, audit, AI) foreign-keys here. `network_risk_score` + `_reasons` are stored (not recomputed each view) so L1 is fast and the reason is auditable.

#### `case_accounts`  — accounts in a case's scope (M:N)
| Column | Type | Null | Key | Notes |
|---|---|---|---|---|
| id | INT | no | PK auto | |
| case_id | TEXT | no | FK→cases, idx | |
| account_id | TEXT | no | FK→accounts | |
| role | ENUM AccountRole | yes | | per-case role (SOURCE/MULE/SINK) |
| hop_distance | INT | yes | | hops from primary account (ego-graph) |

*Reasoning:* defines exactly which accounts the case-scoping invariant permits AI/graph tools to touch — this table *is* the security boundary for a case.

#### `case_status_history`  — FSM transition log
| id (PK auto) | case_id FK | from_status ENUM | to_status ENUM | changed_by FK→users | reason TEXT | changed_at TS |

*Reasoning:* explicit history (not derived) so SLA/escalation reporting and "who moved this case when" are first-class; complements audit_log with typed workflow semantics.

#### `evidence`  — evidence pack items
| Column | Type | Null | Key | Notes |
|---|---|---|---|---|
| evidence_id | TEXT | no | PK | |
| case_id | TEXT | no | FK→cases, idx | |
| type | ENUM EvidenceType | no | | |
| ref_id | TEXT | yes | | txn_id/account_id/report_id it points to |
| label | TEXT | yes | | investigator caption |
| payload | JSON | yes | | e.g. saved graph snapshot, highlighted path |
| file_path | TEXT | yes | | attached documents |
| pinned | BOOL | no | | |
| added_by | TEXT | no | FK→users | |
| added_at | TS | no | | |

#### `notes`  — case notes (investigator OR copilot)
| note_id PK | case_id FK,idx | author_id FK→users | source ENUM NoteSource | body TEXT (🔒 may contain PII) | created_at TS | updated_at TS |

*Reasoning:* `source` distinguishes copilot-written notes from human ones (decision: copilot can take case-specific notes) while keeping one notes store.

#### `reports`  — SAR/STR generation (FIU-IND)
| Column | Type | Null | Key | Notes |
|---|---|---|---|---|
| report_id | TEXT | no | PK | |
| case_id | TEXT | no | FK→cases | |
| type | ENUM ReportType | no | | SAR/STR |
| status | ENUM ReportStatus | no | | |
| narrative | TEXT | yes | | auto-generated, editable (Phase 11) |
| json_payload | TEXT | yes | | FIU-IND JSON |
| json_hash | TEXT | yes | | SHA-256 tamper seal (existing EvidencePack pattern) |
| pdf_path | TEXT | yes | | |
| fiu_reference | TEXT | yes | | external filing ref |
| generated_by | TEXT | no | FK→users | |
| generated_at | TS | no | | |
| submitted_at | TS | yes | | |

#### `case_feature_vector`  — for Similar Historical Cases
| case_id PK,FK | vector JSON (16 floats, same space as RL bandit) | typology TEXT | outcome ENUM CaseResolution | computed_at TS |

*Reasoning:* Similar Cases (Phase 7) = cosine similarity over this vector; reuse the RL 16-dim feature space instead of a new pipeline (§4.1 design note). Store outcome so a match can show "→ SAR filed".

---

### 3.4 AI orchestration

#### `ai_interactions`  — audit + grounding log for BOTH agents
| Column | Type | Null | Key | Notes |
|---|---|---|---|---|
| id | INT | no | PK auto | |
| case_id | TEXT | yes | FK→cases, idx | null for cross-case copilot queries (e.g. "find my cases") |
| agent | ENUM AiAgent | no | | RECOMMENDATION/COPILOT |
| user_id | TEXT | no | FK→users | who invoked / is scoped to |
| request_text | TEXT | yes | | 🔒 stored post-sanitization |
| tools_called | JSON | yes | | fixed-catalog tools invoked (never free-form) |
| facts | JSON | yes | | the tool-computed facts that grounded the answer (the "driving facts" — makes recs auditable) |
| rule_anchors | JSON | yes | | typology/regulation anchors (rec engine) |
| response_text | TEXT | no | | AI output, labeled AI-generated |
| model | TEXT | no | | e.g. claude-opus-4-8 |
| model_provider | TEXT | no | | openrouter/self-hosted (gateway) |
| redacted | BOOL | no | | whether PII redaction was applied on egress |
| latency_ms | INT | yes | | |
| investigator_feedback | TEXT | yes | | accepted/rejected/edited — future learning signal |
| created_at | TS | no | | |

*Reasoning:* this is what makes "not a stupid LLM call" provable — every recommendation persists its driving facts + rule anchors + which tools produced them, so a regulator can reconstruct *why* the system said what it said, and cross-questioning replays from stored grounding. Also the substrate for the workflow-learning roadmap item.

#### `relationships`  — Relationship Explorer discovered edges
| id PK auto | entity_a FK→customers | entity_b FK→customers | shared_attribute TEXT (phone/email/pan/aadhaar/device/ip/address/employer/nominee/introducer/branch) | value_hash TEXT (🔒 hashed, not raw) | confidence REAL | method TEXT | discovered_at TS |

*Reasoning:* stores hidden links transactions can't reveal (§4.2). `value_hash` not raw value → the graph shows "shared phone" without exposing the number. **v1 (Phase 7) only populates name/branch/income/PAN**; device/IP/nominee/introducer wait on data.

---

### 3.5 Platform

#### `users`
| user_id PK | username TEXT unique | email TEXT (🔒PII) | password_hash TEXT | role ENUM UserRole | full_name TEXT (🔒PII) | active BOOL | last_login_at TS | created_at TS |

*Reasoning:* two roles only. `last_login_at` powers the Copilot "what changed since last login" digest (diff audit_log since this timestamp). Workload for auto-assignment is derived (`COUNT(cases WHERE assigned_to=? AND status open)`), not stored.

#### `audit_log`  — append-only, tamper-evident, every action
| Column | Type | Null | Key | Notes |
|---|---|---|---|---|
| id | INT | no | PK auto | monotonic |
| actor_type | ENUM ActorType | no | | INVESTIGATOR/ADMIN/SYSTEM/AI |
| actor_id | TEXT | yes | | user_id or agent name |
| action | TEXT | no | idx | e.g. alert_opened, graph_expanded, evidence_pinned, note_added, decision_changed, escalated, ai_recommendation |
| entity_type | TEXT | no | | case/alert/account/report/… |
| entity_id | TEXT | yes | idx | |
| case_id | TEXT | yes | idx | for per-case reconstruction |
| details | JSON | yes | | before/after or params |
| prev_hash | TEXT | yes | | hash of previous row |
| row_hash | TEXT | no | | SHA-256(this row + prev_hash) → tamper-evident chain |
| created_at | TS | no | idx | |

*Reasoning:* one unified queryable log (fixes the "partial/implicit audit" landmine). The `prev_hash`/`row_hash` chain gives tamper-evidence (a regulatory expectation) cheaply — reusing the SHA-256 pattern already in `EvidencePack`. Append-only: no updates/deletes ever.

#### `watchlist`
| entry_id PK | entity_type ENUM WatchEntityType | entity_value TEXT (🔒 if PII) | reason TEXT | added_by FK→users | active BOOL | expires_at TS | created_at TS |

*Reasoning:* alerts touching a watchlisted entity get auto-priority (Phase 11); maps to FATF R.10 ongoing due diligence.

#### `ingestion_log`  — idempotent CSV ingest
| file_hash PK | filename TEXT | business_date TS | num_transactions INT | num_accounts INT | status TEXT | validation JSON (size/MIME/row-count checks) | ingested_at TS |

*Reasoning:* prevents double-ingesting the same file; `validation` records the upload-safety checks (§5 upload validation) so a rejected file's reason is inspectable.

---

## 4. Confirmed decisions (locked 2026-07-09)

1. **Alert↔case cardinality:** **one alert → one case, one case → many alerts** (`alerts.case_id`). No multi-case membership. ✅
2. **Customer coverage:** `accounts.customer_id` is nullable; L1 "Customer Snapshot" degrades gracefully to account-only when no customer row exists. But for the pitch, demo data **must** populate rich customer/KYC records (see §6). ✅
3. **Audit tamper-evidence:** SHA-256 hash-chain (`prev_hash`/`row_hash`) is sufficient for the pilot/pitch. ✅
4. **Relationship Explorer:** columns for all shared attributes exist now; **for the pitch we generate mock data that populates PAN/phone/email/address/device/employer/nominee** so the feature demos fully (see §6) — not limited to name/branch/income. ✅
5. **Currency:** `NUMERIC`, INR default, single-currency display for pilot; fx captured via `amount` (paid) + `amount_received`. ✅

## 6. Data strategy — trained engine, generated training data, and demo showcase

Three **separate** data concerns; do not conflate them (detail lives in ROADMAP **Phase 1B — Demo & Training Data Studio**):

- **(a) Trained detection engine — train once, persist, never retrain on boot.** Confirmed during Phase 0 (`archive/SALVAGE.md`) and executed in Phase 3: no serialized ML model artifact exists anywhere in the archive — the old system retrained XGBoost from `data/` on every pipeline run, the exact "ML model retrains from scratch each boot" landmine (`CLAUDE.md`). Phase 3 ports the detector/feature-engineering/ensemble-weighting *logic* unchanged (tuned hyperparameters/weights from `archive/fund-flow-tracker/infrastructure/config.py`, not re-derived), trains once against the root-level `data/` set via `scripts/train_detection_model.py`, and persists the resulting artifact to `model_runs.artifact_path` (`detection/scoring/training.py::train_and_persist`) — never retrained on boot again. No from-scratch retraining of the core detector *logic* either (ported as-is, not redesigned).
- **(b) Generated training/reference data** for features that need their own corpus:
  - **Similar Historical Cases** — seed a corpus of past `cases` + `case_feature_vector` + `resolution` (SAR/FP) so cosine retrieval returns real matches.
  - **RL bandit** — seed `detection_feedback` events so the queue looks learned, not cold-start, in a demo.
- **(c) Mock showcase data** — engineered, seeded, reproducible, and clearly tagged as demo (reserved account-id prefix, e.g. `DEMO-`, isolated from real ingest via `ingestion_log`):
  - **KYC/customer** rows populating `pep_status`, `sanction_status`, `kyc_status`, occupation-vs-income mismatch → makes Customer Snapshot + profile-mismatch land.
  - **Relationship networks** — accounts with **no direct transaction link** but a shared `pan`/`phone`/`device`/`employer`/`nominee` → the Relationship Explorer "hidden mule network" reveal.
  - **Golden edge-case scenarios** — one curated network per typology (clean layering, structuring-across-branches, circular/round-trip, dormancy reactivation, profile mismatch, sanction match, funnel mule) each with a **known-correct investigation path** so the Recommendation Engine + Copilot demo deterministically, with a written feature-explanation for each.
  - Each scenario documented as: scenario → feature(s) it showcases → expected system output → the edge case it proves.

## 5. Phase-1 build order (maps to ROADMAP Phase 1 checklist)
1. Enums + `customers`, `accounts`, `transactions` (+ composite indexes) → ingest path + `ingestion_log` with upload validation.
2. `users` + `audit_log` (needed before any authored write).
3. Detection tables: `alerts`, `model_runs`, `rule_definitions`, `rl_arm_state`, `detection_feedback` + model/bandit artifact persistence.
4. Investigation spine: `cases`, `case_accounts`, `case_status_history`, `evidence`, `notes`, `reports`, `case_feature_vector`.
5. AI + platform: `ai_interactions`, `relationships`, `watchlist`.
6. Register the 🔒PII column set with the (stubbed) redaction map so Phase 8 has its target list.
