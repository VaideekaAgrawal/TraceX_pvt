# D1 — Problem Statement + Solution Brief
## PS3: Tracking of Funds within Bank for Fraud Detection

| Field | Details |
|-------|---------|
| **Team Name** | TraceX |
| **Problem Statement** | PS3 — Tracking of Funds within Bank for Fraud Detection |
| **Domain** | AML / Graph Analytics / Machine Learning / Financial Crime |
| **Team Members** | [Name 1] — ML & Ensemble Lead \| [Name 2] — Graph Engine & Backend \| [Name 3] — Frontend & Visualization \| [Name 4] — Data Engineering & Research |

---

## PART A: THE PROBLEM (1 PAGE)

### 1. The Problem in One Sentence

**Core Problem:**  
Union Bank of India processes millions of inter-account transactions daily across NEFT, RTGS, UPI, and IMPS channels. Money launderers exploit the bank's transaction infrastructure to move illicit funds through **rapid layering** (splitting and recombining through multiple accounts), **circular routing** (round-tripping to obscure origin), **structuring** (keeping amounts just below ₹10 lakh CTR threshold), **dormant account abuse** (suddenly activating long-inactive accounts), and **profile mismatches** (volumes wildly exceeding declared income). Current systems cannot trace the complete journey of funds across account hops or identify coordinated multi-account schemes in real time.

### 2. Who Is Affected and How Severely?

- **Direct:** Union Bank's fraud investigation teams — overwhelmed by volume; manually tracing fund flows through CBS logs account-by-account is impossibly slow for 5M+ daily transactions.
- **Financial:** RBI's Annual Report (2023-24) records ₹36,342 crore in total bank fraud. Multi-hop layering and structuring account for a significant portion that rule-based systems miss entirely.
- **Regulatory:** Banks must file Suspicious Transaction Reports (STR) to FIU-IND within 7 days. Without automated detection and evidence packaging, compliance teams miss filing deadlines.
- **Scale:** A single structured scheme across 10 mule accounts can move ₹1 crore below radar in under 24 hours. With 517K+ accounts, manual detection is impossible.
- **Victims:** End victims of money laundering include terror financing targets, drug trade beneficiaries, and tax fraud subjects. Faster detection = faster disruption.

### 3. Why Current Approaches Fail

| Current Approach | Failure Mode |
|-----------------|--------------|
| **Rule-based threshold alerts** (e.g., flag if >₹10L) | Launderers structure at ₹9.99L. Rules have no concept of multi-hop chains or temporal coordination |
| **Single-transaction analysis** | Cannot see that 10 individual ₹9L transactions from the same source, split across 10 mules, total ₹90L |
| **Periodic manual audits** | Backward-looking (weeks/months after damage). By audit time, funds have exited the system |
| **Vendor AML systems** (Actimize, Mantas) | Black-box rules, expensive, not customized to Indian banking patterns (₹10L CTR, UPI-specific flows) |
| **No graph-based analysis** | Relationships between accounts are invisible. A→B is flagged; A→B→C→D→A is not |
| **No ML on behavioral baselines** | Cannot detect that an account with ₹50K/month income suddenly moves ₹50L in a week |

**The fundamental gap:** Current systems analyze transactions **in isolation**. They cannot model the **network of relationships** between accounts, detect **coordinated multi-hop schemes**, or trace the **complete journey** of specific funds from origin to destination.

---

## PART B: OUR SOLUTION

### 4. What We Are Building: TraceX

TraceX is a **graph-first, ML-powered fund flow intelligence system** that:
1. Builds a real-time directed multigraph of all bank account relationships
2. Applies 5 custom fraud pattern detectors (each targeting a specific RBI-defined typology)
3. Trains an ensemble ML model (Isolation Forest + XGBoost) on 29 graph-derived features
4. Classifies account roles (SOURCE / MULE / SINK / NORMAL) using fund flow analysis
5. Enables investigators to trace the complete journey of any fund through interactive graph visualization
6. Auto-generates FIU-IND compliant STR evidence packages with one click

**Why "graph-first":** Money laundering is fundamentally a **network crime**. A single transaction looks normal; the pattern only emerges when you see the graph. TraceX models the problem correctly from the ground up.

### 5. Core Features of Our POC

#### A. Graph Intelligence Engine
- **Directed multigraph** of all accounts (nodes) and transactions (edges)
- **Johnson's algorithm** for cycle detection (finds round-trips up to length 5)
- **Temporal BFS** traces fund journey respecting time (money can't flow backward)
- **Random Walk with Restart** (p=0.15, 5000 steps) discovers accomplice networks
- **Role classification:** SOURCE (sends out), MULE (passes through), SINK (accumulates)

#### B. 5 Custom Fraud Pattern Detectors
| # | Pattern | What It Detects | Real-World Scenario |
|---|---------|----------------|---------------------|
| 1 | **Layering** | Multi-hop chains (≥3 accounts) with decreasing amounts in 30 minutes | Drug money split through 5 mule accounts before consolidation |
| 2 | **Round-Tripping** | Circular flows (A→B→C→A) with ≥85% amount return within 72h | Tax fraud: show fake business activity via round-trip |
| 3 | **Structuring** | ₹9L–₹10L amounts (just below ₹10L CTR threshold), ≥3 per account | Avoiding mandatory Currency Transaction Report filing |
| 4 | **Dormancy** | 180+ days inactive → sudden high-value burst (≥10× historical average) | Purchased dormant accounts used as fresh mules |
| 5 | **Profile Mismatch** | Volume >10× declared income OR >3σ from peer group | Fake salary accounts used for laundering |

#### C. Ensemble ML Pipeline (No Single-Algorithm Dependency)
- **Isolation Forest** (unsupervised): Detects anomalies from Day 1, no labels required
- **XGBoost** (supervised, GPU): Trained on 5,100 labelled laundering cases, F1=0.683
- **29 features per account**: Graph structural (PageRank, betweenness, degree) + Temporal (velocity, dormancy) + Behavioural (channel entropy, night ratio, peer deviation)
- **Ensemble scoring**: ML 30% + Pattern flags 40% + Graph centrality 30% → final risk score 0-100

#### D. Investigator Dashboard (8 Pages)
- **Dashboard:** Real-time stats, risk distribution, top alerts, model performance
- **Graph Explorer:** Neo4j-style interactive visualization (Cytoscape.js), ego-graphs, fund trails
- **Anomaly:** Score histogram, feature importance, P1-P4 investigation queue
- **Patterns:** 8-tab view of all detected patterns with evidence details
- **Evidence:** One-click FIU-IND STR generation (PDF + JSON + SHA-256 integrity hash)

#### E. Evidence Package Generator (FIU-IND Compliant)
- Auto-generates Suspicious Transaction Report in FIU-IND format
- Includes: account details, transaction timeline, detected pattern, risk score, graph subgraph
- Output: PDF report + machine-readable JSON + SHA-256 tamper-detection hash
- Designed for direct submission to Financial Intelligence Unit

### 6. What Is Built vs. What Is Planned

| BUILT (Demonstrable in POC) | PLANNED (Not Yet Built) |
|----------------------------|-------------------------|
| ✅ 5 custom fraud pattern detectors with specific thresholds | ⬜ 15+ additional pattern typologies |
| ✅ Isolation Forest + XGBoost ensemble (GPU-accelerated) | ⬜ Graph Neural Network (GraphSAGE/GAT) |
| ✅ 29-feature vectorised extractor (scales to millions) | ⬜ Real-time streaming (Kafka) |
| ✅ NetworkX directed multigraph with 7 algorithms | ⬜ Neo4j cluster (adapter already built) |
| ✅ Next.js dashboard with 8 pages + Cytoscape.js graphs | ⬜ Mobile investigator app |
| ✅ FIU-IND STR evidence generation (PDF + JSON) | ⬜ Digital signature + legal certification |
| ✅ Temporal BFS fund trail tracing | ⬜ Real-time CBS/NEFT/RTGS integration |
| ✅ Random Walk with Restart for accomplice discovery | ⬜ Multi-bank federated analysis |
| ✅ Daily EOD incremental ingestion pipeline | ⬜ Sub-second streaming ingestion |
| ✅ Case management with TP/FP feedback loop | ⬜ Auto-retraining from investigator feedback |
| ✅ Tested on IBM AML (5M txns, 517K accounts) | ⬜ Tested on real Union Bank data |
| ✅ SQLite ↔ Neo4j adapter pattern | ⬜ Horizontal scaling / graph partitioning |
| ✅ GitHub Actions CI + Docker deployment | ⬜ Kubernetes + monitoring (Prometheus/Grafana) |
| ✅ 8 health checkpoints including SHA-256 integrity | ⬜ SOC2 compliance audit trail |

### 7. Technical Differentiators (Why We Win)

| Differentiator | Details |
|---------------|---------|
| **Not a single API call** | Custom 5-detector + 2-model ensemble pipeline; no GPT wrapper |
| **Graph-first architecture** | Correctly models money laundering as a network crime |
| **29 hand-engineered features** | Capture structural + temporal + behavioural signals simultaneously |
| **GPU-accelerated XGBoost** | Trains on 517K accounts in seconds (CUDA RTX 3060) |
| **Temporal BFS** | Only system that traces funds forward-in-time (not just shortest path) |
| **Johnson's cycle detection** | Mathematically optimal algorithm for round-trip identification |
| **Production-ready architecture** | Adapter pattern, event bus, health monitoring — not a Jupyter notebook |
| **Evidence generation** | FIU-IND STR format — immediately usable by compliance teams |
| **Tested at scale** | Validated on 5M transactions, 517K accounts (IBM AML dataset) |
| **Honest about limitations** | We know what's built vs. planned; no fake metrics |
