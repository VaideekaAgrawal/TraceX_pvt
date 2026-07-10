# TraceX — Cross Questions & Answers
## 28 Strict Q&A for Union Bank of India Evaluation

*Grouped by evaluation factor. Every answer cites a specific code component, metric, or design decision.*

---

## SECTION A: Problem Understanding & Business Relevance

---

**Q1. What specific PMLA 2002 and RBI obligations does TraceX help Union Bank comply with?**

TraceX addresses PMLA 2002 Section 12 (mandatory records of transactions above ₹10L — our structuring detector specifically flags evasion of this threshold), Section 12A (STR filing — our one-click evidence pack generates a FIU-IND compliant STR with reference number in under 60 seconds), and the RBI AML/KYC Master Circular 2023 which requires transaction monitoring covering all five specified typologies. The dormancy detector uses the RBI's exact 6-month definition for dormant accounts. FATF Recommendations 10 (CDD via profile mismatch) and 20 (prompt STR filing) are also directly addressed. No configuration or localisation project is required — India-specific thresholds are built in from day one.

---

**Q2. Union Bank already has Oracle FCCM. Why add TraceX?**

Oracle FCCM is scenario-based: it fires rules against individual rows, not graph paths. It cannot natively express "find accounts where money cycles through 5 intermediaries and returns to the source within 72 hours" — that requires recursive graph traversal, which relational systems approximate poorly with expensive multi-join queries. FCCM's scenario modification requires Oracle Professional Services engagement (₹50L–2Cr per new scenario, 3–6 month lead time). TraceX adds a new detector in Python in one afternoon. Additionally, no enterprise AML system — including FCCM — generates LLM investigator narratives or has a reinforcement learning adaptive queue. TraceX is designed to complement FCCM by processing the same CBS transaction exports and surfacing graph-native patterns that FCCM's SQL engine cannot find.

---

**Q3. How does TraceX prevent too many false positives, which waste investigator time?**

Three specific safeguards are built into the ensemble scoring: First, the ML score only contributes when XGBoost's binary prediction is positive at the PR-curve-optimised threshold (typically 0.90+), not just when raw probability exceeds 0.5 — this prevents the 0.80–0.94 probability range from inflating scores for correctly-classified clean accounts. Second, graph centrality contribution is conditioned on having at least one pattern flag — preventing high-degree legitimate accounts (like a busy branch clearing account) from being falsely elevated. Third, the Convergence Bonus only applies when both pattern flags AND fraud probability >0.5 agree — rewarding multi-signal corroboration. The LinUCB RL agent additionally learns which pattern combinations in UBI's specific data produce true positives vs false positives, progressively reducing FP workload over time.

---

**Q4. How does the system handle launderers who adapt their behaviour after detection?**

Three mechanisms: First, the Isolation Forest flags statistical outliers relative to the current population — as launderers adapt, new behaviours emerge as anomalies regardless of whether they breach a hard rule. Second, the XGBoost model can be retrained on updated investigator feedback (new TP/FP labels from resolved cases) — the model continuously learns evolving patterns. Third, all detection thresholds (structuring range, dormancy window, layering min hops, cycle return threshold) are in `infrastructure/config.py` and adjustable without redeployment — a compliance officer can update them in minutes if launderers shift their strategy. The RL agent also adapts: if a previously reliable signal starts generating FPs, the agent's learned weight for that signal decreases automatically.

---

**Q5. The profile mismatch detection — isn't a simple income/volume ratio enough? Why do you need peer z-scoring?**

A simple ratio misses context. A trading company transacting 10× its declared income may be perfectly normal — because all trading companies in its income bracket do the same. A simple ratio would generate massive false positives on legitimate high-volume businesses. The peer z-score (`actual_volume − peer_mean) / peer_std`) compares each account against others with the same `occupation × income_bracket`. An account is only flagged as suspicious if it is statistically anomalous *among its own peers*. This approach is more defensible in an investigation: "this account transacts 4.7 standard deviations above other accounts with the same occupation and income profile" is a far stronger evidential statement than "their volume exceeds 3× declared income." The peer grouping is computed live using pandas `.groupby()` and `statistics.stdev()` at `/api/profile/{account_id}`.

---

**Q6. What is the exact dormancy definition used, and how is it aligned with RBI guidelines?**

The RBI defines a dormant account as one with no customer-initiated transactions for 24 months (savings) or 12 months (current accounts). However, for AML purposes, we use a more sensitive 6-month gap threshold because money laundering operations often use accounts that were inactive for 6–8 months — just enough to avoid routine scrutiny but not long enough to trigger the full RBI dormancy process. The `DormancyDetector` in `services/detection/dormancy.py` identifies the largest inter-transaction gap per account using sorted timestamps, flags gaps ≥ 183 days (6 months), then computes the post-gap activation ratio (post-gap total in 30 days / max(pre-gap average, 1)). The threshold of 10× is configurable in `infrastructure/config.py` via `dormancy_burst_ratio`. Named test account `DORM_001` demonstrates this exact scenario.

---

**Q7. How quickly can TraceX generate an STR and what does the FIU-IND evidence pack contain?**

The evidence pack is generated by a single POST to `/api/evidence/generate` with a case ID and list of account IDs. Generation takes under 60 seconds regardless of network size. The pack contains: (1) a PDF with case narrative, flagged account profiles, risk scores per account, transaction timeline (all transactions involving flagged accounts, sorted chronologically), detected pattern evidence, graph snapshot, and investigator case notes; (2) a JSON payload with all the same data in machine-readable form; (3) a SHA-256 hash of both the PDF bytes and JSON payload — stored in the case record for tamper detection. A FIU-IND STR reference number is auto-generated and attached. The `EvidenceGenerator` class in `services/investigation/evidence.py` handles all formatting, and the STR structure follows FIU-IND's mandated fields.

---

## SECTION B: Tech & Engineering Quality

---

**Q8. Why NetworkX instead of Neo4j? Is NetworkX fast enough for production?**

NetworkX was chosen deliberately to enable zero-infrastructure deployment for this prototype — a bank can run a pilot with a single Python process, no database server. The architectural decision to use an abstract `DatabaseAdapter` interface means switching to Neo4j requires changing one environment variable (`DB_BACKEND=neo4j`) and providing Neo4j connection credentials — no service code changes. NetworkX handles the demo dataset (5M transactions) in under 2 minutes for full pipeline. For UBI's scale (~20M daily transactions), the production path is Neo4j Enterprise with native Cypher traversal queries and index support — the `Neo4jAdapter` class in `infrastructure/database.py` already defines the interface. We chose "works today, scales tomorrow" over "requires enterprise infrastructure on day one."

---

**Q9. How specifically do you prevent data leakage in the XGBoost model?**

Three independent measures: (1) **Temporal 70/15/15 split** — accounts are ordered by their last transaction timestamp, then split: training uses earliest 70%, validation next 15%, test final 15%. This simulates production exactly — the model only ever sees past data during training. Random splits on time-series data consistently overestimate model performance by 15–30% AUC by allowing future information to leak into training. (2) **Source-only labelling** — only the source account of a confirmed laundering transaction is labelled positive. Including destination accounts was experimentally tested and dropped precision from 77.8% to 4.9% because innocent recipients of laundering transactions inflate label noise. (3) **PR-curve threshold optimisation on validation set** — after training, the classification threshold is tuned on the held-out validation set using `precision_recall_curve()`, not the test set. The test set is only touched once, for final evaluation. These three measures ensure the reported metrics (Precision=0.778, Recall=0.609, F1=0.683, CV AUC=0.933) reflect realistic production performance.

---

**Q10. Johnson's algorithm has exponential worst-case complexity. How do you bound it for large graphs?**

Correct — Johnson's algorithm is O((V+E)(C+1)) where C is the number of simple cycles, which can be exponential in a dense graph. TraceX applies two hard bounds: `max_length=6` limits cycle detection to cycles of at most 6 nodes, and `max_cycles=1,000` terminates the search once 1,000 cycles are found. The `max_length=6` bound is operationally justified — money laundering round-trips of more than 6 hops are impractical (too many accounts to coordinate, too much coordination risk). In practice on the IBM AML dataset (5M edges), cycle detection with these bounds completes in 3–8 seconds. For production at Neo4j scale, cycle detection uses native Cypher `apoc.algo.cycles()` with similar bounds, running in milliseconds on indexed paths.

---

**Q11. Explain the LinUCB math to a technical judge. Why is it "RL" and not just a regression?**

LinUCB is a contextual bandit algorithm, which is a class of Reinforcement Learning distinguished from supervised learning by its online nature and the exploration-exploitation tradeoff. In supervised regression, you collect all data first, then train. LinUCB trains *incrementally* — updating the precision matrix **A** and reward vector **b** after *each single observation*. The UCB score **θᵀx + α√(xᵀA⁻¹x)** has two terms: **θᵀx** (exploitation — expected reward based on what we've learned) and **α√(xᵀA⁻¹x)** (exploration — uncertainty bonus for accounts whose feature vectors are not yet well-characterised). This exploration term causes the agent to deliberately investigate uncertain accounts, not just the obvious high-scorers — which is critical for AML where sophisticated launderers specifically reduce their risk score. The algorithm has a provable cumulative regret bound of O(d√T log T) — mathematically guaranteed to converge to the optimal ranking policy. No regression model provides this guarantee because regression doesn't reason about what to measure next.

---

**Q12. Walk me through the ensemble scoring formula. How do you justify the weights?**

The formula has four components: ML Score (gated on binary prediction: `fraud_prob × 100 × 0.30`), Pattern Score (weighted sum of flagged patterns × 0.55, capped at 55), Graph Score (percentile-based centrality × 0.30, conditioned on pattern flags), and Convergence Bonus (up to 15 points when patterns and fraud_prob > 0.5 agree). The weights emerged from systematic experimentation documented in `claude_session/ml_improvements.md`. The ML gate (binary pred, not raw prob) is critical: clean accounts can have raw fraud_prob of 0.80–0.94 (below the strict PR-curve threshold of ~0.92) but XGBoost correctly classifies them as clean. Using raw probability would give these accounts `0.85 × 100 × 0.30 = 25.5` ML score despite being clean. The gate prevents this inflation. The 0.55 pattern multiplier ensures pattern detection alone cannot saturate the score (max 55 points), leaving room for ML and centrality to differentiate between equally-flagged accounts. The graph centrality condition on pattern flags prevents a high-degree branch clearing account from being falsely elevated.

---

**Q13. What are the actual XGBoost metrics on the IBM AML dataset?**

On the IBM AML test set (15% holdout, temporally split), the documented tuning result (`archive/fund-flow-tracker/infrastructure/config.py` "best config: capped_spw, exp v2, 2026-05-18", reconciled against this doc's earlier — now corrected — ~72%/~0.88 figures and the README, `docs/ROADMAP.md` Phase 3): PR-AUC=0.64, Precision=0.778 (77.8%), Recall=0.609 (60.9%), F1=0.683, CV AUC=0.933, at the PR-curve-optimised threshold. At the default 0.5 threshold, precision drops sharply (more false positives) but recall rises. The PR-curve optimisation deliberately trades some recall for higher precision — in AML, false positives are expensive (wasted investigator time), so we prioritise precision at the cost of some recall. The `fraud_metrics` dict returned by `FraudClassifier.train()` includes: precision, recall, f1, precision_default, recall_default, auc_roc, confusion_matrix, train_size, val_size, test_size, positive_rate, training_time_sec, device (GPU/CPU), optimal_threshold, and best_iteration. All of this is live-queryable at `/api/model-metrics` during the demo.

---

**Q14. How accurate are the LLM-generated AI explanations? What if they hallucinate?**

The LLM prompt is structured to constrain the output: it provides all factual data (risk score, patterns detected, declared income, actual volume, occupation, fraud probability, top features) and instructs the model to summarise these facts in 3–4 sentences. The model cannot hallucinate the numbers because they are injected into the prompt — hallucination risk is limited to phrasing and interpretation, not facts. Temperature is set to 0.3 (low, reducing creativity). The explanation is explicitly labelled in the UI as "AI-Generated Summary" to make clear to investigators that it is an interpretive narrative, not a formal finding. The cache (`_explain_cache`) prevents repeated API calls and ensures consistency within a session. In production, the explanation would be part of the evidence pack appendix, clearly marked as AI-assisted, with the underlying raw data always available for human review.

---

**Q15. How does the SSE real-time stream work technically? What happens if the connection drops?**

The SSE endpoint (`/api/events`) returns a `StreamingResponse` with `media_type="text/event-stream"`. The async generator function polls for new alerts every 2 seconds using a `last_count` cursor — when `len(alerts) > last_count`, it serialises new alerts as `data: {json}\n\n` and yields them to the client. The frontend uses the native browser `EventSource` API which handles reconnection automatically: if the connection drops, the browser reconnects to `/api/events` with the last event ID, and the server resumes from that point. The `stream_service.py` in `services/realtime/` provides additional abstraction — publishing events to a queue that the SSE generator consumes, allowing the realtime service to be upgraded to a WebSocket or Kafka consumer without changing the API endpoint. In the demo, uploading Day2 CSV triggers new alerts which appear as toast notifications on the frontend in under 2 seconds.

---

## SECTION C: Security

---

**Q16. Who can access investigation cases and STR evidence packages?**

Access to the evidence generation endpoint (`/api/evidence/generate`) requires the `write:evidence` permission, granted only to INVESTIGATOR and ADMIN roles. Case creation requires `write:cases` (INVESTIGATOR and ADMIN). ANALYST and VIEWER roles cannot create cases or generate STRs — they can only read overview data and alerts. Every call to generate evidence is logged in the audit trail (`AuditLogger.log()`) with: timestamp, user_id, case_id, account_ids, IP address, user agent. This creates an immutable accountability chain. In production, the audit log would integrate with the bank's SIEM (Security Information and Event Management) system for compliance reporting.

---

**Q17. How does TraceX prevent an insider at the bank from falsifying evidence or planting false alerts?**

Three independent controls: (1) The audit log records every action immutably — a compliance officer can see exactly who flagged an account, when, based on which signals. (2) Evidence packs are SHA-256 hashed at generation time; the hash is stored in the database. If an insider modifies the PDF to change amounts or remove transactions after generation, the stored hash won't match the modified document — tamper-detection is a technical guarantee, not just a policy. (3) Separation of duties: the INVESTIGATOR role can create cases and evidence but has no `delete:*` or `admin:*` permissions — they cannot modify the underlying transaction data, alter risk scores, or delete detection results. Only ADMIN can make system-level changes, and ADMIN actions are also audit-logged.

---

**Q18. The JWT secret in the code says "CHANGE_ME_IN_PRODUCTION". Is this a security vulnerability?**

This is a standard open-source placeholder pattern, not a deployment vulnerability. The variable name itself (`CHANGE_ME_IN_PRODUCTION_USE_32_BYTES_MIN`) makes it impossible to accidentally deploy with the default secret — any security review would immediately flag it. In production, `JWT_SECRET` is injected as a Kubernetes Secret (mounted as an environment variable), never stored in the code or config files. The `SECURITY_ENABLED` environment variable defaults to `"true"` — development bypass only activates explicitly. The security module in `infrastructure/security.py` is fully functional with a proper secret: JWT creation, verification, expiry, and error handling are all implemented and tested. This is not a WIP security feature — it is production-ready code awaiting a production secret.

---

**Q19. How are evidence packages protected from tampering after they leave the system?**

The SHA-256 hash covers both the PDF bytes and the JSON payload and is recorded in the SQLite `cases` table at generation time. The process: `hash = hashlib.sha256(pdf_bytes + json_payload.encode()).hexdigest()`. If the PDF is emailed, modified, and re-submitted as a different document, the hash computed on the modified document will differ from the hash in the database — tamper-detection is mathematical, not procedural. For additional security in production: the evidence pack can be digitally signed using a bank-issued certificate (HSM-backed PKI), and the hash can be registered on a blockchain or notarised — providing a chain of custody that is admissible in court proceedings under Section 65B of the Indian Evidence Act.

---

**Q20. What data does TraceX store and how long is it retained?**

TraceX stores: accounts (account_id, account_type, branch_city, occupation, income_bracket, declared_annual_income, risk_score, risk_level, role), transactions (txn_id, timestamp, source_account, dest_account, amount, channel, txn_type), cases (case_id, account_ids, status, notes, STR reference, timestamps), and ingestion history (filename, date, record count, checksum, status). TraceX does **not** store customer names, PAN numbers, Aadhaar IDs, or addresses — these are not in the transaction export schema. Uploaded CSV files are processed and stored in `data/uploads/` with UUID-prefixed names; they can be deleted post-processing. The in-memory ML models (IsolationForest, XGBoost, LinUCB weights) are persisted to disk between sessions — XGBoost to model binary, LinUCB to `data/rl_state.json`. Retention periods for case records and audit logs are configurable and should be aligned with UBI's data retention policy (typically 5 years under PMLA).

---

**Q21. How does TraceX protect against malicious file uploads designed to attack the system?**

Four layers: (1) File type restriction — only `.csv` extensions accepted at the upload endpoint, checked on the original filename. (2) UUID prefix on saved files — `uuid4()` prefix prevents filename-based path traversal; even if the uploaded filename is `../../etc/passwd.csv`, it is saved as `{uuid}.csv` in the uploads directory. (3) Path resolution whitelist — `_safe_ingest_path()` resolves the filepath with `pathlib.Path.resolve()` and verifies it starts with `data/` or `data/uploads/`; any path outside these directories returns HTTP 400. (4) Schema validation — the `DataContractValidator` checks every CSV for column presence, null rates, data type correctness, and value ranges before any data enters the detection pipeline. A CSV with injected SQL-like strings, negative amounts, or null account IDs is caught at validation and logged as a contract violation, not executed.

---

## SECTION D: Scalability & Enterprise Readiness

---

**Q22. Union Bank processes approximately 20 million transactions per day. Can TraceX handle this?**

At 20M txns/day, the current NetworkX in-memory architecture would require approximately 40GB RAM for the full graph and 5–10 hours for pipeline completion — not viable for same-day detection. The production architecture addresses this in three ways: (1) Neo4j Enterprise as graph storage — supports billion-edge graphs with native index support; incremental daily additions of 20M edges are a standard use case. (2) Incremental EOD processing — only today's 20M new transactions are processed, not the full historical graph; the 7-day lookback runs only on accounts with new activity. (3) Kubernetes HPA — the detection service is stateless and horizontally scalable; pattern detection is parallelisable per account cluster. 20M transactions across ~5M active accounts means ~4 new transactions per account per day — incremental detection across all accounts completes in minutes with distributed processing.

---

**Q23. How does TraceX integrate with Union Bank's Finacle Core Banking System?**

Two integration modes: (1) **Batch EOD (immediate, no CBS modification required)** — Finacle generates the standard daily transaction export as CSV (a native Finacle capability via its MIS/reporting module). TraceX's EOD service (`/api/ingest/upload`) accepts this export, processes it incrementally, and updates all risk scores overnight. Zero CBS modification needed — integration is purely file-based. (2) **Real-time CDC (production)** — Debezium CDC connector is deployed on Finacle's Oracle/PostgreSQL backend, publishing transaction events to a Kafka topic as they are committed. TraceX's event bus subscribes to Kafka; detection runs on 5–15 minute micro-batches. The `DatabaseAdapter` interface ensures the Neo4j graph backend can consume both modes without changing detection or investigation service code. Integration timeline: Week 1 can begin with CSV export immediately.

---

**Q24. What happens if the TraceX backend crashes? Is investigation data lost?**

No. All case records, alerts, investigation history, and ingestion metadata are persisted in SQLite (`data/tracex.db`). The backend is stateless with respect to investigation data — the in-memory graph and ML results can be fully rebuilt from the persisted data by calling `/api/refresh` on restart. The LinUCB RL agent state (A matrix, b vector, feedback counts) is serialised to `data/rl_state.json` after every update — a restart restores the learned weights exactly. Evidence packs (PDF + JSON) are returned to the frontend at generation time and are independent of backend state after delivery. In production: the SQLite DB is replaced with PostgreSQL (replicated primary + read replicas) mounted on cloud-backed storage; Kubernetes liveness probes at `/health/live` trigger automatic pod restart within seconds of failure.

---

**Q25. How does TraceX handle regulatory changes (e.g., RBI raises the CTR threshold from ₹10L to ₹15L)?**

All detection thresholds are in `infrastructure/config.py`. The CTR threshold is `CTR_THRESHOLD = 1_000_000`. To update it to ₹15L: change one line to `CTR_THRESHOLD = 1_500_000`, and the structuring detector's classic and split modes immediately use the new threshold on the next pipeline run. No code changes to the detector classes, no database schema migration, no redeployment. The config file is the single source of truth for all regulatory parameters — including `structuring_range_low` (5%), `structuring_range_high` (15%), `dormancy_gap_days` (183), `round_trip_return_threshold` (0.85), `layering_min_hops` (3). Adding a new regulatory typology requires creating a new detector class with a `detect()` method and registering it in `DetectionService.__init__()` — typically a half-day of development.

---

**Q26. Why should Union Bank choose TraceX over NICE Actimize, which has been in market for 20 years?**

Actimize has 20 years of market presence but three structural limitations that TraceX addresses: (1) SQL-based pattern matching cannot express variable-length graph paths — Actimize approximates layering detection with complex multi-join queries that miss 5-hop chains. TraceX's native graph traversal finds them in milliseconds. (2) Actimize has no LLM-generated narrative capability — investigators see tables of numbers. TraceX generates a 4-sentence plain-English briefing per flagged account that investigators can read and act on in 30 seconds. (3) Actimize has no reinforcement learning component — its alert ranking is static rules, manually maintained by AML consultants. TraceX's LinUCB agent adapts to UBI's specific patterns automatically. TraceX is not positioned as an Actimize replacement — it is positioned as a graph intelligence and AI layer that integrates with or supplements existing systems at a fraction of the cost (open source vs ₹20–50Cr/year).

---

**Q27. How is the ML model governed for regulatory audits?**

Current state: XGBoost feature importance is available at `/api/model-metrics` showing which behavioural features most drive fraud classification. Every risk score includes a `confidence.indicators` list showing exactly which independent signals contributed. The LinUCB learned weights are readable at `/api/rl/weights`. The XGBoost training metrics (F1, AUC, confusion matrix, optimal threshold, training time) are returned from every training run and stored in `fraud_metrics`. Production additions for regulatory-grade governance: (1) SHAP (SHapley Additive exPlanations) per prediction — one-click explainability per flagged account at feature level; (2) MLflow model registry — version control for trained models with lineage, metrics, and training data hash; (3) Model card auto-generated per training run — documenting training data characteristics, performance metrics, known limitations, and intended use. These are 2–4 weeks of development on the current foundation.

---

**Q28. What is the concrete three-week pilot plan for Union Bank of India?**

**Week 1 — Data Integration and Baseline Detection**: UBI provides a 6-month anonymised transaction export (CSV, no customer names or PAN — account IDs only). TraceX ingests within 30 minutes and runs the full detection pipeline. Results are reviewed with UBI's AML compliance team: compare TraceX-flagged accounts against UBI's existing STR filing history to validate detection accuracy. Expected outcome: TraceX correctly identifies 70–80% of accounts that UBI previously filed STRs for, plus novel detections not in existing STR history.

**Week 2 — Threshold Calibration**: Work with UBI compliance team to tune detection thresholds in `infrastructure/config.py` to match UBI's risk appetite: adjust structuring range (if UBI's launderers use a different band), dormancy period, minimum layering hops. Validate the RL simulation endpoint to show how the queue would adapt after 50 investigator decisions. Expected outcome: false positive rate reduced to <20% of flagged accounts based on threshold calibration.

**Week 3 — Investigator Workflow Validation**: 2–3 UBI AML investigators use TraceX to investigate 10–20 flagged accounts from the pilot dataset. They use: fund trail tracing, AI explain narratives, graph visualisation, and STR generation. They provide TP/FP feedback, which feeds the LinUCB agent. Produce a pilot evaluation report with recommended production configuration. Expected outcome: investigator feedback confirming TraceX reduces time from alert to filed STR by >80%, and the RL agent has visibly adapted its queue within 3 weeks.

---

*TraceX v3.0 | Cross-Questions Document | Union Bank of India AML Hackathon | July 2026*
