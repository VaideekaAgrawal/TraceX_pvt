# 🏦 TraceX — Fund Flow Tracking & AML Intelligence System

> **"Every rupee leaves a trail. We make it visible."**

**Problem Statement:** PS3 — Tracking of Funds within Bank for Fraud Detection
**Hackathon:** Union Bank of India × iDEA 2.0

TraceX is a graph-first, ML-powered Anti-Money Laundering detection system that ingests bank transaction data, builds a directed multigraph of account relationships, applies 5 custom fraud pattern detectors + ensemble ML (Isolation Forest + XGBoost), and enables investigators to trace fund flows, get AI-generated explanations, and generate FIU-IND evidence packages — live, as transactions stream in.

---

## 🚀 Quick Start — Clone & Run Locally

### Prerequisites

| Tool | Version | Check |
|------|---------|-------|
| Python | 3.10+ | `python --version` |
| Node.js | 18+ | `node --version` |
| npm | 9+ | `npm --version` |
| Git | Any | `git --version` |

### Step 1: Clone the Repository

```bash
git clone https://github.com/VaideekaAgrawal/TraceX-FinTech.git
cd TraceX-FinTech
```

### Step 2: Set Up the Python Backend

```bash
cd fund-flow-tracker

# Create & activate a virtual environment
python -m venv venv
source venv/bin/activate        # Linux/Mac
# venv\Scripts\activate          # Windows CMD
# .\venv\Scripts\Activate.ps1    # Windows PowerShell

# Install dependencies
pip install -r requirements.txt
```

### Step 3: (Optional) Configure AI Explanations

The "Why flagged? (AI)" panels use OpenRouter to generate plain-English explanations. This is optional — the rest of the system works fully without it.

```bash
# fund-flow-tracker/.env
OPENROUTER_API_KEY=your_key_here
OPENROUTER_MODEL=openai/gpt-4o-mini
```

### Step 4: Get Test Data

A ready-to-use sample (`data/tracex_test_day1.csv` — 8,000 transactions, 312 accounts) ships with the repo, so you can start immediately without generating anything.

To also generate the incremental/demo variants used for multi-day testing:

```bash
python scripts/generate_test_pair.py
```

This adds two more CSVs to `data/` (not tracked in git — regenerate locally any time):
- `tracex_test_day2_incremental.csv` — 5,000 transactions (incremental, behavioral shifts)
- `tracex_test_day3_demo.csv` — 6,000 transactions (demo-optimized, all patterns guaranteed)

### Step 5: Start the Backend Server

```bash
uvicorn api.server:app --host 0.0.0.0 --port 8000
```

Verify: open http://localhost:8000/health — you should see `{"status": "ok"}`.

### Step 6: Start the Frontend (new terminal)

```bash
cd fund-flow-tracker/frontend
npm install
npm run dev
```

Open **http://localhost:3000**.

### Step 7: Use the Application

1. Go to the **Ingest** page (`/ingest`)
2. Upload `data/tracex_test_day1.csv`
3. Wait ~8-10 seconds for the full pipeline to run (graph build → feature extraction → ML training → pattern detection → risk scoring)
4. Explore: Dashboard, Graph Explorer, Anomaly Detection, Pattern Detector, Profile Analyzer, Channel Analytics, Real-Time Detection, FIU Evidence

---

## 📊 What Happens When You Upload Data

```
CSV Upload → Parse & Validate → Build Graph (NetworkX MultiDiGraph)
     → Extract 29 Features/Account → Train ML Models (IF + XGBoost)
     → Run 5 Pattern Detectors → Compute Ensemble Risk Scores
     → Classify Roles (SOURCE/MULE/SINK) → Generate Alerts
```

**Pipeline time:** ~8-10 seconds for 6,000 transactions on standard hardware.

---

## 🔍 Features

### 5 Fraud Pattern Detectors

| Detector | What It Finds | Algorithm |
|----------|--------------|-----------|
| **Layering** | Multi-hop chains (A→B→C→D) with amount decay | Temporal chain extraction |
| **Round-Trip** | Circular flows (A→B→A) with ≥85% return | Johnson's cycle detection |
| **Structuring** | Amounts just below ₹10L CTR threshold | Rule + statistical hybrid |
| **Dormancy** | Inactive 180+ days, sudden burst | Gap analysis + burst detection |
| **Profile Mismatch** | Volume vs. declared income anomalies | Z-score + peer comparison |

### ML Pipeline
- **Isolation Forest** — unsupervised anomaly detection (no labels needed)
- **XGBoost** — supervised classifier (GPU/CUDA accelerated, F1=0.206, AUC-ROC=0.778 — measured on the full IBM HI-Small benchmark, 5,078,345 real transactions, 0.48% positive rate; see `docs/METRICS.md` §18)
- **Ensemble Scoring** — ML 30% + Pattern flags 40% + Graph centrality 30%

### Graph Intelligence
- Role Classification (SOURCE / MULE / SINK / NORMAL)
- Fund Trail Tracing (temporal BFS — money only flows forward in time)
- Accomplice Discovery (Random Walk with Restart)
- **Graph Validation Dialog** — evidence-scoped ego-network per account: always shows direct neighbors, only reaches 2 hops out to nodes already implicated in a detected cycle/chain (never a blind BFS), so dense hub accounts stay readable
- Neo4j-style interactive visualization (Cytoscape.js)

### AI & Live Monitoring
- **AI Explanations** — OpenRouter-backed "Why flagged?" panels that turn detection signals into plain-English investigator notes, plus a metrics glossary
- **Live Dashboard Panel** — rolling 60-second transaction/alert counters, event bus queue depth, highest-risk account today
- **Real-Time Detection Demo** — streams transactions over Server-Sent Events to show alerts firing live, not just on batch upload

### Regulatory
- FIU-IND Suspicious Transaction Report generation (PDF + JSON)
- SHA-256 integrity hash for tamper detection
- Case management (create/track/escalate investigations, status workflow)
- Investigation priority queue (P1–P4)

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  FRONTEND — Next.js 16 + React 19 + Cytoscape.js (port 3000)   │
│  Dashboard │ Graph │ Anomaly │ Patterns │ Profile │ Channels    │
│  Real-Time │ Evidence │ Ingest                                  │
├─────────────────────────────────────────────────────────────────┤
│  BACKEND — FastAPI + Uvicorn (port 8000)                        │
│  45+ REST endpoints │ SSE streaming │ Event Bus │ Health Monitor│
├─────────────────────────────────────────────────────────────────┤
│  DETECTION — 5 Detectors + Isolation Forest + XGBoost           │
│  29 features/account │ Ensemble scoring │ Role classification   │
├─────────────────────────────────────────────────────────────────┤
│  GRAPH — NetworkX Directed MultiGraph                           │
│  Cycle detection │ PageRank │ BFS │ Random Walk │ Centrality    │
├─────────────────────────────────────────────────────────────────┤
│  INFRASTRUCTURE — SQLite │ Event Bus │ Config │ Health          │
└─────────────────────────────────────────────────────────────────┘
```

---

## 📁 Project Structure

```
TraceX-FinTech/
├── README.md                          ← You are here
└── fund-flow-tracker/
    ├── api/server.py                  # FastAPI server (45+ endpoints)
    ├── services/
    │   ├── detection/                 # 5 detectors + ML ensemble
    │   ├── graph/                     # NetworkX graph engine
    │   ├── ingestion/                 # CSV/IBM AML parser, EOD ingestion
    │   ├── investigation/             # Case management + evidence
    │   ├── realtime/                  # SSE streaming demo service
    │   ├── monitoring/                # System metrics
    │   ├── validation/                # Data contracts
    │   └── common/                    # Shared models & constants
    ├── infrastructure/                # Config, DB, Event Bus, Health
    ├── frontend/                      # Next.js dashboard (9 pages)
    ├── scripts/
    │   ├── generate_test_pair.py      # Generate test CSVs
    │   ├── download_data.py           # Download IBM AML dataset
    │   ├── ingest_eod.py              # CLI ingestion tool
    │   ├── init_system.py             # CLI initialization
    │   └── validate_ibm_aml.py        # Dataset validation
    ├── tests/                         # Pytest test suite
    ├── data/                          # Datasets (tracex_test_day1.csv tracked; rest gitignored)
    ├── docs/                          # Architecture + submission docs
    ├── Dockerfile                     # Container deployment
    └── requirements.txt               # Python dependencies
```

---

## 🔌 Key API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health`, `/health/live`, `/health/ready` | GET | System health checks |
| `/api/init` | POST | Initialize from a dataset (ibm_aml, paysim, csv) |
| `/api/refresh` | POST | Rebuild graph/detection from existing DB data |
| `/api/ingest/upload` | POST | Upload a CSV (multipart form) |
| `/api/ingest/history`, `/api/ingest/status` | GET | Ingestion history & status |
| `/api/overview` | GET | Dashboard summary |
| `/api/dashboard/live` | GET | Rolling 60s live activity counters |
| `/api/accounts`, `/api/accounts/{id}` | GET | Accounts with risk scores / account detail |
| `/api/explain/account/{id}`, `/api/explain/metric/{name}` | GET | AI-generated explanations |
| `/api/graph`, `/api/graph/filtered` | GET | Network graph (nodes + edges) |
| `/api/graph/ego/{id}`, `/api/graph/validate/{id}` | GET | Ego-network / evidence-scoped validation subgraph |
| `/api/graph/pattern/{type}` | GET | Pattern-specific subgraph |
| `/api/graph/fund-trail`, `/api/graph/random-walk` | POST | Fund trail tracing / accomplice discovery |
| `/api/anomaly` | GET | Anomaly scores + investigation queue |
| `/api/patterns`, `/api/patterns/first-suspicious/{id}` | GET | Detected fraud patterns |
| `/api/profile`, `/api/profile/{id}` | GET | Income/volume mismatch, peer comparison |
| `/api/channels` | GET | Channel analytics |
| `/api/cases`, `/api/cases/{id}` | GET/POST/PUT | Case management + status workflow |
| `/api/evidence/generate` | POST | Generate FIU STR report (PDF + JSON) |
| `/api/realtime/start`, `/api/realtime/stream` | POST/GET (SSE) | Real-time detection demo |
| `/api/transactions/filtered` | GET | Filtered, paginated transactions |

*(Full list of 45+ endpoints is in `api/server.py`.)*

---

## 🧪 Testing

```bash
cd fund-flow-tracker
python -m pytest tests/ -v
```

### Demo Test Accounts (Day 1 CSV — tracked in repo)

| Account | Pattern | Expected |
|---------|---------|----------|
| `STR001AA01` | Structuring | HIGH risk, amounts near ₹10L |
| `RT_SRC_001` / `RT_DST_001` | Round-tripping | Circular flows |
| `LAY_A01` → `LAY_E01` | Layering | 5-hop chain with amount decay |
| `FANOUT_01` | Fan-out | SOURCE role, many recipients |
| `DORM_001` | Dormancy | Quiet, then a sudden burst |

### Demo Test Accounts (Day 3 CSV — generate locally via `generate_test_pair.py`)

| Account | Pattern | What to Look For |
|---------|---------|-----------------|
| `D3_LAY_A1` → `D3_LAY_F1` | Layering | 6-hop chain, 3-8 min/hop, 13% decay |
| `D3_RT_A1` / `D3_RT_B1` | Round-Trip | Bilateral flows, 90-97% return |
| `D3_RT_A3→B3→C3→A3` | 3-Node Cycle | Triangle round-trip |
| `D3_STR01` – `D3_STR04` | Structuring | ₹9.5L–₹9.99L (below ₹10L threshold) |
| `D3_DORM01` – `D3_DORM03` | Dormancy | 200-day gap, then 20+ txns burst |
| `D3_FAN01` – `D3_FAN02` | Fan-Out | SOURCE role, 20-30 recipients |

---

## 🐳 Docker Deployment

```bash
cd fund-flow-tracker
docker build -t tracex .
docker run -p 8000:8000 tracex
```

---

## ⚠️ Known Limitations

- Trained on synthetic + IBM AML public dataset (no real bank data)
- Real-time page is a replay demo over historical data (SSE), not a live production feed
- No authentication on dashboard (acceptable for POC)
- Evidence PDF follows FIU-IND structure but is not legally certified
- AI explanations require an OpenRouter API key; the rest of the system works without one

---

## 👥 Team

| Name | Role |
|------|------|
| Vedansh Kapoor | ML Pipeline & Ensemble |
| Vaideeka Agrawal, Adarsh Panjwani and Shourya Kalbande | Graph Engine & Backend |
| Vaideeka Agrawal and Vedansh kapoor | Frontend & Visualization |
| Vedansh Kapoor, Vaideeka Agrawal, Shourya Kalbande, Adarsh panjwani | Data Engineering & Research |

---

## 📎 Links

- 🎥 **Demo Video:** https://youtu.be/cAunM3vogJA

---

*PS3: Tracking of Funds within Bank for Fraud Detection — Union Bank × iDEA 2.0 Phase 2*
