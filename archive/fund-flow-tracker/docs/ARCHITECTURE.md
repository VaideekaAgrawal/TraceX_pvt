# TraceX Architecture

## System Overview

TraceX is a production-grade Anti-Money Laundering (AML) intelligence system that processes daily transaction dumps, builds transaction graphs, detects fraud patterns, and provides an interactive investigation dashboard.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         TraceX System                                │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────┐     ┌───────────────┐     ┌──────────────────────┐  │
│  │ Bank EOD │────▶│  Ingestion    │────▶│   Database Layer     │  │
│  │ CSV Dump │     │  Service      │     │  (Neo4j / SQLite)    │  │
│  └──────────┘     │  - Validate   │     └──────────┬───────────┘  │
│                   │  - Normalize  │                 │              │
│  ┌──────────┐     │  - Idempotent │     ┌──────────▼───────────┐  │
│  │ UI Upload│────▶│  - Hash Check │────▶│   Detection Engine   │  │
│  │ (Browser)│     └───────────────┘     │  - Pattern Detector  │  │
│  └──────────┘                           │  - ML Anomaly (XGB)  │  │
│                                         │  - Risk Scorer       │  │
│                                         │  - Role Classifier   │  │
│                                         └──────────┬───────────┘  │
│                                                    │              │
│  ┌──────────────────────────────────────────────────▼───────────┐  │
│  │                    FastAPI Backend                            │  │
│  │  /api/init          - Full pipeline initialization           │  │
│  │  /api/ingest/upload - CSV upload + incremental analysis      │  │
│  │  /api/overview      - Dashboard aggregates (cached 30s)      │  │
│  │  /api/graph         - Graph data (filtered, ego-graph)       │  │
│  │  /api/anomaly       - Anomaly detection results              │  │
│  │  /api/patterns      - Pattern detection results              │  │
│  │  /api/evidence      - FIU evidence generation                │  │
│  └──────────────────────────────────────────────────┬───────────┘  │
│                                                     │              │
│  ┌──────────────────────────────────────────────────▼───────────┐  │
│  │                   Next.js Frontend                           │  │
│  │  Dashboard | Ingest | Graph | Anomaly | Patterns | Evidence  │  │
│  │  - Cytoscape.js graph visualization                         │  │
│  │  - FilterBar on all list pages                              │  │
│  │  - Skeleton loaders for loading states                      │  │
│  │  - Drag-and-drop CSV upload                                 │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

## Component Details

### 1. Ingestion Layer (`services/ingestion/eod_service.py`)
- **Input:** CSV file (same format as training data)
- **Idempotency:** SHA-256 hash of file prevents duplicate processing
- **Account Classification:** New accounts vs existing accounts
- **Incremental Analysis:** Existing accounts use 7-day rolling window
- **Detectors:** structuring, velocity_spike, round_trip, fan_out, mule_suspect
- **CLI:** `scripts/ingest_eod.py` for cron/scheduler
- **API:** `POST /api/ingest/upload` for browser upload

### 2. Database Layer (`infrastructure/database.py`)
- **Adapter Pattern:** Abstract `DatabaseAdapter` with implementations:
  - `Neo4jAdapter` — preferred for graph queries (free tier: Neo4j Aura)
  - `SQLiteAdapter` — fallback for development/testing
- **Config:** Environment variables (`DB_BACKEND`, `NEO4J_URI`, etc.)
- **Features:** Accounts CRUD, transactions, alerts, ingestion metadata, ego-graph queries

### 3. Detection Engine
- **Pattern Detector:** Layering, round-tripping, structuring, dormant activation, fan-in/out
- **ML Detector:** XGBoost classifier trained on labeled AML data
- **Risk Scorer:** Composite score (0-100) from multiple signals
- **Role Classifier:** SOURCE, MULE, SINK, NORMAL classification
- **Speed Analyzer:** Rapid fund movement detection

### 4. API Layer (`api/server.py`)
- **Framework:** FastAPI with CORS for frontend
- **Caching:** TTLCache (30s) for expensive endpoints
- **Endpoints:** Health, init, ingest, overview, graph, anomaly, patterns, evidence, metrics
- **Filtering:** All list endpoints support multi-parameter filtering
- **Pagination:** Offset-based with total counts

### 5. Frontend (`frontend/`)
- **Framework:** Next.js 16 + React 19 + TypeScript + Tailwind CSS v4
- **Graph:** Cytoscape.js (production) + Canvas fallback
- **Charts:** Recharts for statistical visualizations
- **UX:** Skeleton loaders, progressive loading, FilterBar components

## Data Flow: EOD Ingestion

```
1. User uploads CSV via UI (or cron triggers CLI)
2. EOD Service validates format, computes file hash
3. If hash exists in DB → skip (idempotent)
4. For each account in CSV:
   a. Check if account exists in DB
   b. If new: analyze today's transactions only
   c. If existing: fetch last 7 days from DB + merge with today
5. Run incremental detectors on each account's window
6. Store transactions, accounts, and alerts to DB
7. Record ingestion metadata
8. Refresh in-memory graph engine (if running)
9. Return results to user (alerts, patterns, accounts)
```

## Deployment (GCP)

### Cloud Run (Recommended)
```bash
# Backend
gcloud run deploy tracex-api \
  --source=. \
  --port=8000 \
  --set-env-vars="DB_BACKEND=neo4j,NEO4J_URI=$NEO4J_URI,NEO4J_USER=$NEO4J_USER,NEO4J_PASSWORD=$NEO4J_PASSWORD"

# Frontend
cd frontend && npm run build
gcloud run deploy tracex-frontend --source=. --port=3000
```

### Environment Variables
| Variable | Description | Required |
|----------|-------------|----------|
| `DB_BACKEND` | `neo4j` or `sqlite` | Yes |
| `NEO4J_URI` | Neo4j Aura connection URI | If neo4j |
| `NEO4J_USER` | Neo4j username | If neo4j |
| `NEO4J_PASSWORD` | Neo4j password | If neo4j |
| `SQLITE_PATH` | Path to SQLite DB file | If sqlite |
| `NEXT_PUBLIC_API_URL` | Backend URL for frontend | Yes |

### Neo4j Aura Free Tier
- 1 database, 200K nodes, 400K relationships
- Sufficient for demo/POC with subset data
- For production: upgrade to Professional tier

### Scaling Notes
- Backend is stateless (all state in DB) → horizontal scaling via Cloud Run
- Frontend is static after build → CDN-friendly
- Neo4j handles concurrent reads well; writes batched via ingestion
- For >10M transactions: consider partitioning by time window

## Fallback Strategy

If Neo4j free tier is unsuitable:
1. **SQLite** (current fallback): Zero-config, file-based, good for single-instance
2. **MongoDB Atlas** (free tier): 512MB storage, good for document queries
3. **PostgreSQL** (Cloud SQL): Managed, ACID, but no native graph queries

Trade-offs documented in code: `infrastructure/database.py`
