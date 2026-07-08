# D5 — Pitch Video Script (~5 Minutes)
## TraceX: Fund Flow Tracking & AML Intelligence System
### PS3: Tracking of Funds within Bank for Fraud Detection

---

## VIDEO SPECIFICATIONS
- **Duration:** 4:30–5:00 minutes
- **Format:** Screen recording + face cam (picture-in-picture recommended)
- **Structure:** Problem (30s) → Solution + How It Works (2 min) → Demo Walkthrough (1.5 min) → Built vs. Planned (30s) → Team (30s)

---

## SECTION 1: THE PROBLEM [0:00 – 0:30]

**[VISUAL: Title slide with TraceX logo. Fade to RBI fraud statistics graphic.]**

**NARRATION:**

"Union Bank processes millions of transactions every single day. Hidden within this volume, money launderers are moving illicit funds — and current systems are blind to it.

Here's why: rule-based systems analyze each transaction *in isolation*. They flag a single ₹10 lakh transfer. But what they completely miss is when a launderer splits ₹1 crore into ten ₹9.9 lakh chunks, routes them through five mule accounts, and reassembles the money — all within 30 minutes.

RBI's 2023-24 report records over ₹36,000 crore lost to bank fraud. The reason? Fraud is a **network crime**. You cannot detect it by looking at individual transactions. You need to see the graph.

That's exactly what TraceX does."

---

## SECTION 2: SOLUTION + HOW IT WORKS [0:30 – 2:30]

**[VISUAL: Architecture diagram (from D3). Animate layers appearing one by one.]**

**NARRATION:**

"TraceX is a graph-first, ML-powered fund flow intelligence system. Let me walk you through how it works.

**[Point to Layer 1]**

Step one: Data Ingestion. We ingest bank transaction data — whether it's the IBM Anti-Money Laundering dataset with 5 million real labelled transactions, custom CSV uploads, or daily End-of-Day feeds. The system auto-detects column formats and handles multi-currency conversion.

**[Point to Layer 3]**

Step two: Graph Construction. Every account becomes a node. Every transaction becomes a directed edge. We build a NetworkX directed multigraph — the same data structure used by financial intelligence units worldwide. This is the critical difference: we model relationships, not just transactions.

**[Point to Layer 4 — Pattern Detectors]**

Step three: Five custom fraud pattern detectors. Each one targets a specific RBI-defined laundering typology:

- **Layering:** We trace multi-hop chains using temporal chain extraction. If money flows through 3 or more accounts within 30 minutes with decreasing amounts — that's layering.
- **Round-tripping:** We use Johnson's algorithm — the mathematically optimal cycle detection method — to find circular money flows where 85% or more of the amount returns to origin.
- **Structuring:** We detect amounts clustered just below the ₹10 lakh CTR threshold. Three or more near-threshold transactions from the same account trigger an alert.
- **Dormancy:** We identify accounts inactive for 180+ days that suddenly burst with activity at 10× their historical average.
- **Profile mismatch:** We compare actual transaction volumes against declared income and peer groups using z-score analysis.

**[Point to Layer 4 — ML]**

Step four: Our ensemble ML pipeline. We extract 29 features per account — graph structural features like PageRank and betweenness, temporal features like transaction velocity, and behavioural features like channel entropy and night-time transaction ratios.

These feed into two models working together:
- Isolation Forest for unsupervised anomaly detection — works from day one, no labels needed.
- XGBoost trained on 5,100 labelled laundering cases — GPU-accelerated on CUDA — achieving an F1 score of 0.683 and a cross-validated AUC-ROC of 0.933.

The ensemble combines ML scores at 30% weight, pattern detector flags at 40%, and graph centrality at 30% — producing a final risk score from 0 to 100 for every account.

**[Point to Layer 5]**

Step five: The investigator sees everything through our 8-page Next.js dashboard with Neo4j-style graph visualization. They can trace the complete journey of any fund, discover accomplice networks via Random Walk, and generate FIU-IND compliant Suspicious Transaction Reports with one click."

---

## SECTION 3: DEMO WALKTHROUGH [2:30 – 4:00]

**[VISUAL: Switch to live screen recording of the application running at localhost:3000]**

**NARRATION:**

"Let me show you TraceX running on real data.

**[Show Ingest page]**

I'm uploading our test dataset — 8,000 transactions across 312 accounts with embedded fraud patterns. Watch what happens.

**[Upload CSV, show success message]**

The system just parsed the CSV, built a directed multigraph, extracted 29 features for every account, trained both ML models, ran all 5 pattern detectors, computed risk scores, and classified roles — all in under 10 seconds.

**[Navigate to Dashboard]**

Here's the dashboard. We can see [X] accounts flagged, risk distribution across the network, and our top priority alerts ranked P1 through P4. The model metrics panel shows our XGBoost performance — precision 0.778, recall 0.609.

**[Navigate to Graph Explorer]**

This is the graph explorer — Neo4j-style visualization. Each node is an account. Red means critical risk, orange is high, yellow medium, green low. The shapes tell you roles — triangles are SOURCES sending money out, diamonds are MULES passing it through, inverted triangles are SINKS accumulating.

Let me click on this high-risk node... and now I can see its ego-graph — its complete neighborhood of relationships.

**[Show Pattern view]**

Switching to pattern view — here's a detected layering chain. You can see money flowing through 5 accounts with decreasing amounts at each hop. This is exactly what a manual investigator would spend hours tracing through CBS logs.

**[Navigate to Patterns page]**

The patterns page shows all detections organized by type. We have layering chains, round-trip cycles, structuring clusters, dormant accounts, and profile mismatches — each with severity ratings and specific evidence.

**[Navigate to Evidence page]**

Finally, the evidence generator. I select an account, choose the detected pattern, add investigator notes... and one click generates a complete FIU-IND Suspicious Transaction Report. PDF with SHA-256 integrity hash — ready for regulatory submission."

---

## SECTION 4: BUILT vs. PLANNED [4:00 – 4:30]

**[VISUAL: Two-column slide showing Built ✅ vs. Planned ⬜]**

**NARRATION:**

"Let me be completely transparent about what's built versus what's planned.

Everything I just showed you is **working code** — not slides. Five pattern detectors, two ML models, ensemble scoring, interactive graph visualization, evidence generation — all running on real data.

What's planned for production: integration with actual CBS and NEFT gateways, streaming via Kafka instead of batch processing, Graph Neural Networks for deeper structural learning, and digital signature certification for legal STR compliance.

Our architecture — with adapter patterns and event bus abstraction — is explicitly designed so that each production upgrade is a **module swap**, not a rewrite."

---

## SECTION 5: TEAM [4:30 – 5:00]

**[VISUAL: Team slide with photos and roles]**

**NARRATION:**

"We're Team TraceX from [Institute Name].

[Name 1] built our ML pipeline — the 29-feature extractor, ensemble scoring, and GPU-accelerated XGBoost tuning.

[Name 2] engineered the graph engine — NetworkX with Johnson's cycles, temporal BFS, and the complete FastAPI backend with 25+ endpoints.

[Name 3] created the investigator dashboard — 8 pages of Next.js with Cytoscape.js graph visualization.

[Name 4] handled data engineering — the synthetic test generator, IBM AML dataset analysis, and FIU-IND compliance research.

We built TraceX because we believe that ₹36,000 crore in annual bank fraud is not acceptable — and that the technology to stop it exists. We just need to deploy it correctly.

Every rupee leaves a trail. TraceX makes it visible.

Thank you."

**[VISUAL: End slide with GitHub link, demo link, contact email]**

---

## DELIVERY TIPS

1. **Speak with confidence, not speed.** 5 minutes is enough if you don't waste words.
2. **Show the running system** during the demo — not screenshots pasted on slides.
3. **Use numbers:** "29 features, 5 detectors, 5 million transactions, 0.933 AUC" — specifics build credibility.
4. **Acknowledge limitations honestly.** Evaluators respect "we know this needs Kafka for production" more than claiming it's production-ready when it's not.
5. **End strongly.** The last 10 seconds should be memorable — "Every rupee leaves a trail."
