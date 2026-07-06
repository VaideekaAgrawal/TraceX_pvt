# TraceX — AML Intelligence System
## Winning Pitch for Union Bank of India Evaluation

---

> **"Every rupee leaves a trail. TraceX makes it impossible to hide."**

---

## THE PROBLEM — WHY THIS MATTERS TO UNION BANK OF INDIA

India loses over **₹1,00,000 crore annually** to money laundering. Union Bank of India, as one of India's largest public sector banks with thousands of branches and millions of daily transactions, carries a direct regulatory obligation under **PMLA 2002** and **RBI AML/KYC Master Circular** to detect, investigate, and report suspicious activity to FIU-IND.

Today, your AML team faces four brutal realities:

1. **Drowning in data** — millions of transactions per day, most clean, signal buried in noise
2. **Static rules, dynamic criminals** — every sophisticated launderer knows the ₹10L CTR threshold; they transact at ₹9.5L
3. **No graph visibility** — no investigator can trace a 7-hop layering chain through account ledgers alone
4. **Evidence takes days** — by the time an STR is filed manually, the money has moved on

**Non-compliance cost**: PMLA penalties range from **₹1 crore to ₹10,000 crore**. Reputational damage is incalculable.

---

## THE SOLUTION — TRACEX

TraceX is an **intelligent, graph-first, ML-powered, AI-explained Anti-Money Laundering platform** built specifically for India's regulatory framework. It detects all five mandated AML typologies, learns from your investigators, and generates court-ready FIU-IND evidence packages in one click.

### Three Pillars

```
┌─────────────────────────────────────────────────────────────────┐
│  PILLAR 1: GRAPH INTELLIGENCE                                   │
│  NetworkX MultiDiGraph — every account is a node, every         │
│  transaction a directed edge. 7-hop layering chains found in    │
│  milliseconds. Fund trail tracing in any direction.             │
├─────────────────────────────────────────────────────────────────┤
│  PILLAR 2: DUAL MACHINE LEARNING                                │
│  Isolation Forest (unsupervised, Day-1 ready) + XGBoost         │
│  (supervised, GPU-accelerated, trained on 5,100 labelled        │
│  IBM AML cases). Ensemble scoring across ML + patterns +        │
│  graph centrality.                                               │
├─────────────────────────────────────────────────────────────────┤
│  PILLAR 3: AI EXPLAINABILITY + RL ADAPTIVE QUEUE               │
│  LLM generates plain-English investigator briefings per         │
│  account. LinUCB Contextual Bandit learns from every            │
│  TP/FP verdict — queue gets smarter every shift.               │
└─────────────────────────────────────────────────────────────────┘
```

---

## THE FIVE MANDATED AML TYPOLOGIES — ALL DETECTED

| # | Typology | TraceX Detection Method | Algorithm |
|---|----------|------------------------|-----------|
| 1 | **Layering** — rapid multi-hop transfers | BFS chain detection (2 passes: intra-day + 72h), amount decay ratio check | Graph traversal, configurable min hops |
| 2 | **Round-Tripping** — circular transactions | Johnson's cycle algorithm on 72h temporal slices, ≥85% return amount | Cycle detection, max depth 6 |
| 3 | **Structuring** — below ₹10L CTR threshold | Classic (5–15% below ₹10L across ≥3 txns) + Split (sum-to-threshold) + Isolation Forest rolling 30-day | Hard rule + unsupervised ML |
| 4 | **Dormant Activation** — 6+ month gap | Temporal analysis: last txn before gap vs post-gap burst, activity ratio | Time-series comparison, RBI definition |
| 5 | **Profile Mismatch** — declared vs actual | Income/volume ratio (>3×) + peer group z-score (same occupation × income bracket) | Statistical outlier detection |
| + | **Fan-Out/Fan-In** | Out-degree (>10 recipients, short window) + in-degree convergence | Graph degree analysis |

---

## LIVE DEMO WALKTHROUGH — WHAT JUDGES WILL SEE

| Step | Action | What It Proves | Judge Improvement |
|------|--------|---------------|-------------------|
| 1 | Open `/health` live — show per-service status, CP-05 gate, counters | Production-grade observability, not a toy | Improvement 1: Architecture |
| 2 | Upload Day1 synthetic CSV — pipeline runs in < 30s | Full detection pipeline end-to-end | Improvement 3: Synthetic Data |
| 3 | Dashboard: risk distribution, pattern counts, P1–P4 queue | Overview in seconds | Improvement 4: Real-Time Events |
| 4 | Graph Explorer: click LAY_A01 → show 5-hop chain with amounts ₹100→₹97→₹93→₹89→₹84 | Graph algorithm catches what SQL can't | Improvement 2: Algorithm Validation |
| 5 | Click GraphValidationDialog → show algorithm runtimes, chain counts, cycle counts | Proves correctness on known ground truth | Improvement 2 |
| 6 | Click RT_SRC_001 → see round-trip cycle complete in 3 hops, 94% return | Johnson's cycle detection live | Improvement 2 |
| 7 | Click "Explain with AI" on any CRITICAL account → LLM narrative in 3 seconds | No competitor does this | Improvement 5: USP |
| 8 | Upload Day2 CSV → DORM_001 appears as new CRITICAL alert in real-time toast | SSE stream delivers alert live | Improvement 4 + Improvement 8 |
| 9 | Profile page: income vs volume scatter → SHIFT_001 visible as extreme outlier | Behavioural drift detection | Improvement 8: New Patterns |
| 10 | RL Queue page: run simulation, watch weights update (layering → 0.61, structuring → -0.18 FP) | Feedback loop + adaptive learning | Improvement 7: Feedback Loop |
| 11 | Generate STR evidence PDF → show SHA-256 hash, FIU-IND reference number | 60-second STR vs 4-hour manual | Regulatory alignment |
| 12 | Industry comparison slide | TraceX vs FCCM vs Actimize | Improvement 6: Market Comparison |

---

## BUSINESS IMPACT

| Metric | Manual Process Today | TraceX |
|--------|---------------------|--------|
| Time to detect a 5-hop layering chain | Days / never | < 5 seconds |
| Investigations per analyst per week | 2–3 | 20–30 (P1–P4 prioritised) |
| STR generation time | 4–8 hours | < 60 seconds |
| False positive investigation rate | Industry norm: 85–97% of alerts | Multi-signal convergence gate reduces noise |
| AML typology coverage | Partial (rule-based) | All 5 mandated + fan-out/fan-in |
| Audit trail | Manual log | Automated RBAC + audit logger |
| System learning | Never improves | LinUCB learns from every investigator decision |
| Real-time alerting | Next morning (EOD) | SSE stream — alerts in < 2 seconds |

---

## REGULATORY ALIGNMENT

| Regulation | Requirement | TraceX Feature |
|-----------|-------------|---------------|
| PMLA 2002, S.12 | Record all txns above ₹10L | Structuring detector flags evasion of this threshold |
| PMLA 2002, S.12A | Report suspicious transactions to FIU-IND | One-click STR PDF + JSON + SHA-256 hash |
| RBI AML/KYC Master Circular | Transaction monitoring covering 5 typologies | All 5 typologies + fan-out detected |
| RBI Dormant Account Circular | Flag accounts inactive 6+ months, suddenly activated | DormancyDetector with RBI's 6-month definition |
| FATF Recommendation 10 | Know-Your-Customer / profile monitoring | ProfileMismatchDetector with peer z-scoring |
| FATF Recommendation 20 | Prompt STR filing | 60-second evidence pack generation |
| FIU-IND STR Format | Specific field requirements | Auto-generated STR reference, pre-formatted fields |

---

## USP — WHAT NO COMPETITOR HAS

| Feature | NICE Actimize | Oracle FCCM | SAS AML | Temenos FCM | **TraceX** |
|---------|:------------:|:-----------:|:-------:|:-----------:|:----------:|
| Graph-native multi-hop traversal | ✗ SQL approx | Partial | Partial | ✗ 1-hop only | **✓ Native** |
| LLM-generated investigator narrative | ✗ | ✗ | ✗ | ✗ | **✓ OpenRouter** |
| RL adaptive investigation queue | ✗ | ✗ | ✗ | ✗ | **✓ LinUCB** |
| India-specific out-of-box config (₹10L CTR, FIU-IND) | After project | After project | After project | After project | **✓ Built-in** |
| Open source + auditable ML | ✗ Black box | ✗ Black box | ✗ Black box | ✗ | **✓ Full source** |
| Time to first detection | Weeks | Weeks | Months | Weeks | **✓ 30 seconds** |
| Peer group z-scoring | Simple ratio | Simple ratio | Yes | ✗ | **✓ Statistical** |
| SHA-256 tamper-proof evidence | ✗ | ✗ | ✗ | ✗ | **✓ Built-in** |
| Real-time SSE alert stream | ✗ | Partial | ✗ | ✗ | **✓ Built-in** |
| Annual cost | ₹20–50Cr | ₹10–30Cr | ₹15Cr+ | ₹5–15Cr | **✓ Open source** |

---

## THE RL ADVANTAGE — THE QUEUE THAT LEARNS

Every AML system ranks alerts with a static formula. TraceX's **LinUCB Contextual Bandit** breaks this paradigm:

- **State**: 16-dimensional feature vector per account (risk score, pattern flags, fraud probability, role, amount, counterparties, channel diversity)
- **Action**: priority rank in investigation queue
- **Reward**: +1.0 (investigator confirms TP), −0.3 (marks as FP)
- **Update**: O(d²) online — microseconds per investigator decision
- **Interpretable**: learned weight vector is human-readable (no black box)
- **Day-1 ready**: starts exploring with zero training data, improves continuously

After 100 investigator decisions, the agent has learned that **for your bank's specific data**, layering + high betweenness + MULE role is your strongest TP signal. No data scientist needed. No consultant engagement. **The system learns on the job.**

---

## THE ASK — PILOT PROPOSAL

**Week 1**: Share 6-month anonymised transaction export → TraceX detects patterns → compare against UBI's existing STR history for validation

**Week 2**: Threshold calibration with UBI AML compliance team → tune ₹10L structuring range, dormancy period, min hops to UBI's risk appetite

**Week 3**: 2–3 UBI investigators use TraceX live → collect TP/FP feedback → RL agent begins adapting → produce pilot evaluation report

**No CBS integration needed in Week 1.** A CSV export is sufficient. TraceX runs on a single server, requires no proprietary infrastructure, and can be deployed in a Docker container in under 10 minutes.

---

> **TraceX does not replace your investigators. It gives them superpowers.**
> One investigator with TraceX does the work of ten — and files a legally sound STR in the time it currently takes to open the case file.

---

*TraceX v3.0 | Team TraceX | Union Bank of India AML Hackathon | July 2026*
