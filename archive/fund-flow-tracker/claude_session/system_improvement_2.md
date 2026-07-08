# TraceX Session 3 — System Improvement & Polish
**Date:** 2026-06-30
**Session:** [system_improvement-2]
**Goal:** Stabilize, polish, and make production-ready for banking stakeholder demo

---

## System Architecture (Current State)

### Stack
- **Backend:** FastAPI (Python 3.14) at `api/server.py` → port 8000
- **Frontend:** Next.js 15 + Tailwind + Recharts at `frontend/` → port 3000
- **ML:** XGBoost + Isolation Forest + 6 rule-based detectors in `services/detection/`
- **DB:** SQLite (`data/tracex.db`) via `infrastructure/database.py`
- **Graph:** NetworkX in-memory, Cytoscape.js for rendering

### Key Services
| Service | File | Purpose |
|---|---|---|
| IngestionService | `services/ingestion/service.py` | CSV parsing → accounts_df, txns_df |
| GraphService | `services/graph/engine.py` | NetworkX graph build, BFS, random walk |
| DetectionService | `services/detection/ensemble.py` | Run all 6 detectors + ML scoring |
| InvestigationService | `services/investigation/case_manager.py` | Alert/case management |

### Frontend Pages
| Route | Page | API Endpoints Used |
|---|---|---|
| `/` | Dashboard | `/api/overview` |
| `/ingest` | Data Upload | `/api/ingest/upload`, `/api/ingest/history` |
| `/graph` | Graph Explorer | `/api/graph`, `/api/graph/ego/{id}`, `/api/graph/fund-trail`, `/api/graph/random-walk` |
| `/anomaly` | Investigation Queue | `/api/anomaly` |
| `/patterns` | Pattern Detector | `/api/patterns`, `/api/patterns/first-suspicious/{id}` |
| `/profile` | Profile Analyzer | `/api/profile`, `/api/profile/{id}` |
| `/channels` | Channel Analytics | `/api/channels` |
| `/evidence` | FIU Evidence | `/api/evidence/generate`, `/api/accounts` |

---

## Bugs Fixed This Session

### 1. Dashboard Patterns Column — Always Empty
**File:** `api/server.py` → `get_overview()`
**Bug:** `top_alerts` didn't include detection types per account. The frontend `Patterns` column always showed `—`.
**Fix:** Built `det_types_by_account` map from `detection_svc.detection_results` and added `patterns` field to each alert entry.

### 2. `is_laundering` KeyError in `/api/transactions/filtered`
**File:** `api/server.py` → `get_transactions_filtered()`
**Bug:** Line 1560-1561 tried to filter `txns["is_laundering"]` — this column may not exist after processing (custom CSVs don't have it). Would throw `KeyError`.
**Fix:** Added column existence guard: `if "is_laundering" in txns.columns and is_laundering is not None`.

### 3. TypeScript `Transaction.is_laundering` Type Mismatch
**File:** `frontend/src/lib/api.ts`
**Bug:** `Transaction` interface had `is_laundering: number` but the API removed it from all serialization in Session 2. This caused silent type mismatch.
**Fix:** Removed `is_laundering: number` from Transaction interface.

### 4. Graph Page Right Panel Buttons Don't Load
**File:** `frontend/src/app/graph/page.tsx`
**Bug:** "Focus Ego Graph" / "Trace Funds" / "Find Accomplices" in the right detail panel set state but React async state updates meant `loadGraph()` ran with stale values. The graph never actually updated.
**Fix:** Made each button directly call the API with the known node ID (no React state dependency).

### 5. Anomaly Page "Top Risk Factors" Was a Placeholder
**File:** `frontend/src/app/anomaly/page.tsx`
**Bug:** The "Top Risk Factors" card showed static placeholder text with no interaction path.
**Fix:** Replaced with a live aggregation of the top indicators across the highest-priority accounts in the investigation queue (P1/P2 accounts), showing what's driving the most detections.

### 6. Graph Missing Patterns in Alert Column (API side)
The `detection_types` were built and added to `top_alerts`. Frontend already has the rendering logic (checks `alert.patterns ?? alert.detection_types ?? []`).

---

## What Still Needs Attention (Not Fixed This Session)

From the outstanding list in `backend_improvement.md`:
1. **No authentication** — endpoints open
2. **ML model state lost on restart** — retrains from scratch
3. **Case/alert state lost on restart** — in-memory only
4. **Hardcoded stale FX rates** — Bitcoin mapped to UPI
5. **No alert SLA** — no STR countdown timer
6. **`_detect_bipartite` O(N²)** — slow on large datasets
7. **Neo4j ego graph unbounded** — radius > 3 can OOM

---

## Boot Instructions (Single Machine)

### Prerequisites
- Python 3.14 with `.venv` (already set up in `fund-flow-tracker/`)
- Node.js + npm (for Next.js frontend)
- Dataset in `data/` directory

### Start Backend
```bash
cd /Users/vedansh.kapoor/tracex/TraceX-FinTech/fund-flow-tracker
source .venv/bin/activate
uvicorn api.server:app --host 0.0.0.0 --port 8000 --reload
```

### Start Frontend
```bash
cd /Users/vedansh.kapoor/tracex/TraceX-FinTech/fund-flow-tracker/frontend
npm run dev
```

### Load Demo Data
1. Open http://localhost:3000/ingest
2. Upload `data/tracex_test_day1.csv` (or any IBM AML CSV)
3. Wait for processing (~30-60s)
4. Navigate to Dashboard at http://localhost:3000

---

## Demo User Journey (Banking Stakeholder Walkthrough)

### Step 1: Dashboard (/)
**What to show:** AML command center.
- 6 stat cards (accounts, transactions, flagged, anomalies, critical alerts, total volume)
- Risk distribution pie chart, role distribution bar, patterns detected bar
- Top Alerts table with risk score bars, level badges, roles, and detected patterns
- "Action Required" panel at bottom showing what needs review

**What it means:** "At a glance, our system has processed X transactions, flagged Y accounts, and detected Z suspicious patterns. The red nodes are CRITICAL — they need immediate review."

### Step 2: Pattern Detector (/patterns)
**What to show:** All detected AML typologies.
- Tabs: Layering, Round-Tripping, Structuring, Dormant, Fan-In/Out, Profile Mismatch
- Each tab shows the chain/cycle/accounts involved with INR amounts
- Click "First Suspicious Point Detector" to find when an account first went suspicious

**What it means:** "We detected [N] layering chains — money moved through multiple hops to obscure its source. These are the accounts involved, and the exact amounts at each step."

### Step 3: Graph Explorer (/graph)
**What to show:** Fund flow network visualization.
- Start in Network view (default, shows highest-risk accounts)
- Click any red node → right panel shows details → "Focus Ego Graph" to see all connections
- Switch to Pattern view → select "Round Trip" → see cycle visualized
- Click "Trace Flow" → shows all fund paths from that account
- Click "Find Accomplices" → shows accounts that frequently appear in the same fund flow paths

**What it means:** "This is the money laundering network. Red = critical risk. The arrows show where money flows. The thicker the arrow, the larger the amount."

### Step 4: Anomaly Detection (/anomaly)
**What to show:** Investigation priority queue.
- Stats: total queue, P1 critical, P2 high, speed alerts
- Top Risk Factors panel shows system-wide indicators driving alerts
- Queue table: sorted by priority, shows account, risk score, confidence, role, signals (why flagged), amount
- Speed Alerts: chains where money moved abnormally fast (< 2 min/hop)
- Click any account ID → goes to Graph Explorer focused on that account

**What it means:** "Our P1 accounts need immediate action. These are accounts the system is most confident are involved in money laundering, backed by multiple independent signals."

### Step 5: FIU Evidence (/evidence)
**What to show:** STR report generation.
- Select flagged accounts from the list
- Choose pattern type (Layering, Structuring, etc.)
- Add case notes
- Click "Generate Evidence Pack"
- Download PDF (FIU-IND compliant STR format) and JSON

**What it means:** "Once we've identified suspicious accounts, we can generate an STR directly from the system. The PDF is formatted for submission to FIU-India."

### Step 6: Profile Analyzer (/profile)
**What to show:** Income vs. transaction volume anomalies.
- Scatter plot: each dot is an account; X = declared income, Y = actual volume
- Red dots far above the diagonal = volume >> declared income (suspicious)
- Mismatch table: top accounts by ratio (e.g., 47x their income)
- Peer group search: enter account ID to see how it compares to occupation peers

**What it means:** "A factory worker moving ₹2 Cr when their declared income is ₹4L is a 47x mismatch. This is profile fraud — a major AML red flag."

### Step 7: Channel Analytics (/channels)
**What to show:** Which payment channels are being abused.
- Summary table: volume and count by channel (UPI, NEFT, RTGS, etc.)
- Bar chart of channel usage
- Suspicious channels: channels most used by flagged accounts
- Heatmap: channel usage by hour of day

**What it means:** "Cash and SWIFT are disproportionately used by flagged accounts. This tells us where to focus compliance controls."
