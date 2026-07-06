# 🏦 TraceX — AML Intelligence System

> **"Every rupee leaves a trail. We make it visible."**

Graph-first, ML-powered, law-enforcement-ready Anti-Money Laundering detection system.

---

## Quick Start

### Prerequisites
- Python 3.10+
- Node.js 18+
- npm

### Backend (FastAPI)
```bash
cd fund-flow-tracker
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

pip install -r requirements.txt
uvicorn api.server:app --host 0.0.0.0 --port 8000
```

### Frontend (Next.js)
```bash
cd fund-flow-tracker/frontend
npm install
npm run dev          # http://localhost:3000
```

### Test Data
The backend auto-seeds a small curated dataset on first run if the database is empty
(covers every detection rule plus a structuring control case) — the dashboard won't be
blank on a fresh install. For a larger demo, `data/tracex_test_day1.csv` (8,000
transactions, 312 accounts) ships in the repo — upload it via `/ingest` to layer on
more data.

To generate the incremental/demo variants (not tracked in git):
```bash
cd fund-flow-tracker
python scripts/generate_test_pair.py
```
This adds two more CSVs in `data/`:
- `tracex_test_day2_incremental.csv` — 5000 transactions (incremental with behavioral shifts)
- `tracex_test_day3_demo.csv` — 6000 transactions (demo-optimized, all patterns guaranteed)

### AI Explanations (optional)
"Why flagged? (AI)" panels use OpenRouter. Add to `fund-flow-tracker/.env`:
```
OPENROUTER_API_KEY=your_key_here
OPENROUTER_MODEL=openai/gpt-4o-mini
```
Everything else works without this.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Next.js Frontend (port 3000)                       │
│  Dashboard │ Graph Explorer │ Anomaly │ Patterns │ Profile │ Channels │
│  Real-Time │ Evidence │ Ingest                                        │
├─────────────────────────────────────────────────────────────────────┤
│                    FastAPI Backend (port 8000)                        │
│  /api/init │ /api/graph │ /api/anomaly │ /api/patterns │ /api/ingest │
│  /api/dashboard/live │ /api/explain │ /api/realtime (SSE)             │
├─────────────────────────────────────────────────────────────────────┤
│         Orchestration (AnalysisPipeline: persist → graph → detect →  │
│                         alert, one path for every ingestion route)   │
├─────────────────────────────────────────────────────────────────────┤
│                    Microservice Layer                                 │
│  Ingestion │ Graph (NetworkX) │ Detection (Rule Engine + ML) │ Inv.  │
├─────────────────────────────────────────────────────────────────────┤
│                    Infrastructure                                     │
│  Event Bus │ Health Monitor │ Config │ SQLite DB (always-on, the     │
│  single source of truth — survives restarts, auto-seeds if empty)    │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Features

### Detection — Rule Engine (DB-backed, no code deploy to edit)
Every pattern below is a **rule** in the `/rules` UI, not a hardcoded detector — edit
any threshold (e.g. round-trip's 85% return ratio) or compose new patterns from
primitives with AND/OR, and it takes effect on the next refresh/ingest.

| Rule | What It Finds |
|----------|--------------|
| **Layering** | Multi-hop chains (A→B→C→D) with amount decay |
| **Round-Trip** | Circular flows (A→B→A) with a configurable amount-return ratio |
| **Structuring** (2 rules) | Amounts just below ₹10L CTR threshold — classic + split-daily-total |
| **Dormancy** | Accounts inactive 6+ months, suddenly active |
| **Profile Mismatch** (3 rules) | Income vs. volume ratio, peer-group z-score deviation, sudden behavioural shift |
| **Fan-Out / Fan-In / Bipartite** | Hub-and-spoke dispersal, consolidation, and scatter-gather structures |

Plus a `generic_group_aggregate` primitive as an escape hatch for ad-hoc new rules
(group-by-account aggregation over a threshold) with no new Python at all.

### ML Pipeline
- **Isolation Forest** — unsupervised anomaly detection (no labels needed)
- **XGBoost** — supervised classification (trains on `is_laundering` labels, GPU/CUDA supported)
- **Ensemble Scoring** — ML 30% + Pattern flags 40% + Graph centrality 30%

### Graph Intelligence
- **Role Classification** — SOURCE / MULE / SINK / NORMAL
- **Fund Trail Tracing** — Follow money through the network
- **Random Walk** — Find accomplices via PageRank
- **Pattern Subgraphs** — Neo4j-style visualization of flagged networks
- **Graph Validation Dialog** — evidence-scoped ego-network (direct neighbors always shown, 2-hop reach limited to nodes already implicated in a detected cycle/chain) so hub accounts stay readable

### AI & Live Monitoring
- **AI Explanations** — OpenRouter-backed "Why flagged?" panels + metrics glossary
- **Live Dashboard Panel** — rolling 60s transaction/alert counters, event bus depth
- **Real-Time Detection Demo** — SSE stream showing alerts firing live over replayed transactions

### Regulatory
- **FIU-IND Evidence Packs** — one-click STR report (PDF + JSON)
- **Case Management** — create/track/escalate investigations, status workflow
- **Investigation Priority Queue** — P1-P4 ranking

### Persistence & Operations
- **Always-on SQLite** — every ingestion path (init/upload/EOD) persists to the DB; a
  server restart or browser refresh rebuilds in-memory state from it automatically
- **Auto-seed on first run** — a fresh install seeds a small curated dataset covering
  every rule (plus a structuring control case) instead of starting blank
- **Today's Activity** — the dashboard distinguishes patterns flagged for the first
  time today from ones still active/re-detected, backed by a per-day run summary
- **Single detection run per EOD ingest** — the full rule set runs once over the
  cumulative dataset per ingest, not a lightweight pass followed by a duplicate full pass

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | System health |
| `/api/init` | POST | Initialize from dataset (ibm_aml, paysim, csv) |
| `/api/refresh` | POST | Rebuild from DB data |
| `/api/ingest/upload` | POST | Upload CSV (multipart form) |
| `/api/ingest/history` | GET | Ingestion history |
| `/api/overview` | GET | Dashboard summary |
| `/api/graph` | GET | Network graph (nodes + edges) |
| `/api/graph/ego/{id}` | GET | Ego-network for account |
| `/api/graph/pattern/{type}` | GET | Pattern-specific subgraph |
| `/api/graph/fund-trail` | POST | Fund flow trail |
| `/api/graph/random-walk` | POST | Find accomplices |
| `/api/anomaly` | GET | Anomaly scores + investigation queue |
| `/api/patterns` | GET | Detected fraud patterns |
| `/api/profile` | GET | Income/volume mismatch data |
| `/api/channels` | GET | Channel analytics |
| `/api/accounts` | GET | All accounts with risk scores |
| `/api/accounts/{id}` | GET | Account detail + features |
| `/api/graph/validate/{id}` | GET | Evidence-scoped validation subgraph |
| `/api/dashboard/live` | GET | Rolling 60s live activity counters |
| `/api/explain/account/{id}` | GET | AI-generated "why flagged" explanation |
| `/api/explain/metric/{name}` | GET | AI-generated metric glossary entry |
| `/api/cases` | GET/POST | Case management |
| `/api/cases/{id}/status` | PUT | Update case status |
| `/api/realtime/start` / `/api/realtime/stream` | POST / GET (SSE) | Real-time detection demo |
| `/api/transactions/filtered` | GET | Filtered, paginated transactions |
| `/api/evidence/generate` | POST | Generate FIU STR report |
| `/api/daily-summary` | GET | New-vs-reactivated alerts as of the latest pipeline run |
| `/api/rules` | GET/POST | List / create detection rules |
| `/api/rules/{id}` | GET/PUT/DELETE | Get / edit / delete a rule (built-ins can't be deleted) |
| `/api/rules/{id}/enable` / `/disable` | POST | Toggle a rule |
| `/api/rules/primitives` | GET | Primitive catalog + param schemas (drives the `/rules` UI) |
| `/api/rules/dry-run` | POST | Preview a draft rule's impact with no side effects |

*(50+ endpoints total — see `api/server.py` for the full list.)*

---

## Project Structure

```
fund-flow-tracker/
├── api/
│   └── server.py             # FastAPI server (all endpoints)
├── services/
│   ├── pipeline/               # AnalysisPipeline — persist → graph → detect → alert
│   ├── ingestion/              # Data parsing (IBM AML, CSV, EOD)
│   ├── graph/                  # NetworkX graph engine
│   ├── detection/              # Detectors + Rule Engine (rule_engine.py) + ensemble ML
│   ├── investigation/          # Cases, alerts (DB-backed), evidence, RL queue
│   ├── monitoring/             # System metrics
│   ├── validation/             # Data contracts + rule_validator.py
│   └── common/                 # Shared models & constants
├── infrastructure/
│   ├── config.py               # System configuration (legacy defaults; rules now DB-backed)
│   ├── database.py             # SQLite adapter (accounts/txns/alerts/rules/daily summaries)
│   ├── event_bus.py            # Pub/sub event bus
│   └── health.py                # Health checkpoints
├── frontend/
│   └── src/
│       ├── app/                # Next.js pages (dashboard, graph, rules, etc.)
│       ├── components/         # UI components (CytoscapeGraph, etc.)
│       └── lib/                # API client, utilities
├── scripts/
│   ├── seed_demo_data.py       # Small curated seed dataset (auto-run if DB is empty)
│   ├── generate_test_pair.py   # Generate Day1 + Day2 test CSVs
│   ├── download_data.py        # Download IBM AML dataset
│   ├── ingest_eod.py           # CLI ingestion tool
│   └── init_system.py          # Initialize system from CLI
├── data/                      # tracex_test_day1.csv tracked; other CSVs gitignored (regenerate locally)
├── tests/                     # Pytest test suite
├── utils/                     # Domain constants
├── docs/                      # Architecture docs
├── Dockerfile                 # Container deployment
└── requirements.txt           # Python dependencies
```

---

## Testing

### Run Test Suite
```bash
python -m pytest tests/ -v
```

### Manual Testing Flow
1. Start backend + frontend (see Quick Start)
2. Open http://localhost:3000/ingest
3. Upload `data/tracex_test_day1.csv` (ships in the repo) → explore all pages
4. (Optional) `python scripts/generate_test_pair.py`, then upload `data/tracex_test_day2_incremental.csv` (check "Force re-process") → watch risk scores change

### Key Test Accounts
| Account | Pattern | Expected |
|---------|---------|----------|
| `STR001AA01` | Structuring | HIGH risk, amounts near ₹10L |
| `RT_SRC_001` | Round-tripping | Circular flows with `RT_DST_001` |
| `LAY_A01→LAY_E01` | Layering | 5-hop chain with amount decay |
| `FANOUT_01` | Fan-out | SOURCE role, many recipients |
| `DORM_001` | Dormancy | Quiet Day1, burst Day2 |
| `SHIFT_001` | Behavioral shift | Clean Day1 → Dirty Day2 |
| `VELO_001` | Velocity spike | 20+ transactions in 30 minutes |

---

## Graph Legend

| Symbol | Meaning |
|--------|---------|
| 🔴 Red node | CRITICAL risk (76-100) |
| 🟠 Orange node | HIGH risk (51-75) |
| 🟡 Yellow node | MEDIUM risk (26-50) |
| 🟢 Green node | LOW risk (0-25) |
| △ Triangle | SOURCE (sends money out) |
| ◇ Diamond | MULE (passes money through) |
| ▽ Inverted triangle | SINK (receives money) |
| ○ Circle | NORMAL account |
| Node size | Proportional to risk score |
| Edge thickness | Proportional to transaction amount |

---

## Data Sources

| Source | Description |
|--------|-------------|
| **IBM AML** | 5M+ transactions, 5,100 labelled laundering cases |
| **Custom CSV** | Upload any CSV with timestamp, source, dest, amount |
| **Generated** | Synthetic test data with embedded patterns |

---

## Deployment

```bash
# Docker
docker build -t tracex .
docker run -p 8000:8000 tracex
```

---

## License

Research & educational use. IBM AML dataset: CDLA Sharing 1.0.
