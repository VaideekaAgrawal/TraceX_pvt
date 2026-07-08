# TraceX Backend Improvement — Session Summary
**Date:** 2026-06-30  
**Session:** [backend improvement]  
**Scope:** Full backend audit + targeted fixes across API, infrastructure, detection, investigation, ingestion, and frontend observability layers  
**Test suite:** 160 pass, 1 pre-existing failure (SQLite adapter, unrelated) — zero regressions introduced

---

## Session Goal

Following the ML pipeline session (85.9% recall, 5/5 PASS), this session focused on hardening the backend and making the output layer trustworthy for bank compliance officers who don't understand ML. Three audit agents ran in parallel, then four implementation agents fixed everything in parallel. No regressions.

---

## Audit Method

Three read-only audit forks ran simultaneously:
1. **API + Infrastructure** (`server.py`, `database.py`, `event_bus.py`, `health.py`, `models.py`, `contracts.py`)
2. **Detection + ML Services** (all `services/detection/`, `services/graph/`, `services/ingestion/`, `services/investigation/`)
3. **Output / Observability** (all frontend pages, `api/server.py` response shapes, `utils/visualization.py`)

---

## Root Causes Found (by category)

### Output / Analyst Trust Gap (Most Critical Business Impact)
- `indicators: string[]` (plain-language "why") was returned by API but **never rendered** in the frontend — biggest trust gap
- Raw ML numbers shown to compliance officers: `fraud_probability: 0.8234`, `anomaly_score: 67.43`, XGBoost feature importance bar chart
- ML Model Performance panel (AUC-ROC 0.834, confusion matrix, precision/recall) on the main analyst dashboard — an officer reading "recall: 0.653" would correctly infer 37% miss rate and lose confidence
- `is_laundering: 1` ground-truth IBM label exposed in every transaction response — false signal in a real deployment
- Evidence PDF printed internal codes (`fan_out: 2 instance(s)`) — a compliance officer filing an STR saw `fan_out`, not "High-Degree Fund Dispersal"
- `visit_probability: 0.47` shown next to accomplice accounts — random walk term meaningless to analysts
- `confidence_count: (4)` shown in table — looked like a version number

### Detection Logic Bugs
- Isolation Forest still counted in `compute_confidence` (was explicitly excluded from scoring in ML session because IF is inverted on this dataset — clean accounts score higher)
- Structuring detector had no time window — 3 near-threshold transactions in 3 years triggered alert
- `velocity_10min` and `velocity_1hour` features were both identical (`max_daily_txn_count`) — XGBoost double-counting
- `geographic_dispersion` was hardcoded `0.0` for every account — wasted feature slot
- Chain deduplication used `(first_node, last_node)` fingerprint — collapsed distinct paths `A→B→C→D` and `A→X→Y→D`
- Dormancy burst off-by-one (`>` instead of `>=`); new accounts with zero prior outgoing falsely flagged as dormant
- Profile detector: fragile `acc_id` extraction after `reset_index()`; reported first spike not most anomalous

### API Performance Bugs
- `compute_centrality()` (PageRank + betweenness) called **200 times per `/api/anomaly` request** — inside per-account loop
- `anomaly[anomaly["account_id"] == acc_id]` inside `iterrows()` loop — O(n²) DataFrame scan for account listing
- `list.pop(0)` in BFS — O(n) dequeue, BFS degraded from O(V+E) to O(V²)
- `iterrows()` in `get_transaction_chains` chain extraction — 10-100× slower than vectorized on large datasets

### Infrastructure / Security
- File path injection: `req.filepath` passed directly to `eod_svc.ingest_daily_file()` — caller could read `../../etc/passwd`
- Upload filename unsanitized: `os.path.join(upload_dir, file.filename)` — `../../api/server.py` would overwrite server files
- SQLite: single shared `self._conn` across all requests — undefined behavior under concurrent writes
- SQLite path relative — different CWD created ghost databases at different locations
- `_response_cache` not cleared after `/api/init` or `/api/refresh` — stale data served for 30s after new data loaded
- `event_bus._event_log` grew forever (no TTL or cap) — would OOM a long-running server
- DLQ `pop(0)` was O(n); `datetime.utcnow()` deprecated in Python 3.12
- `health.is_ready()` returned True when services were in "starting" state — load balancers routed traffic before init

### Case Management / Ingestion Reliability
- Alert/case ID counters reset to 0 on restart — `ALT-0001` reissued for a completely different alert (collision)
- No alert deduplication: running pipeline 3 times created 3 identical alerts per detection
- EOD alert IDs included `datetime.now()` timestamp — re-running created duplicates with different IDs
- `txn_id = TXN-{date}-{i:08d}` — two files on same date produced identical transaction IDs
- EOD round-trip detection had no temporal constraint — A→B in January + B→A in December = alert
- Velocity spike threshold was batch-size dependent (raw count, not rate)
- N+1 DB queries in ingestion: 100K accounts = 100K individual `SELECT account_exists()` calls
- Graph time filter used lexicographic string comparison instead of datetime

---

## All Fixes Applied

### Detection Layer
| File | Fix |
|---|---|
| `services/detection/ensemble.py` | Removed IF block from `compute_confidence` (~line 462) |
| `services/detection/structuring.py` | `_detect_classic` now uses 30-day rolling window; `detect()` deduplicates by account |
| `services/detection/features.py` | Removed duplicate `velocity_10min`; `geographic_dispersion` → bank-code diversity proxy |
| `services/detection/layering.py` | Chain dedup uses full node sequence; added `max_results=500` cap |
| `services/detection/dormancy.py` | Fixed `>= split_row` off-by-one; new-account guard when `pre_avg == 0 and len(pre) < 2` |
| `services/detection/profile.py` | `accs.index.name = "account_id"` before reset_index; sort by z_score for best spike; simplified income_mismatch guard |
| `services/graph/engine.py` | `deque` + `popleft()` in BFS; `to_dict("records")` instead of `iterrows()`; tuples in edge-seen set instead of `hash()` |
| `tests/test_pipeline_e2e.py` | Feature count: 29 → 28 (removed duplicate) |
| `tests/test_incremental_ingestion.py` | Feature count: 29 → 28 |

### API Layer
| File | Fix |
|---|---|
| `api/server.py` | `compute_centrality()` moved out of 200-account loop |
| `api/server.py` | Pre-built `anomaly_score_map`, `fraud_prob_map` dicts — O(n²) → O(n) account listing |
| `api/server.py` | `_safe_ingest_path()` whitelist — blocks path traversal in `/api/ingest` |
| `api/server.py` | Upload filename: `uuid + basename`, strips directory components |
| `api/server.py` | `_response_cache.clear()` added to `init_system` and `refresh_from_db` |
| `api/server.py` | Graph time filter uses `pd.Timestamp` comparison |
| `api/server.py` | `Query(ge=…, le=…)` bounds on `max_nodes`, `max_edges`, `radius`, `num_steps` |
| `api/server.py` | `is_laundering` removed from all client-facing transaction serialization |

### Infrastructure
| File | Fix |
|---|---|
| `infrastructure/database.py` | `_get_conn` creates/commits/closes fresh connection per call — thread-safe |
| `infrastructure/database.py` | `SQLITE_PATH` resolved to absolute path via `_THIS_DIR` |
| `infrastructure/event_bus.py` | `_event_log` → `deque(maxlen=10_000)` per topic; DLQ uses deque; `datetime.now(timezone.utc)` |
| `infrastructure/health.py` | `is_ready()` requires status == "healthy" (not "starting"); `record_error()` sets "degraded" at ≥5 errors |

### Investigation / Evidence / Ingestion
| File | Fix |
|---|---|
| `services/investigation/case_manager.py` | UUID-based IDs (`ALT-{date}-{uuid8}`); removed counter; `_find_open_alert()` dedup before create |
| `services/investigation/evidence.py` | `DETECTION_LABELS` map + `_label_detection()` — PDF uses human language; `_abbrev_acc()` for long IDs; latin-1 uses `"ignore"` |
| `services/ingestion/eod_service.py` | `_make_alert_id()` — SHA-256 deterministic alert IDs; txn_id includes file hash; round-trip 48h constraint; velocity rate-normalized |
| `services/ingestion/service.py` | Chunked bulk account existence query (1000/batch); swallowed DB errors → `logger.warning` |

### Frontend (Analyst-Facing)
| File | Fix |
|---|---|
| `frontend/src/app/anomaly/page.tsx` | `indicators[]` rendered as "Signals (Why Flagged)" bullet column — was received but never shown |
| `frontend/src/app/anomaly/page.tsx` | Feature importance chart removed; `anomaly_score` → categorical (Unusual / Moderate / Normal); confidence `HIGH (4)` → `HIGH — 4 signals`; fraud_probability column removed |
| `frontend/src/app/page.tsx` | ML metrics panel (AUC-ROC, confusion matrix) removed; replaced with "Action Required" (critical alerts, high-risk count, flagged accounts) |
| `frontend/src/app/page.tsx` | "Avg Risk" stat → "Critical Alerts" (actionable count); "Patterns" column added to alerts table |
| `frontend/src/app/evidence/page.tsx` | `JSON.stringify` summary → structured human-readable card with INR formatting |
| `frontend/src/app/graph/page.tsx` | `visit_probability` → Strong/Moderate/Weak label with "Frequency of appearing in fund flow paths" subtitle |
| `frontend/src/app/patterns/page.tsx` | STACK amount_decay: "0.0%" → "Extended pattern (decay not applicable)" |

---

## What Is Still Outstanding

The following issues were identified in the audit but are **not fixed** — they require either a database migration, authentication infrastructure, or are architectural in nature:

1. **No authentication** — every endpoint is open; needs `Depends(verify_api_key)` + JWT/API key system
2. **ML model state lost on restart** — `FraudClassifier` retrains from scratch on every server start; needs joblib persistence + model registry
3. **Case/alert state lost on restart** — `case_manager` is in-memory; needs DB persistence (`db.save_case()`, `db.load_cases()`)
4. **Bitcoin mapped to UPI** in `constants.py` — Bitcoin channel treated as domestic payment instrument; wrong thresholds + reporting
5. **Hardcoded stale FX rates** including `"Bitcoin": 5_500_000.0` INR — structuring thresholds wrong for cross-currency transactions
6. **`EvidencePack.compute_hash()` on empty payload** — hashes empty string and stores as tamper-detection hash
7. **`/api/patterns/first-suspicious` look-ahead Z-score bias** — uses full transaction history to compute baseline, not rolling
8. **`upsert_accounts` row-by-row insert** in `database.py` — should use `executemany` for bulk insert
9. **No audit log for case mutations** — `PUT /api/cases/{id}` and `POST /api/cases/{id}/resolve` have no `changed_by` / `changed_at` trail
10. **`_detect_bipartite` O(N²) nested loop** in `fan_out.py` — will hang on large datasets; needs sparse matrix approach
11. **No alert SLA / aging indicators** — regulatory frameworks require STR within 7–30 days; no countdown or "overdue" flag exists
12. **Alert deduplication is in-memory only** — survives within a server session but not across restarts (blocked by #3 above)
13. **Neo4j ego graph query unbounded** — `MATCH path = (center)-[*1..$radius]-(neighbor)` with radius > 3 can OOM

---

## Files Changed This Session

**Backend Python:**
- `services/detection/ensemble.py`
- `services/detection/structuring.py`
- `services/detection/features.py`
- `services/detection/layering.py`
- `services/detection/dormancy.py`
- `services/detection/profile.py`
- `services/graph/engine.py`
- `api/server.py`
- `infrastructure/database.py`
- `infrastructure/event_bus.py`
- `infrastructure/health.py`
- `services/investigation/case_manager.py`
- `services/investigation/evidence.py`
- `services/ingestion/eod_service.py`
- `services/ingestion/service.py`

**Tests (updated assertions):**
- `tests/test_pipeline_e2e.py`
- `tests/test_incremental_ingestion.py`

**Frontend TypeScript/React:**
- `frontend/src/app/anomaly/page.tsx`
- `frontend/src/app/page.tsx`
- `frontend/src/app/evidence/page.tsx`
- `frontend/src/app/graph/page.tsx`
- `frontend/src/app/patterns/page.tsx`
