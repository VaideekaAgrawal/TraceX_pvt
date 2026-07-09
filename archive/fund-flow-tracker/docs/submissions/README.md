# TraceX — Fund Flow Tracking & AML Intelligence System

> **"Every rupee leaves a trail. We make it visible."**

Graph-first, ML-powered, law-enforcement-ready Anti-Money Laundering detection system for **PS3: Tracking of Funds within Bank for Fraud Detection** — Union Bank of India × iDEA 2.0 Hackathon.

---

## Problem Statement

This project addresses **PS3: Tracking of Funds within Bank for Fraud Detection**. TraceX ingests bank transaction data, builds a real-time directed multigraph of account relationships, applies 5 custom fraud pattern detectors + ensemble ML (Isolation Forest + XGBoost), and provides investigators with interactive graph visualizations and auto-generated FIU-IND Suspicious Transaction Reports (STR).

---

## Live Demo

🔗 **Live App:** Run locally (instructions below)  
🎥 **Demo Video:** [YouTube - Unlisted Link]  
🎥 **Pitch Video:** [YouTube - Unlisted Link]  
📂 **Repository:** [GitHub Link]

---

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Backend API** | FastAPI 0.104+ / Uvicorn | REST API server with 25+ endpoints |
| **ML — Unsupervised** | Scikit-learn (Isolation Forest, n=200, contamination=5%) | Baseline anomaly detection without labels |
| **ML — Supervised** | XGBoost 2.0+ (GPU/CUDA RTX 3060) | Fraud probability classification (PR-AUC 0.64, F1 0.683) |
| **Graph Engine** | NetworkX (Directed MultiGraph) | Transaction graph, cycle detection, PageRank, Random Walk |
| **Frontend** | Next.js 16 + React 19 + Tailwind CSS | 8-page investigator dashboard |
| **Graph Visualization** | Cytoscape.js | Neo4j-style interactive graph rendering |
| **PDF Generation** | FPDF2 | FIU-IND STR evidence packages |
| **Database** | SQLite (WAL mode) / Neo4j (production) | Transaction & account persistence |
| **Event System** | Custom pub/sub event bus (Kafka-pattern) | Decoupled pipeline orchestration |
| **Data Processing** | Pandas 2.0 + NumPy | Vectorised feature extraction (29 features/account) |
| **Testing** | Pytest + pytest-asyncio + httpx | Unit, integration, smoke, regression tests |
| **CI/CD** | GitHub Actions | Automated test pipeline |
| **Containerisation** | Docker | Production deployment |

---

## How to Run Locally

### Prerequisites
- Python 3.10+ (3.11 recommended)
- Node.js 18+
- npm 9+
- (Optional) NVIDIA GPU with CUDA for accelerated XGBoost

### Step 1: Clone the Repository
```bash
git clone https://github.com/your-team/TraceX-FinTech.git
cd TraceX-FinTech/fund-flow-tracker
```

### Step 2: Setup Python Environment
```bash
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate
pip install -r requirements.txt
```

### Step 3: Generate Test Data
```bash
python scripts/generate_test_pair.py
```
This creates two realistic test CSVs:
- `data/tracex_test_day1.csv` — 8,000 transactions across 312 accounts (Day 1 initial batch)
- `data/tracex_test_day2_incremental.csv` — 5,000 transactions (Day 2 incremental with behavioural shifts)

### Step 4: Start the Backend
```bash
uvicorn api.server:app --host 0.0.0.0 --port 8000
```
Backend runs at `http://localhost:8000`. Health check: `GET /health`

### Step 5: Start the Frontend (separate terminal)
```bash
cd frontend
npm install
npm run dev
```
Frontend runs at `http://localhost:3000`

### Step 6: Ingest Data & Explore
1. Open `http://localhost:3000/ingest`
2. Upload `data/tracex_test_day1.csv`
3. System automatically: parses CSV → builds graph → extracts 29 features/account → runs IF + XGBoost → detects 5 fraud patterns → assigns risk scores → classifies roles
4. Explore Dashboard, Graph Explorer, Anomaly, Patterns, Profile, Evidence pages
5. Upload `data/tracex_test_day2_incremental.csv` to see incremental detection (dormancy, behavioural shifts)

---

## Project Structure

```
fund-flow-tracker/
├── api/
│   └── server.py                  # FastAPI server — 25+ endpoints
├── services/
│   ├── detection/
│   │   ├── layering.py            # Multi-hop chain detector (min 3 hops, 30-min window)
│   │   ├── round_trip.py          # Circular flow detector (Johnson's algorithm)
│   │   ├── structuring.py         # CTR threshold avoidance (₹9L–₹10L range)
│   │   ├── dormancy.py            # Dormant account reactivation (180-day threshold)
│   │   ├── profile.py             # Behavioural baseline + z-score deviation
│   │   ├── ensemble.py            # IsolationForest + XGBoost + ensemble scoring
│   │   └── features.py            # 29-feature vectorised extractor
│   ├── graph/
│   │   └── engine.py              # NetworkX MultiDiGraph, PageRank, BFS, RWR
│   ├── ingestion/
│   │   ├── parser.py              # IBM AML / PaySim / Custom CSV auto-detection
│   │   └── eod_service.py         # Daily incremental ingestion + 7-day rolling window
│   ├── investigation/
│   │   ├── case_manager.py        # Case lifecycle (OPEN → ESCALATED → CLOSED)
│   │   └── evidence.py            # FIU-IND STR PDF + JSON + SHA-256 integrity
│   ├── monitoring/                # System metrics & health
│   ├── validation/                # Data contracts & schema enforcement
│   └── common/                    # Shared models, constants, enums
├── infrastructure/
│   ├── config.py                  # Centralized system configuration (dataclass)
│   ├── database.py                # Adapter pattern: SQLite ↔ Neo4j
│   ├── event_bus.py               # Topic-based pub/sub (Kafka semantics)
│   └── health.py                  # 8 health checkpoints (CP-01 to CP-08)
├── frontend/
│   └── src/
│       ├── app/                   # Next.js App Router (8 pages)
│       ├── components/            # CytoscapeGraph, charts, tables
│       └── lib/                   # API client, types, utilities
├── scripts/
│   ├── generate_test_pair.py      # Synthetic test data with embedded fraud patterns
│   ├── download_data.py           # IBM AML dataset downloader (Kaggle)
│   ├── ingest_eod.py              # CLI daily ingestion tool
│   ├── init_system.py             # CLI system initialization
│   └── run_pipeline.py            # Full pipeline orchestrator
├── tests/
│   ├── test_core.py               # Unit tests (helpers, graph, loaders)
│   ├── test_ingestion.py          # DB adapter + EOD service tests
│   ├── test_reliability.py        # Data contract validation + label leakage guards
│   └── test_smoke_pipeline.py     # End-to-end regression (AUC≥0.88, PR-AUC≥0.60)
├── data/                          # Datasets (gitignored, generated locally)
├── docs/                          # Architecture & submission documents
├── .github/workflows/ci.yml       # GitHub Actions CI pipeline
├── Dockerfile                     # Container deployment
└── requirements.txt               # Python dependencies (19 packages)
```

---

## Dataset

### Primary: IBM Anti-Money Laundering Dataset (Kaggle)
- **Size:** 5,016,335 transactions across 517,037 accounts
- **Labels:** 5,100 confirmed laundering transactions (is_laundering=1)
- **Patterns:** 8 laundering typologies including fan-in/fan-out, scatter-gather, cycle
- **License:** CDLA Sharing 1.0
- **Download:** `python scripts/download_data.py`

### Testing: Custom Synthetic Generator
- All test data is **100% synthetic**, generated by our team
- Embeds known fraud patterns at controlled rates for validation
- Named test accounts allow deterministic verification (e.g., `STR001AA01` for structuring)
- No real bank data used at any point

---

## Model Performance

### Isolation Forest (Unsupervised — No Labels Required)
| Metric | Value |
|--------|-------|
| Contamination Rate | 5% |
| Estimators | 200 |
| Feature Input | 29 graph + behavioural features |
| Training Time | ~2s on 8,000 accounts |

### XGBoost Fraud Classifier (Supervised — GPU Accelerated)
| Metric | Value |
|--------|-------|
| **PR-AUC** | 0.640 |
| **Precision** | 0.778 |
| **Recall** | 0.609 |
| **F1-Score** | 0.683 |
| **CV AUC-ROC** | 0.933 |
| Training | Temporal 70/15/15 split (no data leakage) |
| GPU | NVIDIA RTX 3060 (CUDA) |
| Early Stopping | 50 rounds on validation aucpr |
| Optimal Threshold | 0.5 (via PR curve analysis) |

### Ensemble Risk Scoring
| Component | Weight | Source |
|-----------|--------|--------|
| ML Score | 30% | max(IF anomaly, XGBoost fraud_prob × 100) |
| Pattern Score | 40% | Weighted pattern flags (layering=25, round_trip=30, structuring=20, dormancy=20, profile=15) |
| Graph Score | 30% | PageRank × 10000 + Betweenness × 100 |

---

## Fraud Detection Capabilities

### 5 Custom Pattern Detectors
| # | Detector | Algorithm | Key Threshold |
|---|----------|-----------|---------------|
| 1 | **Layering** | Temporal chain extraction + amount decay analysis | ≥3 hops, 30-min window, 70% preservation |
| 2 | **Round-Tripping** | Johnson's cycle detection on SCCs | ≥85% amount return, ≤72h window |
| 3 | **Structuring** | Rule-based + Isolation Forest hybrid | ₹9L–₹10L range, ≥3 near-threshold txns |
| 4 | **Dormancy** | Vectorised gap analysis + burst detection | ≥180 days inactive, ≥10× volume multiplier |
| 5 | **Profile Mismatch** | Z-score + Mahalanobis + peer deviation | >3σ from peer group, >10× declared income |

### Graph Intelligence
| Capability | Algorithm | Use Case |
|-----------|-----------|----------|
| Role Classification | Percentile-based flow ratio analysis | SOURCE / MULE / SINK / NORMAL |
| Fund Trail | Temporal BFS (money only flows forward in time) | Trace complete journey of funds |
| Accomplice Detection | Random Walk with Restart (p=0.15, 5000 steps) | Find connected suspicious actors |
| Cycle Detection | Johnson's algorithm on bounded SCCs | Identify circular money flows |
| Suspicious Paths | Chain scoring (avg_risk×0.4 + max_risk×0.4 + hops×2) | Rank investigation targets |

---

## Key Test Accounts (for Demo Verification)

| Account ID | Embedded Pattern | Expected Detection |
|------------|-----------------|-------------------|
| `STR001AA01` – `STR005EE05` | Structuring | HIGH risk, amounts ₹9L–₹9.5L |
| `RT_SRC_001` / `RT_DST_001` | Round-Tripping | Circular flows, 85-95% return |
| `LAY_A01` → `LAY_E01` | Layering | 5-hop chain, 5-15% decay/hop |
| `FANOUT_01` – `FANOUT_03` | Fan-Out | SOURCE role, 15-25 recipients |
| `DORM_001` – `DORM_003` | Dormancy | Quiet Day1, burst Day2 |
| `VELO_001` – `VELO_002` | Velocity Spike | 20+ txns in 30 minutes |
| `SHIFT_001` – `SHIFT_003` | Behavioural Shift | Clean Day1 → Dirty Day2 |

---

## Known Limitations

We are transparent about what is built vs. what would be needed for production:

1. **Synthetic data only** — Trained on IBM AML public dataset and custom synthetic data. Real bank deployment would require re-training on actual transaction logs.
2. **Batch processing** — Current system processes uploaded CSVs. Production would need Kafka/streaming for real-time detection. Architecture supports this via the event bus abstraction.
3. **No live banking integration** — Not connected to CBS, RTGS, or NEFT gateways. The ingestion layer is designed as a pluggable adapter for future integration.
4. **Approximate graph metrics** — PageRank and betweenness use fast approximations (O(n)) rather than exact algorithms (O(n³)) for scalability. Exact computation is available but disabled for performance.
5. **Single-node deployment** — Current architecture runs on one machine. Production would distribute graph partitioning across a cluster.
6. **Evidence PDF format** — STR reports follow FIU-IND structure but are not legally certified or digitally signed.
7. **No authentication** — Dashboard has no RBAC (acceptable for POC; production requires multi-level access control).

---

## Team

| Name | Role | Contribution |
|------|------|-------------|
| [Name 1] | ML Lead | Ensemble pipeline (IF + XGBoost), 29-feature extractor, model tuning |
| [Name 2] | Graph & Backend | NetworkX engine, FastAPI server, 5 pattern detectors, event bus |
| [Name 3] | Frontend & Viz | Next.js dashboard, Cytoscape.js graph, responsive UI |
| [Name 4] | Data & Research | Synthetic data generator, IBM AML analysis, FIU-IND compliance research |

---

## Contact

**Team Name:** TraceX  
**Institute:** [Your College Name]  
**Email:** [Team email]  
**Hackathon:** Union Bank × iDEA 2.0 — Phase 2 Submission  
**Problem Statement:** PS3 — Tracking of Funds within Bank for Fraud Detection
