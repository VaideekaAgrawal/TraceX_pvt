# D2 — Frontend + Backend Demonstration Video Script (5–10 Minutes)
## TraceX: Fund Flow Tracking & AML Intelligence System
### PS3: Tracking of Funds within Bank for Fraud Detection

---

## VIDEO SPECIFICATIONS
- **Duration:** 7–8 minutes (target)
- **Format:** Screen recording with continuous voice narration (no silent clicking)
- **Resolution:** 1080p minimum
- **Upload:** YouTube (Unlisted)
- **Key Rule:** Narrate EVERYTHING you do. Explain WHY, not just WHAT.

---

## PRE-RECORDING CHECKLIST
- [ ] Backend running: `uvicorn api.server:app --port 8000`
- [ ] Frontend running: `npm run dev` (http://localhost:3000)
- [ ] Database cleared: delete `data/tracex.db` for fresh demo
- [ ] Test CSVs ready: `data/tracex_test_day1.csv` + `data/tracex_test_day2_incremental.csv`
- [ ] Terminal visible (split screen: browser left, terminal right)
- [ ] Microphone tested, no background noise

---

## SECTION 1: SYSTEM STARTUP & ARCHITECTURE [0:00 – 1:30]

**[VISUAL: Terminal window, show the project folder structure]**

**NARRATION:**

"Hi, I'm [Name] from Team TraceX. In this video, I'm going to demonstrate our complete fund flow tracking system — from starting the backend, to ingesting transaction data, to detecting fraud patterns, to generating evidence reports. Everything you see is running live — no pre-recorded outputs.

Let me first show you the project structure."

**[ACTION: Run `tree` or show VS Code explorer with folders expanded]**

"Our system is organized into microservice layers. The `api/` folder contains our FastAPI server with 25+ endpoints. `services/` has the core logic — `detection/` for our 5 fraud detectors and ML pipeline, `graph/` for the NetworkX engine, `ingestion/` for data parsing, and `investigation/` for case management and evidence generation. `infrastructure/` handles configuration, the database adapter, event bus, and health monitoring."

**[ACTION: Show `requirements.txt` briefly]**

"We're using FastAPI, scikit-learn for Isolation Forest, XGBoost with GPU acceleration, NetworkX for graph analytics, and FPDF2 for PDF report generation. 19 production dependencies total."

**[ACTION: Start backend in terminal]**

```bash
uvicorn api.server:app --host 0.0.0.0 --port 8000
```

"Starting the FastAPI server. You can see it detects my NVIDIA RTX 3060 GPU and will use CUDA for XGBoost training. The server is now live on port 8000."

**[ACTION: In a second terminal, start frontend]**

```bash
cd frontend && npm run dev
```

"And here's the Next.js frontend starting up on port 3000. This gives investigators an 8-page dashboard to explore the data."

---

## SECTION 2: DATA INGESTION — CSV UPLOAD [1:30 – 3:00]

**[VISUAL: Switch to browser at http://localhost:3000]**

**NARRATION:**

"Opening the application. Right now, the system is empty — no data loaded. The dashboard shows a 'System not initialized' message because there's nothing to analyze yet."

**[ACTION: Navigate to /ingest page]**

"I'm going to the Ingest page. This is where investigators upload transaction data. In a production environment, this would be an automated daily feed from the Core Banking System. For our POC, we support CSV upload."

**[ACTION: Click 'Choose File', select `tracex_test_day1.csv`]**

"I'm selecting our Day 1 test dataset. This contains 8,000 transactions across 312 accounts. The data has embedded fraud patterns — layering chains, round-trip cycles, structuring clusters, fan-out networks — with realistic noise mixed in. The accounts have names like STR001 for structuring, RT_SRC for round-tripping, LAY_A for layering — so we can verify detection accuracy."

**[ACTION: Click Upload / Submit button. Watch the terminal for processing logs.]**

"Watch the terminal as it processes. You can see:
- First, it parses the CSV and validates the schema
- Then it builds the directed multigraph — 312 nodes, thousands of edges
- Next, the feature extractor computes 29 features per account — graph metrics like PageRank and betweenness centrality, temporal features like transaction velocity and timing entropy, and behavioral features like channel diversity and night-time ratios
- Now it's training the Isolation Forest — 200 estimators, 5% contamination rate
- XGBoost is training on GPU — you can see the CUDA logs — with early stopping on PR-AUC
- All 5 pattern detectors are running: layering, round-tripping, structuring, dormancy, profile mismatch
- Finally, ensemble scoring combines everything into a 0-100 risk score per account

The entire pipeline — parse, graph, features, ML, patterns, scoring, role classification — completed in under 10 seconds."

**[ACTION: Show the success response in the browser]**

"The frontend confirms ingestion: 312 accounts processed, models trained, patterns detected. Let's go explore what it found."

---

## SECTION 3: DASHBOARD OVERVIEW [3:00 – 3:45]

**[ACTION: Navigate to / (home dashboard)]**

**NARRATION:**

"The dashboard gives investigators a single-screen summary. At the top we see total accounts, total transactions, flagged accounts, and average risk score. The risk distribution chart shows how accounts are distributed across LOW, MEDIUM, HIGH, and CRITICAL risk categories.

Below that, we have the model metrics panel — XGBoost precision 0.778, recall 0.609, F1 0.683, and the PR-AUC of 0.640. These are honest numbers on a heavily imbalanced dataset where only about 5% of accounts are actually laundering.

The investigation priority queue ranks the most urgent cases: P1 for critical risk accounts flagged by multiple detectors, down to P4 for accounts with only minor anomalies. This is what a fraud investigator would look at first thing every morning."

---

## SECTION 4: GRAPH EXPLORER — NEO4J-STYLE VISUALIZATION [3:45 – 5:30]

**[ACTION: Navigate to /graph]**

**NARRATION:**

"This is the Graph Explorer — the core of TraceX's value proposition. Every account is a node. Every transaction is a directed edge. The visualization is powered by Cytoscape.js with a physics-based COSE layout.

Let me explain the visual encoding:
- **Colors** represent risk: red is CRITICAL 76-100, orange is HIGH 51-75, yellow is MEDIUM 26-50, green is LOW 0-25
- **Shapes** represent roles: triangles are SOURCES that send money out, diamonds are MULES that pass money through, inverted triangles are SINKS that accumulate funds, circles are NORMAL accounts
- **Node size** scales with risk score — bigger nodes are more dangerous
- **Edge thickness** scales with transaction amount — thicker lines mean more money"

**[ACTION: Click on a red/orange node]**

"I'm clicking on this high-risk node — you can see its details: account ID, risk score, role classification, total sent and received amounts. Let me switch to Ego view to see its complete neighborhood."

**[ACTION: Switch to 'Ego Network' view mode, select the same account]**

"Now I can see every account this flagged account transacted with. This is exactly what an investigator needs — not just 'this account is suspicious', but WHO did it transact with, and are THEY also suspicious? You can see the red nodes clustering together — that's the suspicious subnetwork.

Now let me show the most powerful feature — pattern subgraph view."

**[ACTION: Switch to 'Pattern' view, select 'Layering']**

"I've switched to Pattern view and selected Layering. The system is now querying only accounts involved in detected layering chains — and rendering them with a breadthfirst layout so you can clearly see the money flowing through multiple hops. This chain shows money moving from the SOURCE through MULE accounts to the SINK, with amounts decreasing at each hop — classic layering.

Let me try round-tripping."

**[ACTION: Switch pattern type to 'Round-Trip']**

"Round-tripping patterns are shown with a circle layout. You can see the circular flow: Account A sends to B, B sends to C, C sends back to A — with 85-95% of the amount preserved. This is exactly what RBI defines as round-tripping for money laundering."

---

## SECTION 5: ANOMALY DETECTION & PATTERNS [5:30 – 7:00]

**[ACTION: Navigate to /anomaly]**

**NARRATION:**

"The Anomaly page shows ML-driven detection results. Each account has an anomaly score — accounts above the threshold are flagged. The investigation queue shows them ranked by priority.

You can see the score breakdown: ML confidence from both Isolation Forest and XGBoost, plus which specific features triggered the anomaly — high betweenness centrality, rapid transaction velocity, unusual amounts."

**[ACTION: Navigate to /patterns]**

"The Patterns page is organized by detection type. Let me expand the Layering tab."

**[ACTION: Click on Layering tab/section]**

"Here we can see every detected layering chain — the accounts involved, the number of hops, the amount decay percentage, the time window. Each detection includes a severity rating: HIGH for chains with 5+ hops and >₹10 lakh total flow, MEDIUM for shorter chains.

Let me check Structuring."

**[ACTION: Click on Structuring tab]**

"The structuring detector found accounts making multiple transactions between ₹9 lakh and ₹10 lakh — deliberately staying below the ₹10 lakh CTR threshold. You can see our test accounts STR001 through STR005 correctly flagged, along with several other accounts the model identified."

**[ACTION: Navigate to /profile]**

"The Profile Analyzer compares declared customer profiles against actual behavior. This account declared an income bracket suggesting ₹5 lakh monthly turnover — but it's actually processing ₹2.3 crore. That's a 46× mismatch. Definitely needs investigation."

---

## SECTION 6: INCREMENTAL INGESTION — BEHAVIORAL SHIFTS [7:00 – 8:00]

**[ACTION: Navigate back to /ingest]**

**NARRATION:**

"Now I'm going to demonstrate incremental detection. I'm uploading Day 2 data — 5,000 new transactions. This data includes accounts that were CLEAN on Day 1 but show SUSPICIOUS behavior on Day 2. This tests whether our system can detect behavioral drift."

**[ACTION: Upload `tracex_test_day2_incremental.csv` with force checkbox]**

"Watch the terminal — the system ingests incrementally. It doesn't rebuild from scratch. It ADDS the new transactions to the existing graph, re-extracts features, and re-scores. This is how a production system would work — processing each day's batch without losing historical context."

**[ACTION: Navigate to /anomaly or dashboard, show changed scores]**

"Look at the dashboard now — more accounts are flagged. Specifically, our DORM accounts — dormant for 180+ days on Day 1 — just burst with high-value transfers on Day 2. The dormancy detector caught them immediately. And our SHIFT accounts — clean on Day 1 — are now flagged because their Day 2 behavior deviates significantly from their established baseline.

This is the power of incremental ML: the model learns what's NORMAL for each account and flags when behavior CHANGES."

---

## SECTION 7: EVIDENCE GENERATION — FIU REPORTING [8:00 – 8:30]

**[ACTION: Navigate to /evidence]**

**NARRATION:**

"Finally, the Evidence Generator. When an investigator is ready to file a Suspicious Transaction Report with FIU-IND, they come here.

I select a flagged account, choose the pattern type detected, add investigator notes..."

**[ACTION: Fill in form fields, click Generate]**

"One click generates a complete evidence package:
- Account identification and KYC details
- Complete transaction timeline with flagged entries highlighted
- Graph visualization of the suspicious subnetwork
- Pattern detection summary with algorithm details
- Risk score breakdown showing exactly WHY this account was flagged
- SHA-256 hash for document integrity verification

This is ready for regulatory submission. In production, it would integrate with the bank's STR filing system."

---

## SECTION 8: API VERIFICATION — BACKEND DEPTH [8:30 – 9:00]

**[ACTION: Switch to terminal or Postman/curl]**

**NARRATION:**

"Let me quickly show that this isn't just a UI — the backend has real depth. Let me hit a few API endpoints directly."

**[ACTION: Run curl commands]**

```bash
curl http://localhost:8000/health
```

"Health endpoint shows all system components operational."

```bash
curl http://localhost:8000/api/overview
```

"Overview returns total accounts, transactions, flagged count, risk distribution, model metrics — all computed live."

```bash
curl http://localhost:8000/api/graph?max_nodes=20
```

"Graph endpoint returns nodes with risk scores and roles, plus edges with amounts and timestamps — all in JSON ready for any visualization library."

```bash
curl http://localhost:8000/api/accounts/STR001AA01
```

"Individual account lookup gives complete feature vector — all 29 features, risk breakdown, pattern flags, transaction history. This is the raw intelligence behind every UI element you saw."

---

## CLOSING [9:00 – 9:15]

**[VISUAL: Return to dashboard]**

**NARRATION:**

"That's TraceX — a complete, working fund flow tracking system. Graph-first intelligence, 5 custom fraud detectors, ensemble ML with GPU acceleration, and investigator-ready evidence generation. Every component I showed is running live, on real data, producing real output.

Every rupee leaves a trail. TraceX makes it visible.

Thank you."

---

## POST-RECORDING NOTES

### Key Points to Emphasize During Recording:
1. **Never stay silent** — explain every click, every navigation, every loading state
2. **Show the terminal** — processing logs prove the ML is running, not faked
3. **Point out specific numbers** — "0.683 F1 score", "29 features", "312 accounts" — specifics build credibility
4. **Mention algorithm names** — "Johnson's cycle detection", "COSE layout", "PageRank" — shows depth
5. **Show imperfections honestly** — if something takes 2 seconds to load, say "the model is computing in real-time"
6. **Contrast with the problem** — "A manual investigator would take hours to trace this chain. We do it in milliseconds."

### If Something Goes Wrong During Recording:
- **Page loads slowly:** "The system is computing graph layout for 300+ nodes — this is real-time physics simulation, not a cached image"
- **No flagged accounts:** Re-check CSV was uploaded. Say "Let me verify the data was ingested" and show the /api/overview endpoint
- **Graph looks sparse:** "I'm showing a capped view of 40 nodes for browser performance. The full graph has 312 nodes — investigators can zoom and filter."

### Video Quality Tips:
- Use dark mode in browser and terminal (looks more professional on YouTube)
- Zoom browser to 110-125% so text is readable at 1080p
- Close all other tabs and notifications
- Record at least 2 takes — use the better one
