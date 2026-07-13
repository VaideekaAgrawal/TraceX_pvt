# TraceX Metrics Ledger

Single running record of every quantitative metric produced by this project — dataset sizes, ML model performance, CI/test figures, pipeline run outputs, and system-behavior numbers surfaced during `/verify` or code review. This file exists so numbers don't live only in `docs/SESSION_LOG.md` prose (where they rot and drift, e.g. the README-vs-`cross_questions.md` XGBoost figure mismatch that had to be reconciled in Phase 3 — see `CLAUDE.md`'s landmine list).

**Update this file whenever a metric is added or changes** — new training run, new ingest, new test count, new CI timing, etc. See `CLAUDE.md` → General rules. Superseded values are struck through and dated, not deleted, so the history of a number is visible (e.g. a metric that regresses is a signal worth keeping).

---

## 1. Dataset / ingest (Phase 1)

Source: `backend/db/ingest.py` run against `data/HI-Small_accounts.csv` + `data/tracex_test_day1.csv`.

| Metric | Value | Recorded | Source |
|---|---|---|---|
| Customers ingested | 166,207 | Session 4 (2026-07-09) | `docs/SESSION_LOG.md` Session 4 & 6, `docs/ROADMAP.md` Phase 1 |
| Accounts ingested | **518,573** (Session 4/6 log) vs **518,889** (`docs/ROADMAP.md` Phase 1 checklist) — ⚠️ unreconciled discrepancy, flagged here 2026-07-10, not yet fixed | Session 4 (2026-07-09) | see above |
| Transactions ingested | 8,002 | Session 4 (2026-07-09) | same |
| Audit chain rows verified | 693,102 | Session 4 (2026-07-09) | same |

## 2. ML model performance (Phase 3 — XGBoost / IsolationForest ensemble)

Source: `archive/fund-flow-tracker/infrastructure/config.py` documented tuning result ("best config: capped_spw, exp v2, 2026-05-18"), reconciled into `docs/cross_questions.md` and `README.md` during Phase 3 (previously these two docs disagreed — see `CLAUDE.md` landmine list, now resolved).

| Metric | Value | Recorded | Source |
|---|---|---|---|
| PR-AUC | 0.64 | Phase 3 (2026-07-10) | `docs/cross_questions.md` |
| Precision | 0.778 (77.8%) | Phase 3 (2026-07-10) | `docs/cross_questions.md`, `README.md` |
| Recall | 0.609 (60.9%) | Phase 3 (2026-07-10) | `docs/cross_questions.md` |
| F1 | 0.683 | Phase 3 (2026-07-10) | `docs/cross_questions.md`, `README.md` |
| CV AUC / AUC-ROC | 0.933 | Phase 3 (2026-07-10) | `docs/cross_questions.md`, `README.md` |
| Precision (destination-labelled, rejected approach) | 0.049 (4.9%) — dropped from 0.778 when destination accounts were included in positive labels; confirms source-only labelling design choice | Phase 3 (2026-07-10) | `docs/cross_questions.md` |
| `xgb_scale_pos_weight` (hyperparameter, not a result metric but load-bearing) | 15.0 (deliberately capped) | Phase 3 (2026-07-10) | `backend/detection/config.py` |

## 3. Rule engine (Phase 3–4)

| Metric | Value | Recorded | Source |
|---|---|---|---|
| Built-in rules seeded | 8 of archive's 11 (deviation from literal plan, documented) | Phase 4 (2026-07-10) | `backend/detection/rules/seed.py`, `docs/SESSION_LOG.md` Session 7 |
| `dry_run` cycle-rule matches (real data) | 244 | Phase 3 `/verify` (2026-07-10) | `docs/SESSION_LOG.md` Session 6 |
| `dry_run` chain-rule matches (real data) | 311 | Phase 3 `/verify` (2026-07-10) | `docs/SESSION_LOG.md` Session 6 |
| Ego-graph fan-out cap | 500 (per hop, hub-account safety valve; live-stress-tested with synthetic 700-edge hub) | Phase 3 code review fix (2026-07-10) | `docs/SESSION_LOG.md` Session 6 |

## 4. Detection pipeline run output (Phase 4)

Source: `scripts/run_detection_pipeline.py` run live against the real ingested dataset (166,207 customers / ~518.6k accounts / 8,002 transactions) on a throwaway DB, run twice.

| Metric | Run 1 | Run 2 | Recorded | Source |
|---|---|---|---|---|
| Alerts generated | 2,738 | 3,981 | Phase 4 `/verify` (2026-07-10) | `docs/SESSION_LOG.md` Session 7 |
| Cases auto-created & assigned | 20 | 8 | Phase 4 `/verify` (2026-07-10) | `docs/SESSION_LOG.md` Session 7 |
| `case_assigned` audit rows per 20 assignments (pre-fix, duplicate-audit bug) | 40 | — | Phase 4 code review (2026-07-10) | `docs/SESSION_LOG.md` Session 7 |
| `case_assigned` audit rows per 20 assignments (post-fix) | 20 | — | Phase 4 code review (2026-07-10) | `docs/SESSION_LOG.md` Session 7 |
| `decision_changed` audit rows per case close | 1 | — | Phase 4 code review (2026-07-10) | `docs/SESSION_LOG.md` Session 7 |
| Workload split across 2 investigators (post auto-assignment) | 10 / 10 (perfectly balanced) | — | Phase 4 `/verify` (2026-07-10) | `docs/SESSION_LOG.md` Session 7 |

## 5. Test suite & CI

| Metric | Value | Recorded | Source |
|---|---|---|---|
| Test count — Phase 2 merge | 106 tests, 97% coverage | Session 5 (2026-07-09) | `docs/SESSION_LOG.md` Session 5 |
| Test count — Phase 3 merge | 198 tests | Session 6 (2026-07-10) | `docs/SESSION_LOG.md` Session 6 |
| Test count — Phase 4 merge | 270 tests | Session 7 (2026-07-10) | `docs/SESSION_LOG.md` Session 7 |
| Test count — Phase 1B merge | 275 tests | Session 8 (2026-07-11) | `docs/SESSION_LOG.md` Session 8 |
| Test count — Phase 5 merge | 304 tests, 97% coverage | Session 9 (2026-07-11/12) | `docs/SESSION_LOG.md` Session 9 |
| Test count — Phase 6 merge | ~~369 tests (pre-code-review)~~ → 379 tests, 97% coverage (post-code-review-fixes + live-verify NaN fix) — 2026-07-12 | Session 10 (2026-07-12) | `docs/SESSION_LOG.md` Session 10 |
| CI duration — Phase 0 (branch push) | not recorded numerically | Session 3 (2026-07-09) | — |
| CI duration — Phase 2 (branch push / PR) | 20m35s / 14m32s | Session 5 (2026-07-09) | `docs/SESSION_LOG.md` Session 5 |
| CI duration — Phase 3 (branch push / PR) | 20m12s / 20m9s (slower than Phase 1/2 due to new ML dependency install, not a regression) | Session 6 (2026-07-10) | `docs/SESSION_LOG.md` Session 6 |
| CI duration — Phase 4 (branch push / PR) | 18m34s / 22m8s | Session 7 (2026-07-10) | `docs/SESSION_LOG.md` Session 7 |
| CI duration — Phase 5 (branch push / PR) | 20m15s / 22m0s | Session 9 (2026-07-11/12) | `docs/SESSION_LOG.md` Session 9 |
| CI duration — Phase 6 (branch push / PR) | 22m22s / 22m13s | Session 10 (2026-07-12) | `docs/SESSION_LOG.md` Session 10 |
| Local pytest run time — Phase 1B (`.venv313`, full suite) | ~7.5 min (275 tests) | Session 8 (2026-07-11) | `docs/SESSION_LOG.md` Session 8 |
| Local pytest run time — Phase 5 (full suite, incl. coverage) | ~5.6 min (334.87s, 304 tests) | Session 9 (2026-07-11/12) | `docs/SESSION_LOG.md` Session 9 |
| Local pytest run time — Phase 6 (full suite, incl. coverage, post-fixes) | ~5.9 min (353.14s, 379 tests) | Session 10 (2026-07-12) | `docs/SESSION_LOG.md` Session 10 |

## 6. Login timing side-channel fix (Phase 2)

| Metric | Value | Recorded | Source |
|---|---|---|---|
| Response latency — unknown username / wrong password / inactive user (post-fix, 5x each, live-timed) | ~0.40–0.42s (converged) | Session 5 (2026-07-09) | `docs/SESSION_LOG.md` Session 5 |

## 7. Demo & Training Data Studio (Phase 1B)

Source: `backend/demo_data/`, run live against a throwaway SQLite DB via `backend/scripts/generate_demo_data.py`.

| Metric | Value | Recorded | Source |
|---|---|---|---|
| KYC demo customers + accounts seeded | 200 (~4% PEP, ~2% sanctioned, ~15% occupation/income mismatch) | Session 8 (2026-07-11) | `docs/SESSION_LOG.md` Session 8 |
| Relationship clusters seeded | 8 (2-4 customers each, shared pan/phone/email/employer/address/income_bracket/branch_city, zero transactions between members) | Session 8 (2026-07-11) | `docs/SESSION_LOG.md` Session 8 |
| Historical cases seeded | 50 (~50% FALSE_POSITIVE / 35% TRUE_POSITIVE_SAR / 15% ENHANCED_MONITORING) | Session 8 (2026-07-11) | `docs/SESSION_LOG.md` Session 8 |
| Golden edge-case scenarios seeded | 7 (one per typology), all 7 confirmed live to trigger their intended `DetectionType` through the real rule engine + alert pipeline | Session 8 (2026-07-11) | `docs/SESSION_LOG.md` Session 8 |
| Detection pipeline run against golden-scenario-only DB | 10 detections across 5 `DetectionType`s, 10 alerts generated | Session 8 (2026-07-11), reproduced identically pre- and post-code-review-fixes | `docs/SESSION_LOG.md` Session 8 |
| `rl_arm_state` audit rows written per `generate_demo_data.py` run | ~~50 (pre-fix, one per historical case)~~ → 1 (post-fix, single persist after the seeding loop) — 2026-07-11 | Session 8 (2026-07-11) | `docs/SESSION_LOG.md` Session 8 |
| `case_created` audit rows for 50 historical cases | 50 (1:1, confirms the backdating fix closed the audit-invariant gap — previously 0 audit rows for the `created_at` write) | Session 8 (2026-07-11) | `docs/SESSION_LOG.md` Session 8 |

## 8. L2 deep investigation (Phase 6)

Source: `scripts/run_detection_pipeline.py`/`scripts/train_detection_model.py` run live against a throwaway copy of the real ingested dataset (166,207 customers / 518,573 accounts / 8,002 transactions), then every new L2 route (`api/routes/l2.py`) driven over `TestClient` against a real, pipeline-generated case. First pass below is pre-code-review; the graph-latency figure was re-measured after the code-review's N+1 and redundant-query fixes.

| Metric | Value | Recorded | Source |
|---|---|---|---|
| Detections → alerts → auto-created cases (pipeline run) | 2,740 detections across 5 `DetectionType`s → 2,740 alerts → 20 auto-created/assigned cases | Session 10 (2026-07-12) | `docs/SESSION_LOG.md` Session 10 |
| `GET .../accounts/{account_id}/graph?radius=4` latency (real case-linked account) | ~~325ms (128 nodes / 162 edges, pre-code-review — per-node N+1 prior-SAR lookup)~~ → 96ms (post-fix: batched `list_for_primary_accounts` + reused case-account-id set) — 2026-07-12, includes the `graph_expanded` audit commit | Session 10 (2026-07-12) | `docs/SESSION_LOG.md` Session 10 |
| `GET .../profile` latency | 13ms | Session 10 (2026-07-12) | `docs/SESSION_LOG.md` Session 10 |
| `GET .../transactions/search` latency (case-wide) | 13ms (162 items) | Session 10 (2026-07-12) | `docs/SESSION_LOG.md` Session 10 |
| `GET .../behavior` latency | 8ms | Session 10 (2026-07-12) | `docs/SESSION_LOG.md` Session 10 |
| `GET .../timeline` latency | 7ms (65 events) | Session 10 (2026-07-12) | `docs/SESSION_LOG.md` Session 10 |
| `GET .../pattern-explanation` latency, no LLM key configured (fail-open path) | 6ms, `cached=False`, zero `AiInteraction` rows persisted | Session 10 (2026-07-12) | `docs/SESSION_LOG.md` Session 10 |
| `graph_expanded` audit rows after one `GET .../graph` call | 1 (confirmed via `audit_log` query — closes the Phase 4 deferral) | Session 10 (2026-07-12) | `docs/SESSION_LOG.md` Session 10 |
| Pandas-NaN-vs-Pydantic-`None` crash on `GET .../graph` (real data, blank `from_bank`/`to_bank`) | Found live (no seeded test fixture had ever left these columns blank); fixed via `graph_filters._sanitize_edge`, confirmed 200 post-fix on the exact real transaction that previously 500'd | Session 10 (2026-07-12) | `docs/SESSION_LOG.md` Session 10 |

## 9. Reuse-driven intelligence (Phase 7)

Source: `scripts/train_detection_model.py`/`run_detection_pipeline.py`/`generate_demo_data.py` run live against a throwaway copy of the real ingested dataset (166,207 customers / 518,573 accounts / 8,002 transactions), then the new routes (`GET .../similar-cases`, `GET .../relationships`, `GET .../money-flow`) driven over `TestClient`, plus `investigation.path_facts.compute_path_recommendation_facts` driven directly (no HTTP route).

| Metric | Value | Recorded | Source |
|---|---|---|---|
| Relationship Explorer candidate pool size (real data) | 213 (correctly gated to `pan IS NOT NULL OR income_bracket IS NOT NULL`, not the full 166,207 real customers) | Session 11 (2026-07-12) | `docs/SESSION_LOG.md` Session 11 |
| Relationships discovered (demo + real pool, one `generate_demo_data.py` run) | 5,382 total — branch: 1,620, income_bracket: 3,713, name: 40, pan: 9 (income_bracket/branch volume expected and by-design given their deliberately low 0.35/0.25 "coarse categorical" confidence over only ~6 buckets across ~200 customers) | Session 11 (2026-07-12) | `docs/SESSION_LOG.md` Session 11 |
| Similar Historical Cases similarity variance (real open case vs. 50-case demo corpus) | 0.9985 down to 0.9922 across top-5 (real variance, not pinned) | Session 11 (2026-07-12) | `docs/SESSION_LOG.md` Session 11 |
| `case_feature_vector` corpus growth after closing 2 real cases via the real decision endpoint | Both newly-closed cases correctly appeared in a third case's similar-cases results at similarity 1.0 (confirms `close_case`'s new upsert + live corpus growth, not just demo data) | Session 11 (2026-07-12) | `docs/SESSION_LOG.md` Session 11 |
| `GET .../money-flow` `pct_of_total` (real transaction data) | Sums to 100.0% per direction bucket (sources/beneficiaries) | Session 11 (2026-07-12) | `docs/SESSION_LOG.md` Session 11 |
| `compute_path_recommendation_facts` fund-flow % sum (real pipeline cases, 51-edge ego-graphs) | 100.0% per bucket across 15 sampled real cases, no crash/div-by-zero | Session 11 (2026-07-12) | `docs/SESSION_LOG.md` Session 11 |
| Test count — Phase 7 merge | 410 tests | Session 11 (2026-07-12) | `docs/SESSION_LOG.md` Session 11 |

---

## 10. PII / data-reality audit (Phase 8 planning — Session 13)

Queried directly against `data/tracex.db` (the IBM HI-Small ingest; **no demo seed applied to this DB**). Recorded here because Phase 8's entire PII posture, and the decision to keep `narration`/`purpose` out of prompts, rest on these numbers — a future session should not re-derive them, and **should re-check them if the ingest changes.**

| Metric | Value | Measured | Source |
|---|---|---|---|
| Customers (IBM HI-Small ingest) | 166,207 | Session 13 (2026-07-13) | `docs/SESSION_LOG.md` Session 13 |
| `customers.pan` populated | **0** | Session 13 (2026-07-13) | ditto |
| `customers.aadhaar` populated | **0** | Session 13 (2026-07-13) | ditto |
| `customers.phone` populated | **0** | Session 13 (2026-07-13) | ditto |
| Transactions | 8,002 | Session 13 (2026-07-13) | ditto |
| `transactions.narration` populated | **0** | Session 13 (2026-07-13) | ditto |
| `transactions.purpose` populated | **0** | Session 13 (2026-07-13) | ditto |

**Interpretation:** there is **no real customer PII in this project**. Customer "names" are IBM synthetic entities (`Corporation #33520`). The 🔒PII columns registered in `db/pii.py` are aspirational except where the `DEMO-` Phase 1B seed fills them. The attacker-controllable free-text fields the guardrail spec was written about (`narration`, `purpose`) **do not exist in the data at all** — excluding them from prompts costs zero features.

### Demo identifier safety audit (Session 13)

| Generator | Output shape | Verdict |
|---|---|---|
| `_synthetic_aadhaar` | `100000000000 + i` → 12 digits starting `1` | ✅ Safe — real Aadhaar never starts 0 or 1; structurally impossible to collide |
| `_synthetic_email` | `…@example-demo.invalid` | ✅ Safe — `.invalid` is an IANA-reserved TLD, can never resolve |
| `_synthetic_pan` | 5 letters + 4 digits + 1 letter | ⚠️ **Defect** — the exact real PAN format, and PAN has **no checksum**, so a generated value can collide with a real person's. Fix in Phase 8. |
| `_synthetic_phone` | `9700000001`-style | ⚠️ **Defect** — a real Indian mobile format; can collide with a live number. Fix in Phase 8. |

---

## How to keep this file current

- Any session that trains a model, runs the detection pipeline, changes CI, adds/removes tests, or re-ingests data: add or update the relevant row here before ending the session (part of `/session-end`).
- When a new value supersedes an old one, strike through the old value and date the change rather than deleting it — a regression in a metric (e.g. test count dropping, F1 falling) is itself informative and shouldn't be silently overwritten.
- If a metric is only reported in prose in `docs/SESSION_LOG.md` and not yet promoted here, that's a gap — promote it next time you touch this file.
- Known unresolved discrepancy: accounts-ingested count (§1) — needs a source-of-truth pass (re-run ingest and compare, or check whether the two paths counted different files/point-in-time).
