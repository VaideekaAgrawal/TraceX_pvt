# TraceX — Presentation Deck Content
## PS3: Tracking of Funds within Bank for Fraud Detection
### Team TraceX | Union Bank × iDEA 2.0

---

## SLIDE 1: TITLE

**TraceX**  
*"Every rupee leaves a trail. We make it visible."*

**Fund Flow Tracking & AML Intelligence System**  
PS3: Tracking of Funds within Bank for Fraud Detection  
Team TraceX | [Institute Name]

---

## SLIDE 2: THE PROBLEM

### ₹36,342 Crore Lost to Bank Fraud (RBI 2023-24)

**The reality today:**
- Union Bank processes **millions of transactions daily** across NEFT, RTGS, UPI, IMPS
- Money launderers exploit this volume to hide in plain sight
- Current rule-based systems analyze transactions **in isolation**
- **The network is invisible** — A→B→C→D→A looks like 4 normal transactions

**5 Attack Patterns That Slip Through:**

| Pattern | How It Works | Why Current Systems Miss It |
|---------|-------------|----------------------------|
| **Layering** | ₹1Cr split through 5 accounts in 30 min | Each individual txn looks small |
| **Round-Tripping** | A→B→C→A within 72 hours | No cycle detection |
| **Structuring** | 10 txns of ₹9.9L (below ₹10L CTR limit) | Each individually "below threshold" |
| **Dormant Abuse** | 6-month inactive account suddenly moves ₹50L | No behavioral baseline |
| **Profile Mismatch** | ₹50K salary account moves ₹5Cr/month | No income-to-volume correlation |

**The fundamental gap:** Fraud is a **network crime**. You cannot detect it by looking at individual transactions.

---

## SLIDE 3: OUR SOLUTION — TraceX

### Graph-First, ML-Second, Law-Enforcement-Ready

**TraceX treats money laundering as what it is: a graph problem.**

```
Transaction Data → Directed MultiGraph → Pattern Detection → ML Scoring → Evidence Package
                   (accounts = nodes)     (5 detectors)      (IF + XGBoost)  (FIU-IND STR)
                   (transactions = edges)  (graph algorithms)  (29 features)   (PDF + JSON)
```

**What makes us different:**
- 🔍 **Graph-First:** We build the relationship network FIRST, then analyze patterns
- 🧠 **Custom ML:** 29 hand-engineered features + Isolation Forest + XGBoost (not a GPT wrapper)
- ⚡ **5 Targeted Detectors:** Each addresses a specific RBI-defined laundering typology
- 📋 **Evidence-Ready:** Auto-generates FIU-IND compliant STR packages
- 🖥️ **Interactive Graphs:** Neo4j-style visualization for investigator exploration

---

## SLIDE 4: ARCHITECTURE OVERVIEW

### 5-Layer System Architecture

```
┌────────────────────────────────────────────────────────────────┐
│  LAYER 5: PRESENTATION — Next.js 16, Cytoscape.js, 8 Pages    │
├────────────────────────────────────────────────────────────────┤
│  LAYER 4: DETECTION — 5 Detectors + IF + XGBoost Ensemble     │
├────────────────────────────────────────────────────────────────┤
│  LAYER 3: GRAPH ENGINE — NetworkX MultiDiGraph, 7 Algorithms   │
├────────────────────────────────────────────────────────────────┤
│  LAYER 2: INFRASTRUCTURE — Event Bus, DB, Health, Validation   │
├────────────────────────────────────────────────────────────────┤
│  LAYER 1: INGESTION — IBM AML, Custom CSV, Daily EOD Feed      │
└────────────────────────────────────────────────────────────────┘
```

**Key Design Decisions:**
- **Adapter Pattern:** SQLite (POC) ↔ Neo4j (Production) — swap via env var
- **Event Bus:** Kafka-pattern pub/sub — decouples all services
- **Vectorised Features:** 29 features/account computed via Pandas (no Python loops)
- **GPU Acceleration:** XGBoost on CUDA (RTX 3060) — trains on 517K accounts in seconds

---

## SLIDE 5: GRAPH INTELLIGENCE

### The Network Reveals What Transactions Hide

**Graph Structure:**
- **Nodes:** Every bank account (517,000+ in full dataset)
- **Edges:** Every transaction (directed, multi-edge, weighted by amount)
- **Insight:** The *structure* of connections reveals coordinated schemes

**7 Graph Algorithms:**

| Algorithm | Purpose | Finding |
|-----------|---------|---------|
| Johnson's Cycle Detection | Round-trip identification | A→B→C→A flows |
| Temporal BFS | Fund trail tracing | Complete money journey (forward-in-time only) |
| Random Walk with Restart | Accomplice discovery | Who else is connected to this suspect? |
| PageRank (approx) | Money concentration | Where do funds accumulate? |
| Betweenness (approx) | MULE identification | Who sits between SOURCE and SINK? |
| Role Classification | Account typing | SOURCE → MULE → SINK flow direction |
| Suspicious Path Ranking | Investigation priority | Which chains deserve attention first? |

**Demo:** [Screenshot of Cytoscape graph showing a detected layering chain with color-coded risk nodes]

---

## SLIDE 6: 5 FRAUD PATTERN DETECTORS

### Custom-Built for Indian Banking Context

| # | Detector | Algorithm | Key Threshold | Why It Matters |
|---|----------|-----------|---------------|----------------|
| 1 | **Layering** | Temporal chain extraction | ≥3 hops, 30-min window, 70% amount preservation | ₹1Cr moved through 5 accounts in minutes |
| 2 | **Round-Tripping** | Johnson's cycle detection on SCCs | ≥85% return, ≤72h | Fake business activity for tax fraud |
| 3 | **Structuring** | Rule + IF hybrid | ₹9L–₹10L, ≥3 per account | Avoiding ₹10L CTR reporting to FIU |
| 4 | **Dormancy** | Vectorised gap analysis | ≥180 days inactive, ≥10× burst | Purchased mule accounts activated |
| 5 | **Profile** | Z-score + Mahalanobis | >3σ from peers, >10× income | Fake accounts laundering real money |

**Each detector produces:**
- Named pattern classification (required for FIU-IND STR)
- Specific account IDs involved
- Evidence trail (transaction hashes, timestamps, amounts)
- Severity rating (CRITICAL / HIGH / MEDIUM)
- Confidence score with supporting indicators

---

## SLIDE 7: ML PIPELINE — ENSEMBLE APPROACH

### Why Two Models? Because No Single Model Is Enough.

```
┌─────────────────────────────────────────────────────────────┐
│           29 FEATURES PER ACCOUNT                            │
│  Graph: PageRank, betweenness, degree (in/out), clustering   │
│  Flow: total_in, total_out, net_flow, reciprocity            │
│  Temporal: velocity, dormancy_days, regularity               │
│  Behavioural: night_ratio, weekend_ratio, round_numbers      │
│  Compliance: near_threshold_count, income_volume_ratio       │
└──────────────────┬──────────────────────────────────────────┘
                   │
         ┌─────────┼─────────┐
         ▼                   ▼
┌─────────────────┐  ┌─────────────────────┐
│ Isolation Forest │  │ XGBoost (GPU/CUDA)  │
│ n=200            │  │ 500 trees, depth=6  │
│ contamination=5% │  │ PR-AUC = 0.640      │
│ No labels needed │  │ F1 = 0.683          │
│ Works from Day 1 │  │ CV AUC-ROC = 0.933  │
└────────┬────────┘  └──────────┬──────────┘
         │                      │
         └──────────┬───────────┘
                    ▼
┌─────────────────────────────────────────────────────────────┐
│              ENSEMBLE RISK SCORER                             │
│  ML Score (30%) + Pattern Flags (40%) + Graph Score (30%)    │
│  → Risk Score 0-100 → Priority P1/P2/P3/P4                  │
│  → Confidence: Very Strong / Strong / Moderate / Weak        │
└─────────────────────────────────────────────────────────────┘
```

**Why this works better than any single approach:**
- IF detects **novel attacks** (no prior labels needed)
- XGBoost catches **known patterns** with high precision
- Pattern detectors provide **explainability** (required by FIU)
- Ensemble combines all three signals — more robust than any alone

---

## SLIDE 8: INVESTIGATOR DASHBOARD

### 8-Page Next.js Application — Built for Fraud Analysts

| Page | What It Shows | Key Interaction |
|------|--------------|----------------|
| **Dashboard** | Real-time stats, risk pie chart, top alerts | Auto-refresh on new data |
| **Ingest** | CSV upload, force re-process, history | Drag-drop → full pipeline runs |
| **Graph Explorer** | Interactive Cytoscape.js network | Click node → ego graph, trace fund trail |
| **Anomaly** | Score distribution, feature importance, queue | Sort by P1→P4 priority |
| **Patterns** | 8-tab pattern breakdown with evidence | Filter by severity, amount, account |
| **Evidence** | STR generator with PDF download | One-click FIU-IND report |
| **Profile** | Volume vs income scatter, peer comparison | Identify mismatches instantly |
| **Channels** | Channel-wise analytics and heatmap | Spot suspicious channel patterns |

**Graph Visualization:**
- Node **size** = risk score (bigger = more dangerous)
- Node **color** = risk level (🔴 CRITICAL, 🟠 HIGH, 🟡 MEDIUM, 🟢 LOW)
- Node **shape** = role (△ SOURCE, ◇ MULE, ▽ SINK, ○ NORMAL)
- Edge **thickness** = transaction amount

---

## SLIDE 9: EVIDENCE GENERATION — FIU-IND READY

### One-Click Suspicious Transaction Report

**What the Evidence Package Contains:**

| Section | Content |
|---------|---------|
| **Part A** | Reporting Entity (Bank) Details |
| **Part B** | Subject Account Information (ID, KYC, income, role) |
| **Part C** | Transaction Summary — top 20 suspicious transactions with amounts, dates, counterparties |
| **Part D** | Suspicion Indicators — which patterns detected, with what confidence |
| **Part E** | Graph Subgraph — visual showing the account's network context |

**Output Format:** PDF + JSON + SHA-256 integrity hash  
**Tamper Detection:** CP-08 health checkpoint verifies hash chain integrity  
**Use Case:** Investigator generates report → reviews → submits to FIU-IND within 7-day window

---

## SLIDE 10: LIVE DEMO RESULTS

### Tested on IBM AML Dataset (5M Transactions, 517K Accounts)

**Detection Results (Day 1 — 8,000 transactions, 312 accounts):**

| Metric | Value |
|--------|-------|
| Accounts analyzed | 312 |
| Transactions processed | 8,000 |
| Patterns detected | ~180+ flags across 5 types |
| P1 (Critical) alerts | 8-12 accounts |
| P2 (High) alerts | 20-30 accounts |
| Graph edges | 8,000 (capped to 100 for visualization) |
| Pipeline time | <10 seconds (with GPU) |

**Model Metrics:**
| Model | Metric | Value |
|-------|--------|-------|
| XGBoost | PR-AUC | 0.640 |
| XGBoost | Precision | 0.778 |
| XGBoost | Recall | 0.609 |
| XGBoost | F1 | 0.683 |
| XGBoost | CV AUC-ROC | 0.933 |
| IF | Contamination | 5% |
| Ensemble | Coverage | All accounts scored |

---

## SLIDE 11: TECHNICAL DEPTH — NOT A SLIDE DECK

### What Separates Us From "API Wrapper" Projects

| Dimension | Our Implementation |
|-----------|-------------------|
| **Custom ML Pipeline** | 29 features × 2 models × ensemble scoring — not a single sklearn call |
| **Graph Algorithms** | Johnson's cycles, temporal BFS, RWR, PageRank — implemented in engine |
| **5 Domain-Specific Detectors** | Each with tuned thresholds for Indian banking (₹10L CTR, UPI patterns) |
| **Production Architecture** | Adapter pattern, event bus, 8 health checkpoints, CI/CD, Docker |
| **Feature Engineering** | 29 features capturing graph + temporal + behavioural + compliance signals |
| **GPU Acceleration** | XGBoost on CUDA — not just CPU sklearn |
| **Evidence Generation** | FIU-IND STR format with SHA-256 integrity — not just a risk score |
| **Scale Validation** | Tested on 5M transactions (IBM AML) — not 100-row toy data |
| **Test Suite** | Unit + integration + smoke + regression guards (AUC≥0.88 gate) |
| **Honest Limitations** | We tell you exactly what's built vs. planned |

---

## SLIDE 12: BUILT vs. PLANNED

### We Are Honest About Scope

| ✅ BUILT & WORKING | ⬜ PLANNED FOR PRODUCTION |
|-------------------|--------------------------|
| 5 fraud pattern detectors | 15+ additional typologies |
| IF + XGBoost ensemble (GPU) | Graph Neural Network (GraphSAGE) |
| NetworkX graph engine (7 algorithms) | Neo4j cluster (adapter ready) |
| Next.js dashboard (8 pages) | Mobile investigator app |
| FIU-IND STR evidence (PDF + JSON) | Digital signature + legal certification |
| Temporal BFS fund tracing | Real-time CBS/NEFT integration |
| Random Walk accomplice discovery | Multi-bank federated analysis |
| Daily EOD ingestion pipeline | Sub-second Kafka streaming |
| GitHub Actions CI + Docker | Kubernetes + Prometheus monitoring |
| 8 health checkpoints | SOC2 audit trail |

**Key point:** Everything in the "Built" column **runs on data and produces output**. This is not vapourware.

---

## SLIDE 13: WHY TraceX WINS

### Evaluation Criteria Mapping

| Criteria | How We Excel |
|----------|-------------|
| **Technical Functionality (Working POC)** | Full pipeline runs: CSV → Graph → ML → Detection → Evidence. All 25+ API endpoints tested. GPU-accelerated. |
| **Problem Fit & Relevance** | Directly addresses PS3 with Indian banking context (₹10L CTR, FIU-IND STR format, UPI/NEFT channels) |
| **Innovation & Technical Depth** | Custom 5-detector ensemble + 29-feature XGBoost + temporal BFS + Johnson's cycles — not a single LLM call |
| **Code Quality & Documentation** | Clear README, runnable in 5 steps, CI/CD, Docker, honest limitations documented |
| **Demo Clarity** | Narrated video showing real data flowing through graph → detection → evidence |
| **Team & Execution Readiness** | Clear built vs. planned; production architecture (adapters, event bus) proves we can take it forward |

---

## SLIDE 14: TEAM & NEXT STEPS

### Team TraceX

| Member | Expertise | Contribution |
|--------|-----------|-------------|
| [Name 1] | Machine Learning | Ensemble pipeline, 29-feature extractor, XGBoost GPU tuning |
| [Name 2] | Systems & Graphs | NetworkX engine, FastAPI server, 5 detectors, event bus architecture |
| [Name 3] | Frontend & UX | Next.js dashboard, Cytoscape.js visualization, responsive design |
| [Name 4] | Data & Compliance | Synthetic generator, IBM AML analysis, FIU-IND research, documentation |

### Immediate Next Steps (if selected for Phase 3)
1. Deploy Neo4j cluster (adapter already built)
2. Connect to simulated CBS feed via Kafka
3. Add GNN layer (GraphSAGE) for structural learning
4. Pilot with Union Bank's sandbox data

---

## SLIDE 15: THANK YOU

**TraceX — Every rupee leaves a trail. We make it visible.**

📂 GitHub: [Repository Link]  
🎥 Demo Video: [YouTube Link]  
📧 Contact: [Team Email]

*PS3: Tracking of Funds within Bank for Fraud Detection*  
*Union Bank × iDEA 2.0 | Phase 2 Submission*
