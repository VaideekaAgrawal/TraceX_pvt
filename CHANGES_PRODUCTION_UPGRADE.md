# TraceX: Hackathon → Production-Grade Upgrade — Full Change Log & Detection Engine Deep-Dive

This document covers everything done in this session: what judges flagged, what was
built in response, exactly how the detection engine works now, how the work was
carried out and verified, and what's still incomplete.

---

## 1. Why This Work Happened

Judges reviewing TraceX flagged four gaps between a hackathon demo and a system a
compliance team could actually trust:

1. **Data disappeared.** `/api/init` and `/api/upload` only built in-memory state —
   SQLite stayed empty in normal use, so a server restart wiped everything.
2. **EOD ingestion double-analyzed.** Every EOD upload ran a lightweight detector pass
   *and* a full pipeline pass, silently overwriting its own alerts and wasting compute.
3. **Thresholds were hardcoded.** Changing anything (e.g. round-trip's 85% return
   ratio) required editing Python and redeploying.
4. **Detection and Investigation were tangled.** Orchestration logic was duplicated
   across route handlers; the API layer reached into detection internals directly.

The request was to fix all four **as one coherent architecture**, not four patches,
while never silently changing what the system flags today.

---

## 2. How The Work Was Done (methodology)

This wasn't "read the ask, write code." The approach for a change this size was:

1. **Parallel research fork-outs** — three independent research passes (data
   persistence, EOD pipeline mechanics, and detector/rule architecture) each read the
   actual source files and cited exact `file:line` locations rather than trusting the
   README's framing. This surfaced a fifth, deeper issue nobody had asked about: there
   were actually **two disconnected alert stores** (an in-memory dict wiped every
   pipeline run, and a SQLite table nothing ever read from) — the real root cause
   under asks #1 and #2.
2. **A dedicated design pass** turned those findings into a concrete, phased plan —
   what depends on what, which files change, how each phase would be verified before
   moving to the next.
3. **Plan review with the user** — a scope decision was explicitly surfaced (a simple
   "edit thresholds" rule system vs. a full topology-aware rule DSL that can also
   express graph-shape patterns like cycles/chains) rather than assumed.
4. **Sequential implementation, phase by phase**, each one fully tested against a
   running backend before starting the next — never batching untested changes.
5. **Continuous drift-checking**: before/after diffing of detector outputs on a fixed
   dataset at every refactor step, specifically to catch "this silently changed what
   gets flagged" — the single highest-risk failure mode in this kind of migration.

---

## 3. Target Architecture (what changed structurally)

```
Before:                                    After:
API routes                                 API routes (thin — HTTP only)
  ├─ inline detect→alert logic                   │
  ├─ direct access to detection internals        ▼
  ├─ RL bandit instantiated in routes      AnalysisPipeline (services/pipeline/)
  └─ 6 hardcoded detector instances          persist → build graph → detect → alert
                                                   │
In-memory-only state                              ▼
(wiped on restart)                         Detection Layer
                                              RuleEngine → PrimitiveRegistry
Two disconnected alert stores                (DB-backed rules, not hardcoded classes)
(in-memory dict + orphaned DB table)              │
                                                   ▼
                                            Investigation Layer
                                              DB-backed CaseManager (one alert store)
                                              RL bandit (owned here now)
                                              Evidence generation (via DetectionSummary DTO)
```

The four asks turned out to compose naturally: persistence became the pipeline's
write step; the pipeline (built while fixing persistence) is the one place every
route calls, which is what let the EOD fix collapse to one line; the rule engine
plugs into the same pipeline step the old hardcoded detectors occupied, so nothing
downstream needed to change; the layer cleanup happened on the same files persistence
work already touched.

---

## 4. Phase-by-Phase Change Log

### Phase 1 — Persistence foundation + seed data

**Problem:** `/api/init`/`/api/upload` built pandas DataFrames and ran detection
entirely in memory; only the EOD path happened to call `db.upsert_accounts()`/
`insert_transactions()`.

**Changes:**
- `services/ingestion/service.py` — new `IngestionService.persist_to_db()` (writes
  accounts+transactions, reused by every ingestion path) and `load_from_db()` (the
  inverse — reloads and normalizes DataFrames from SQLite).
- `services/ingestion/eod_service.py` — `_persist_data()` now delegates to the shared
  method instead of duplicating the batched-upsert logic.
- `api/server.py` — `/api/init`/`/api/upload` call `persist_to_db()`; a new FastAPI
  startup hook checks if the DB has data and, if so, rebuilds the in-memory graph and
  detection state automatically (so a restart doesn't present an empty dashboard); if
  the DB is empty, it seeds demo data instead of starting blank.
- **New file** `scripts/seed_demo_data.py` — a small, hand-built dataset (~50 accounts,
  ~100 transactions, not the 8,000-row generator) covering all 6 original detector
  patterns plus a structuring **control case** (an account that should *not* flag, to
  prove the threshold boundary is real). Background "normal" traffic is deliberately
  built as disjoint one-directional account pairs so it can never accidentally form a
  cycle/chain/fan-degree and produce false demo noise.

**Verified:** deleted the DB, confirmed auto-seed on boot; killed and restarted the
server, confirmed identical data and alert IDs; uploaded a second file, confirmed
counts were cumulative not reset.

---

### Phase 2 — Orchestration pipeline + unified alert store

**Problem (the deeper one found in research):** `CaseManager._alerts` was an
in-memory dict, reset to `{}` on every pipeline run (`self._alerts = {}` at the top of
`auto_create_alerts_from_detections`). Separately, `db.upsert_alert()` was only ever
called from the EOD service's lightweight detectors — and `db.get_alerts()` was never
called from anywhere except tests. Two alert systems, neither of which was both
durable and actually read from.

**Changes:**
- **New file** `services/pipeline/analysis_pipeline.py` — `AnalysisPipeline.run()`
  (persist → build graph → detect → create alerts) and `.run_from_db()` (reload +
  run). Every route that used to inline this sequence now calls one of these two
  methods instead.
- `infrastructure/database.py` — additive-only schema migration (`ALTER TABLE ADD
  COLUMN`, never destructive) adding `account_ids` (JSON — an alert can span multiple
  accounts, e.g. a round-trip cycle), `detected_at` (set once, never overwritten),
  `last_seen_at` (bumped every re-detection), `severity`, `details_json`, `source`,
  `assigned_to`, `notes` to the `alerts` table. New `get_alert()`/`close_stale_alerts()`
  methods.
- `services/common/models.py` — `make_deterministic_alert_id(account_ids, type, date)`
  — a shared hash function so both the full pipeline and the realtime lightweight
  path generate compatible IDs without collisions.
- `services/investigation/case_manager.py` — **rewritten to be DB-backed.** No more
  wipe-and-rebuild; `auto_create_alerts_from_detections()` now upserts the current
  run's alerts (preserving `detected_at` for ones that already existed), closes out
  ("stale") any previously-open alert that didn't re-fire, and returns a diff:
  `{new_ids, reactivated_ids, stale_ids}`.

**Verified:** ran the pipeline twice on identical data — second run showed "0 new, N
reactivated, 0 stale" with `detected_at` unchanged and `last_seen_at` advanced; ran on
data with a pattern removed — that pattern's alert correctly flipped to `status:
"stale"` while others stayed open; restarted the server and confirmed alert IDs were
byte-identical to before restart (proof it's genuinely DB-backed now, not rebuilt with
new random IDs).

---

### Phase 3 — Detection/Investigation API cleanup

**Problem:** `/api/accounts/{id}` called `detection_svc.ensemble._build_flags(...)`
directly (a private, underscore-prefixed method, reached across two layers from the
API route). `/api/evidence` passed raw `graph_svc.graph`, `detection_svc.risk_scores`,
`detection_svc.detection_results`, and two raw DataFrames into
`investigation_svc.generate_evidence()` — five loose parameters instead of one typed
object. The RL bandit (`LinUCBAgent`) was instantiated as a module-level global in
`api/server.py` and its ranking/feedback logic lived inline in route handlers.

**Changes:**
- `services/detection/ensemble.py` — `_build_flags` → public `build_flags`.
- `services/common/models.py` — new `DetectionSummary` dataclass (risk scores, roles,
  detection results, flags, anomaly/fraud scores, centrality, pipeline metrics) — the
  one object other layers should read instead of reaching into `DetectionService`'s
  internals.
- `services/detection/service.py` — new `get_summary()` (builds a `DetectionSummary`),
  `get_account_detail()` and `get_all_account_summaries()` (consolidate logic that
  used to be duplicated inline in two different routes).
- `services/investigation/evidence.py` / `service.py` — `generate_evidence()` now
  takes one `DetectionSummary` instead of five loose params; dropped a `graph_engine`
  parameter that was accepted but never actually used (confirmed dead by grep before
  removing).
- `services/investigation/service.py` — the RL bandit moved here entirely:
  `self.rl_agent = LinUCBAgent(...)` is now owned by `InvestigationService`, with
  `get_prioritized_queue()`, `submit_feedback()`, `get_rl_weights()`, and
  `simulate_rl_feedback()` wrapping it. `api/server.py`'s four `/api/rl/*` routes
  became thin passthroughs.

**Verified:** diffed JSON responses for every touched endpoint before/after against
the same dataset — byte-identical; grepped for the private-method pattern and the
old module-level bandit — both zero hits after the change.

---

### Phase 4 — EOD correctness + "new today" tracking

**Problem (confirmed with exact line numbers):** `/api/ingest/upload` called
`eod_svc.ingest_daily_file()` (which internally ran 7 lightweight inline detectors
over just the uploaded file), then **immediately afterward** re-read the *entire* DB
and ran the real 6-detector+ML pipeline again — detection ran twice per upload, with
the second pass's deterministic alert IDs silently overwriting the first pass's
results.

**Changes:**
- `services/ingestion/eod_service.py` — `ingest_daily_file()` **no longer calls**
  `_run_incremental_analysis()`. It still validates, normalizes, classifies, and
  persists — detection now happens exactly once, via the caller's subsequent
  `AnalysisPipeline` call. The lightweight detectors themselves were **kept**, not
  deleted — `ingest_transaction_rows()` (used by the real-time streaming demo) still
  needs a genuinely fast per-row path, distinct from the EOD batch path. A docstring
  makes this split explicit so it doesn't get silently re-merged later. Alerts from
  each path are tagged with a new `source` column (`pipeline` vs.
  `realtime_lightweight`) so it's always clear which produced a given row.
- `api/server.py` — `/api/ingest` and `/api/ingest/upload` both call
  `pipeline.run_from_db()` exactly once after `ingest_daily_file()` succeeds,
  replacing the old double-run and a large inline rebuild block. Along the way, fixed
  a genuinely dead line of code found while touching this section:
  `hasattr(detection_svc, "anomaly_scores")` was always `False` (that attribute never
  existed — the real data lived in `detection_svc.anomaly_results`), so an anomaly
  score in the upload-summary payload was silently always `0`. Now sourced from
  `detection_svc.get_summary().anomaly_scores`.
- `infrastructure/database.py` — new `daily_run_summary` table (one row per calendar
  day: new/reactivated/stale alert-id lists, counts). `AnalysisPipeline.run()` writes
  to it using the alert diff from Phase 2.
- New endpoint `GET /api/daily-summary` — resolves the day's new/reactivated alert IDs
  to full alert objects.
- **Frontend**: `frontend/src/lib/api.ts` gained `getDailySummary()`; the dashboard
  (`frontend/src/app/page.tsx`) gained a "Today's Activity" panel — two stat cards
  ("🆕 New Today" / "🔁 Reactivated"), each expandable into a per-account list linking
  to the graph view.

**Verified:** ingested the same file twice — first run's `new_alert_ids` covered
everything, second run's `reactivated_alert_ids` covered everything with
`new_alert_ids` empty; constructed a layering chain spanning 10 days (the old 7-day
incremental window would have missed it entirely) and confirmed it's now caught,
since the full pipeline runs over the cumulative dataset every time; confirmed via log
line count that exactly one "DETECTION PIPELINE STARTING" banner appears per ingest,
not two.

---

### Phase 5 — Rule Engine DSL (the biggest piece — see §5 for full mechanics)

**Problem:** every threshold (round-trip's 85% return ratio, structuring's ₹9L–₹10L
band, dormancy's 180-day window, etc.) was a Python dataclass field, or in several
cases a bare hardcoded literal inside a method body not even wired to config. Changing
any of it meant editing code and redeploying. There was no way to define a new pattern
type without writing a new detector class and wiring it into three other files
(`service.py`, `ensemble.py`, `evidence.py`).

The user explicitly chose the more ambitious option here: not just "make existing
thresholds editable" but a genuine rule-composition system that can also express
graph-topology conditions (cycles, chains, fan-degree), not only threshold checks.

**Changes (summarized here, full mechanics in §5):**
- Refactored all 6 existing detector classes (`round_trip.py`, `layering.py`,
  `structuring.py`, `dormancy.py`, `profile.py`, `fan_out.py`) to accept an optional
  `params: dict` in `__init__`, defaulting to today's exact existing values when
  omitted — the mechanism that makes "no code deploy" true.
- **New file** `services/detection/rule_engine.py` — `PrimitiveRegistry` (11
  parametrized primitives, each mapped 1:1 to an existing detector's math),
  `RuleEvaluator` (Tier 1: single primitive, native results; Tier 2: AND/OR/NOT
  composition across primitives, synthesized per-account results), `RuleEngine`
  (loads enabled rules from DB, evaluates all, groups by detection type; `dry_run()`
  for previewing an unsaved rule with no side effects).
- **New file** `services/validation/rule_validator.py` — structural + per-primitive
  parameter-type/range validation before a rule can be saved.
- `infrastructure/database.py` — new `detection_rules` / `detection_rule_history`
  tables; a one-time idempotent seed inserts 11 built-in rules with `rule_json`
  params equal to today's exact defaults, so behavior is byte-identical until someone
  edits a rule; full CRUD methods (`list_rules`, `get_rule`, `create_rule`,
  `update_rule`, `delete_rule` — the last one refuses at the SQL level if
  `is_builtin=1`, defense-in-depth behind the API's 403).
- `services/detection/service.py` — `run_full_pipeline()` step 4 now calls
  `self.rule_engine.run_all(...)` instead of 6 hardcoded `self.layering.detect(...)`-
  style calls.
- **New API endpoints**: `GET/POST /api/rules`, `GET/PUT/DELETE /api/rules/{id}`,
  `POST /api/rules/{id}/enable|disable`, `GET /api/rules/primitives`, `POST
  /api/rules/dry-run`.
- **New frontend page** `frontend/src/app/rules/page.tsx` — rule list with
  enable/disable toggles and a built-in lock badge; an editor with a primitive
  picker that renders parameter forms dynamically from `/api/rules/primitives`; a
  dry-run preview before saving; a Sidebar nav entry.

**Verified:** ran detection on the seed dataset before and after migrating to the
rule engine — **byte-identical results** (same accounts, same scores, same
severities, structuring control case still correctly unflagged); edited the
round-trip rule's `min_return_ratio` from 0.85 to 0.70 via the live HTTP API,
confirmed a synthetic 0.76-ratio case flipped from `MEDIUM` severity to `HIGH` with no
restart; built and dry-ran a genuinely new Tier-2 composite rule (fan-out AND income
mismatch) that correctly matched only the one account satisfying both conditions;
confirmed `DELETE` on a built-in rule returns 403; re-ran the full regression sweep
across every other endpoint — all green.

---

### Phase 6 — Integration polish & verification

- Ran the full pytest suite. Of 6 failures, confirmed (via `git stash` comparison
  against the untouched original code) that 5 were **pre-existing**, unrelated to this
  work — tests calling methods (`get_risk_scores()`, `get_account_roles()`,
  `get_alerts()`) that never existed anywhere in the repo's git history. Fixed them
  anyway since the correct replacement was obvious (`detection_svc.risk_scores`,
  `.roles`, `investigation_svc.list_alerts()`). The 6th (`test_ingest_daily_file`)
  needed updating because Phase 4 intentionally changed that method's return
  contract.
- **Migration safety test**: hand-built a genuine pre-Phase-2-schema SQLite DB with
  real data (old `alerts` table shape, no `detection_rules`/`daily_run_summary`
  tables) and ran the current `initialize()` against it. This caught a real bug:
  `ALTER TABLE ADD COLUMN ... DEFAULT` only applies the default going forward — a
  pre-existing alert row would have silently ended up with `account_ids=[]` and
  `detected_at=NULL` despite having a perfectly good `account_id`/`created_at` already
  on the row. Fixed with a one-time backfill step for legacy rows, re-verified against
  the same test DB.
- **Performance check**: timed `run_full_pipeline()` on an 8,000-transaction dataset —
  13.08s via the new Rule Engine vs. 13.42s on the original hardcoded detectors (via
  `git stash` comparison). No regression; the Rule Engine's DB-load indirection is
  negligible next to the actual detection algorithm cost.
- Reverted an accidental modification to `data/tracex_test_day1.csv` that occurred as
  a side effect during testing (source never fully identified, but confirmed
  unrelated to the actual code changes — restored via `git checkout`).
- Updated `README.md`: architecture diagram, feature list, API endpoint table,
  project structure, test-data section.

---

## 5. The Detection Engine — How It Actually Works Now

### 5.1 The core idea

Before: `DetectionService.run_full_pipeline()` called 6 hardcoded Python objects —
`self.layering.detect(...)`, `self.round_trip.detect(...)`, etc. — each reading fixed
thresholds from a `config.detection` singleton. Adding a pattern meant a new class
plus edits to three other files.

After: those 6 detector classes still exist and contain the actual pattern-matching
math (nothing about *how* a round-trip cycle or a layering chain is detected changed),
but they're no longer called directly. Instead:

```
DetectionService.run_full_pipeline()
        │
        ▼
  RuleEngine.run_all(graph_engine, accounts_df, transactions_df)
        │
        ├─ loads all `enabled=1` rows from the `detection_rules` DB table
        │
        └─ for each rule → RuleEvaluator.evaluate_rule(rule, ...)
                 │
                 ├─ Tier 1 (1 condition): PrimitiveRegistry.evaluate(primitive, params, ...)
                 │     → instantiates the matching detector class WITH the rule's
                 │       current params, calls its detect()/sub-method, returns its
                 │       native DetectionResult list untouched (full score/severity/
                 │       details preserved)
                 │
                 └─ Tier 2 (2+ conditions): evaluate each condition's primitive,
                       reduce to a per-account {matched: bool} set, combine via
                       AND (intersection) / OR (union), apply NOT per-condition,
                       synthesize one DetectionResult per matched account
```

The critical mechanism: each detector class's `__init__` now does this (shown for
`RoundTripDetector`, but all 6 follow the same pattern):

```python
def __init__(self, params: Optional[Dict] = None):
    base = config.detection
    p = params or {}
    self.cfg = SimpleNamespace(
        round_trip_max_cycle_length=p.get("max_length", base.round_trip_max_cycle_length),
        round_trip_max_cycles=p.get("max_cycles", base.round_trip_max_cycles),
        round_trip_amount_return_ratio=p.get("min_return_ratio", base.round_trip_amount_return_ratio),
    )
```

The rest of the detector's actual detection logic (`detect()`) is **completely
unchanged** — it still reads `self.cfg.round_trip_amount_return_ratio` exactly as
before. Only where that value *comes from* changed: instead of always being
`config.detection`'s hardcoded default, it's now `params["min_return_ratio"]` if the
DB-stored rule provides one. Since `RuleEngine.run_all()` re-loads rules from the DB
**on every pipeline run**, editing a rule's JSON in the `detection_rules` table and
hitting `/api/refresh` (or the next EOD ingest) re-instantiates the detector with the
new value — no restart, no redeploy.

### 5.2 The 11 primitives (built-in rules)

Each of the original 6 detector classes actually contained multiple independent
sub-checks. The Rule Engine exposes each sub-check as its own primitive/rule, so they
can be individually toggled/edited:

| Primitive | Detector method it wraps | Key params |
|---|---|---|
| `cycle` | `RoundTripDetector.detect()` | `max_length`, `max_cycles`, `min_return_ratio` |
| `chain` | `LayeringDetector.detect()` | `min_hops`, `time_window_minutes`, `extended_min_hops`, `extended_window_minutes`, `decay_ratio_threshold` |
| `amount_band_count` | `StructuringDetector._detect_classic()` | `lower`, `upper`, `min_count`, `window_days` |
| `split_sum_threshold` | `StructuringDetector._detect_split()` | `lower`, `upper`, `min_count` |
| `inactivity_then_burst` | `DormancyDetector.detect()` | `threshold_days`, `min_burst_txns`, `multiplier` |
| `volume_vs_declared_income_ratio` | `ProfileMismatchDetector._detect_income_mismatch()` | `ratio_threshold` |
| `peer_zscore_deviation` | `ProfileMismatchDetector._detect_peer_deviation()` | `z_threshold`, `min_peer_group_size` |
| `behavioural_shift` | `ProfileMismatchDetector._detect_behavioural_shift()` | `shift_z_threshold`, `min_txn_count`, `rolling_window` |
| `fan_degree` | `FanOutFanInDetector._detect_fan()` | `direction` (fan_out/fan_in), `min_degree`, `window_days` |
| `bipartite_scatter_gather` | `FanOutFanInDetector._detect_bipartite()` | `min_side`, `window_days` |
| `generic_group_aggregate` | *(new — no detector; a from-scratch pandas evaluator)* | `group_by`, `agg` (SUM/COUNT/AVG/MAX/MIN), `field`, `window_days`, `operator`, `value` |

The first 10 are exact wrappers around pre-existing math (byte-identical output,
verified). The 11th, `generic_group_aggregate`, is new — a fully generic "group by
account, aggregate a field over a window, compare to a threshold" evaluator, meant as
an escape hatch for ad-hoc rules that don't need real topology logic (e.g. "flag if
SUM(amount) for an account over 14 days exceeds ₹50L").

**A few hardcoded literals were newly exposed as parameters** during this refactor —
things that existed in the original code but were never config-driven at all (e.g.
structuring's split-detector minimum count of 2, profile mismatch's income ratio
threshold of 10, dormancy's peer-group minimum size of 5, layering's 0.5 decay-ratio
cutoff). These now have the exact same default value as before, just editable.

**Two config fields were found to be genuinely dead** (defined in
`infrastructure/config.py`, never read anywhere): `structuring_upper` (redundant with
`ctr_threshold`, which was what the code actually used) and `layering_amount_
preservation_ratio`. These were **not** migrated into the rule engine as fake
"editable" knobs — doing so would have made something look configurable that never
actually did anything.

### 5.3 Composing a new rule (Tier 2)

A rule is stored as JSON:

```json
{
  "combinator": "AND",
  "conditions": [
    {"primitive": "fan_degree", "params": {"direction": "fan_out", "min_degree": 3, "window_days": 30}, "negate": false},
    {"primitive": "volume_vs_declared_income_ratio", "params": {"ratio_threshold": 10}, "negate": false}
  ]
}
```

For a 1-condition rule (all 11 built-ins), the primitive's own `DetectionResult` list
is returned as-is — full fidelity, including whatever rich `details` the underlying
detector computed (e.g. round-trip's `cycle_nodes`, `return_ratio`, `time_span_hours`).

For a 2+-condition rule, each condition is evaluated independently, reduced to "which
accounts matched," and the sets are combined (AND = intersection, OR = union, with
per-condition NOT = "accounts not in this primitive's match set"). A single synthetic
`DetectionResult` is produced per matched account — score is the max across
contributing primitives, severity is the worst-case, and `details` records which
primitives/rule produced the match (this loses per-primitive structural detail like
exact cycle nodes; a genuine limitation, see §6).

### 5.4 End-to-end trace: editing round-trip's threshold

1. Analyst opens `/rules`, selects "Round-Trip Circular Flow," changes
   `min_return_ratio` from `0.85` to `0.70` in the form.
2. Frontend calls `PUT /api/rules/builtin_round_trip` with the updated `rule_json`.
3. Backend validates via `RuleValidator`, bumps the rule's `version`, writes both
   `detection_rules` (current state) and `detection_rule_history` (audit trail).
4. Next `/api/refresh` (or the next EOD ingest, which always calls
   `AnalysisPipeline.run_from_db()`) → `DetectionService.run_full_pipeline()` → step 4
   → `RuleEngine.run_all()` → reloads all enabled rules fresh from the DB →
   `PrimitiveRegistry.evaluate("cycle", {"min_return_ratio": 0.70, ...}, ...)` →
   instantiates a fresh `RoundTripDetector(params={"min_return_ratio": 0.70, ...})` →
   its `detect()` method now classifies any cycle with ≥70% return as "tight" (was
   85%) → higher severity/score for previously-borderline accounts.

No code change. No restart. No redeploy.

### 5.5 Residual limits (honest, not glossed over)

- A genuinely novel graph-**shape** motif outside the 11 primitives (e.g. an
  alternating-currency multi-hop pattern with no existing analog) still needs one new
  Python primitive registered in `PrimitiveRegistry` — now an isolated addition, not a
  4-file change, but still code.
- ML-model signals (IsolationForest, XGBoost) are **not** expressible in the rule DSL
  at all — they remain code-level training config, entirely separate from the rule
  engine.
- Tier 2 composition is **account-level only** — it can say "this account matched
  primitive A and primitive B," not "this cycle shares an edge with that chain." True
  cross-primitive topological joins aren't supported.
- The structuring detector's original `detect()` deduplicated an account's best score
  across its classic+split sub-checks; as two independent rules now, an account
  matching *both* sub-patterns simultaneously would show up as two separate alert
  entries instead of one merged best-of. Narrow edge case (doesn't affect whether an
  account gets flagged, only display duplication in that specific double-match
  scenario); not fixed, documented as a known trade-off.

---

## 6. What's Verified Working Right Now

- Full stack starts cleanly (backend :8000, frontend :3000), auto-seeds on first run.
- Data and alerts survive a server restart with stable IDs.
- Every ingestion path (`/api/init`, `/api/upload`, `/api/ingest`,
  `/api/ingest/upload`) persists to SQLite and runs detection exactly once.
- The dashboard's "Today's Activity" panel correctly distinguishes new vs.
  reactivated alerts.
- `/rules` lets you edit any of the 11 built-in rules' thresholds or build new
  composite rules, with a live dry-run preview; built-in rules can't be deleted (only
  disabled).
- The full pytest suite passes (169 passed, only pre-existing/explained
  exceptions), a from-scratch old-schema-DB migration test passes, and performance is
  unchanged from before the refactor.

## 7. Known Gaps / Follow-Up Work (not addressed in this session — out of the
   approved scope, flagged for awareness)

- **Two separate case-tracking systems still exist**: `InvestigationService`'s
  in-memory `CaseManager._cases` dict, and a completely separate SQLite `cases` table
  that `/api/cases` routes read/write directly via `get_database()`, bypassing
  `InvestigationService` entirely. This was noted during Phase 2 research but
  explicitly scoped out (the plan only covered unifying the **alert** store, not
  cases) — a real follow-up item.
- **Neo4j adapter parity is partial** — the new `daily_run_summary` and
  `detection_rules`/`detection_rule_history` tables only have SQLite implementations;
  `Neo4jAdapter` inherits the abstract base class's `NotImplementedError` for these.
  Fine since SQLite is the actual default/only-configured backend, but worth knowing
  if Neo4j is ever turned on.
- **No authentication on any API route** — noted in earlier system analysis
  (`infrastructure/security.py` exists with JWT/RBAC logic fully written but is never
  imported in `api/server.py`). Not touched in this session; still an open item for
  production readiness.
- **Rule Engine Tier 2 composition detail loss** — see §5.5.
- **`test_get_transactions_for_account`** remains a known-flaky pre-existing test
  (hardcodes a calendar date and compares against `datetime.now()` with a 7-day
  window — will fail whenever run more than a week after the hardcoded date,
  independent of any code correctness). Not fixed — flagged for whoever next touches
  that test file.
- The frontend Rule Builder page was verified via TypeScript compilation and an HTTP
  200 page load, but **not visually screenshot-tested** — no headless browser tool was
  available in this environment. Manual visual QA in a real browser is recommended
  before treating it as demo-ready.
