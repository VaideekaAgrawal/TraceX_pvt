# TraceX — Comprehensive System Development Plan

*A consolidated specification for the AML investigation platform, merging `systemrequirements.txt` (the enterprise investigation workflow and 14 proposed features) with the actual state of the codebase (`README.md`, `CHANGES_PRODUCTION_UPGRADE.md`, `docs/RL_USP.md`, `docs/IMPROVEMENTS_STRATEGY.md`, `docs/pitch.md`, `docs/cross_questions.md`). This is a reference spec, not a sprint plan — every item carries its current build status and the reasoning behind its design, so it can be read top to bottom as "what the system is and should be," not "what to do this week."*

---

## 1. Vision & Positioning

**Product:** TraceX — a graph-first, ML-powered, AI-explained Anti-Money Laundering investigation platform for Indian banks.
**Tagline:** "Every rupee leaves a trail. TraceX makes it impossible to hide."
**Built for:** Union Bank of India, PS3 (Tracking of Funds within Bank for Fraud Detection). Positioned as *complementary to*, not a replacement for, an existing rules engine like Oracle FCCM — TraceX sits downstream of / alongside detection, focused on making investigation faster and more defensible, not on replacing the bank's existing alert-generation infrastructure.

**Why keep this framing:** it has already been stress-tested against ~28 hard judge/investor questions (`docs/cross_questions.md`) and a competitor comparison table (`docs/pitch.md`). Re-deriving positioning from `systemrequirements.txt` alone would discard that work and risk two documents disagreeing if a judge cross-references them.

### The Three Pillars

1. **Graph Intelligence** — NetworkX MultiDiGraph, multi-hop chain/cycle detection, fund-trail tracing, accomplice discovery.
2. **Dual Machine Learning** — Isolation Forest (unsupervised) + XGBoost (supervised), ensemble-scored with pattern flags and graph centrality.
3. **AI Explainability + Adaptive Prioritization** — LLM investigator narratives (OpenRouter) + a LinUCB contextual bandit that reprioritizes the investigation queue from investigator TP/FP feedback.

### Headline Narrative: "AI Investigation Orchestrator"

`systemrequirements.txt` itself proposes this at the bottom as the strongest USP: instead of presenting prioritization, explanation, similar-case retrieval, next-step recommendation, and narrative generation as separate buttons, frame them as **one system that actively drives the investigation** rather than a dashboard a human interprets unassisted.

**Why this should be the headline, not a footnote:** judges at a fintech fest see dozens of "dashboard + ML model" pitches. What's rare is a system that behaves like a junior analyst doing the first pass of triage. TraceX already has the three components needed to make this claim true today (the RL queue, AI explanation, and the rule-engine feedback loop) — it needs to be *presented and wired together* as one orchestrator loop rather than three independent features. That makes it a positioning and integration task more than new-build work — high leverage, low cost.

---

## 2. Ground Truth: Feature Status

This table reconciles the 14 features proposed in `systemrequirements.txt` against the real codebase, so the rest of this spec doesn't re-propose what already exists or claim novelty a technical judge could disprove by reading the repo.

| # | Feature | Status | Where it lives / notes |
|---|---|---|---|
| 1 | AI Case Prioritization Queue | **Built** | `services/rl/` — LinUCB contextual bandit, 16-dim feature vector, `/rl-queue` page. This *is* the feature described in the requirements doc. |
| 2 | Similar Historical Cases | **Net-new** | Needs a case-similarity index. |
| 3 | Timeline + Graph Synchronization | **Partial** | Both data sources exist (transaction timeline, graph API); bidirectional click-to-highlight UI sync not yet built. |
| 4 | Graph Filters | **Partial** | `/api/graph/filtered` exists; full filter set (risk threshold, amount, date range, channel, direction) needs verification against the requirements list. |
| 5 | Network Risk Score | **Partial** | Centrality, cycle counts, and SAR-adjacent data all exist but aren't packaged into one scored, explained number. |
| 6 | AI Investigation Copilot (conversational) | **Net-new** | Existing AI features are static "Explain this account" panels, not an open-ended chat interface. |
| 7 | Auto-generated Investigation Narrative | **Partial** | Per-account LLM explanation exists (`/api/explain/account/{id}`); a full case-level, multi-account, evidence-citing narrative does not. |
| 8 | Relationship Explorer (shared PAN/device/IP/etc.) | **Net-new** | `IMPROVEMENTS_STRATEGY.md` scopes a basic fuzzy-name entity-resolution version; the full shared-attribute graph (device, IP, employer, nominee) is unbuilt. |
| 9 | Graph Replay (animated time-based trail) | **Net-new** | Fund-trail BFS exists (static); a timeline-scrubber animated replay does not. |
| 10 | Watchlist Management | **Net-new** | `IMPROVEMENTS_STRATEGY.md` scopes a `WatchlistScreener` design; unbuilt. |
| 11 | Detection Feedback Loop | **Built** | Rule Engine DSL (11 primitives, Tier-2 composition, live dry-run at `/rules`) + RL reward signal from investigator verdicts. Covers most of what the requirements doc describes. |
| 12 | Audit Trail | **Partial** | Case-status changes and rule edits are logged in some form; a unified, queryable log covering *every* investigator action (alert opened, graph expanded, evidence bookmarked) is not one subsystem yet. |
| 13 | Investigation Path Recommendation | **Net-new** | Natural extension of the existing RL infrastructure. |
| 14 | Continuous Learning Feedback Loop (workflow-level) | **Roadmapped, not built** | `docs/RL_USP.md` already lays out this exact idea as later phases of the RL roadmap. |

### Other material findings (not in the requirements doc, found while grounding this plan)

- **No authentication is wired into any API route.** `infrastructure/security.py` has JWT/RBAC logic fully implemented, but it is never imported by `api/server.py`. This is the largest gap against the "admin/investigator roles" concern, and the most damaging kind of gap: the code sits right there, unused.
- **Two parallel case-tracking systems exist** — `InvestigationService`'s in-memory `CaseManager` and a separate SQLite `cases` table read directly by `/api/cases`. These need to be unified before case-assignment or case-management features are extended, or new features will attach to the wrong store.
- **k8s manifests already describe a target production architecture** (`fund-flow-tracker/k8s/api-deployment.yaml`): 3-replica rolling deployment, HPA (3→20 pods on CPU/memory), PodDisruptionBudget, non-root/read-only-root containers, Neo4j backend env vars, JWT secret env var, TLS ingress with rate limiting. None of this is wired to the running app (the Neo4j adapter is partial, JWT is unused) — but the target infra shape is already designed. The work is closing the gap between manifest and app, not designing scaling infra from scratch.
- **A basic CI pipeline exists** (`.github/workflows/ci.yml`): backend pytest, frontend lint + typecheck, build check. The lint/typecheck/build steps use `|| true` — they can never fail the build. Fine for a hackathon; must be tightened before "CI/CD" is cited as a maturity signal to investors.
- **Metric inconsistency:** `README.md` states XGBoost F1=0.683, AUC-ROC=0.933; `docs/cross_questions.md` states F1≈0.72, AUC-ROC≈0.88. These need to be reconciled before a judge who reads both documents notices.
- **Hardcoded JWT secret** (`JWT_SECRET = "CHANGE_ME_IN_PRODUCTION"`) — a genuine finding already flagged in `cross_questions.md` Q18, not hypothetical.

---

## 3. End-to-End Investigation Lifecycle

The lifecycle proposed in `systemrequirements.txt` —
`anomaly detection → alert → alert-to-case assignment → case management → L1 → L2 → resolve → report → feedback to detection → feedback to admin → admin review → changes implemented → improved detection → back to detection`
— is correct in shape; it matches how Actimize/FCCM/SAS structure their pipelines. Below is the same lifecycle with TraceX's existing components mapped onto each stage, so it reads as an architecture rather than just a flow.

```
┌────────────────────────────────────────────────────────────────────┐
│ 1. DETECTION ENGINE                                                 │
│    5 pattern detectors + IsolationForest + XGBoost + Rule Engine    │
│    DSL (11 primitives, Tier-2 composition) → ensemble risk score    │
└───────────────────────────────┬───────────────────────────────────┘
                                 ▼
┌────────────────────────────────────────────────────────────────────┐
│ 2. ALERT GENERATION                                                 │
│    Alert ID, type, risk score, confidence, timestamp                │
└───────────────────────────────┬───────────────────────────────────┘
                                 ▼
┌────────────────────────────────────────────────────────────────────┐
│ 3. AI PRIORITIZATION QUEUE  (LinUCB — built)                        │
│    Reorders the queue using risk + network + history + confidence   │
└───────────────────────────────┬───────────────────────────────────┘
                                 ▼
┌────────────────────────────────────────────────────────────────────┐
│ 4. CASE ASSIGNMENT & CASE MANAGEMENT  (needs store unification)     │
│    Single case store, investigator assignment, SLA timer, status    │
│    machine: New → Assigned → In Progress → Awaiting Review →        │
│    Escalated/Closed                                                 │
└───────────────────────────────┬───────────────────────────────────┘
                                 ▼
┌────────────────────────────────────────────────────────────────────┐
│ 5. L1 INVESTIGATION (TRIAGE)                                        │
│    Alert summary, AI explanation, customer snapshot, geo risk,      │
│    txn summary, simplified graph, AI case summary, previous alerts, │
│    similar historical cases, network risk score                     │
│    Decision: False Positive | Escalate to L2                        │
└─────────────┬─────────────────────────────────┬───────────────────┘
              │ False Positive                  │ Escalate
              ▼                                 ▼
┌───────────────────────────┐   ┌────────────────────────────────────┐
│ 6a. CLOSE CASE             │   │ 6b. L2 INVESTIGATION (DEEP)         │
│  Feedback → RL + Rule       │   │  Full graph (N-hop), full profile, │
│  Engine confidence update   │   │  relationship explorer, pattern    │
│  Audit trail updated        │   │  explanation, AI copilot, graph    │
└───────────────────────────┘   │  replay, evidence management,       │
                                  │  watchlist, auto-narrative           │
                                  └───────────────┬────────────────────┘
                                                   ▼
                                  ┌────────────────────────────────────┐
                                  │ 7. FINAL DECISION                   │
                                  │  FP | Monitoring | Escalate to      │
                                  │  Compliance | Generate SAR/STR      │
                                  │  (STR generation — built, FIU-IND   │
                                  │  PDF+JSON+SHA-256)                  │
                                  └───────────────┬────────────────────┘
                                                   ▼
                                  ┌────────────────────────────────────┐
                                  │ 8. FEEDBACK LOOP                    │
                                  │  → RL reward update (built)         │
                                  │  → Rule Engine confidence (built)   │
                                  │  → Admin review queue for new       │
                                  │    rules / edge cases               │
                                  │  → Detection engine improves        │
                                  └───────────────┬────────────────────┘
                                                   ▼
                                          back to (1) DETECTION ENGINE
```

**One structural change from the original cycle:** the AI Prioritization Queue is shown as its own explicit stage between "alert generated" and "case assignment," rather than folded into case assignment. This is deliberate — it's already built and independently demoable, so keeping it visible as its own pipeline stage (not buried inside case management) is what makes the RL story land as its own pitch beat, consistent with how `docs/pitch.md` already demos it as a standalone step.

---

## 4. Feature Specifications

Organized by where each feature sits in the lifecycle above, with description, rationale, and status.

### 4.1 L1 Triage Features

**Alert Summary, Customer Snapshot, Geographic Risk, Transaction Summary, Transaction Purpose** — standard fields any AML triage screen needs (alert ID/type/rule/priority/risk/time, KYC/PEP/sanction status, origin/destination jurisdiction risk, aggregated transaction stats, declared vs. actual purpose consistency). These are largely data-assembly tasks over data the system already computes; treat as UI composition rather than new backend work.

**AI Explanation of Alert ("why was this triggered")** — *Built.* Existing per-account LLM explanation panel. Facts are injected into the prompt (not generated), temperature is low, output is labeled "AI-Generated," and responses are cached. This is a genuinely strong existing answer to a question judges will ask (see §6, AI Guardrails).

**Simplified Money Flow Graph** — a reduced view (source → mule → sink, or source → customer → N beneficiaries) distinct from the full N-hop L2 graph. *Why it matters:* L1 triage needs a 10-second visual read, not an analyst-grade interactive graph — conflating the two views is a common UX mistake in this domain (over-showing detail at triage time slows investigators down rather than speeding them up).

**Previous Alert Summary** — count of prior alerts/SARs/false-positives on the account, risk trend. Needed to give L1 context on repeat offenders without requiring a full L2 dive.

**Similar Historical Cases** *(status: net-new)* — retrieves past investigated cases with matching transaction pattern, typology, or network topology, and shows their outcome (e.g., "93% similar to Case #2314 — SAR filed — layering through seven mule accounts"). **Design note:** build this on top of the same 16-dimensional feature vector already used by the RL bandit rather than standing up a separate feature-extraction pipeline — cosine similarity over that vector (or a lightweight embedding of the case narrative) is enough for a first version. **Why it matters:** reuses institutional knowledge, helps junior investigators, standardizes investigation quality across the team — a real productivity story, not just a demo trick.

**Network Risk Score** *(status: partial → needs packaging)* — a single score (distinct from individual customer risk) reflecting network-level danger: number of suspicious nodes, mule-account count, prior SARs in the network, sanctioned entities, graph centrality, density, money concentration. **Design note:** the underlying signals (centrality, cycle counts, SAR-adjacent data) already exist in the codebase — this is an aggregation-and-explanation task ("Network Risk: 95 — Reason: 8 linked mule accounts, 3 previous SARs, 2 sanctioned entities"), not new analytics. **Why it matters:** money laundering is a network crime; scoring only the individual customer misses organized activity, which is exactly the blind spot traditional AML systems have.

**Investigation Path Recommendation** *(status: net-new, but low-cost)* — suggests the next investigative action ("Expand 2-hop network — 84% of suspicious funds moved there," "Check device sharing — four accounts share one device," "Review previous SAR — destination already appeared in SAR #1834"). **Design note:** the same feature vector that ranks *which alert* to look at next (the RL queue) can be reused to rank *what action* to take next inside a case — this is a reuse of existing infrastructure, not a new model. **Why it matters:** guides less experienced investigators and reduces time-to-decision, directly addressing investigator-productivity concerns.

### 4.2 L2 Deep Investigation Features

**Full Network Graph Exploration (1/2/3/N-hop)** — interactive expand/collapse, timeline mode, filter by amount/date, highlight suspicious paths. Distinct from the L1 simplified view; this is the analyst-grade tool.

**Graph Filters** *(status: partial)* — `/api/graph/filtered` exists; the full filter list in `systemrequirements.txt` (suspicious-only, risk-threshold, amount-threshold, time-window, international, UPI-only, cash-only, direction, source/mule/sink role, prior-SAR) should be checked against what's implemented and extended where missing. **Why it matters:** graphs become unusable past a few hundred nodes — filtering is not a nice-to-have, it's what makes the L2 graph view usable at all at bank scale.

**Complete Customer Profile** — full KYC, beneficial owner, linked accounts/cards/loans/deposits, occupation, employer, income, expected-vs-actual behavior, historical risk score, prior SARs.

**Complete Transaction Analysis** — searchable, filterable, exportable transaction table (date, amount, channel, branch, product, account, direction, type).

**Historical Behaviour Analysis** — monthly spending, cash deposit trends, transfer trends, dormant-account activation, salary mismatch, velocity increase, seasonal trends.

**Relationship Explorer** *(status: net-new)* — automatically discovers hidden relationships via shared phone, email, PAN, Aadhaar, device ID, IP address, address, employer, nominee, introducer, or beneficial ownership, displayed as an interactive relationship graph. **Design note:** start with the cheap version already scoped in `IMPROVEMENTS_STRATEGY.md` — fuzzy name + branch + income match — before attempting device/IP correlation, which needs data that may not exist in the current synthetic dataset. **Why it matters:** this is the single feature most likely to produce a "no one else does this" reaction from judges, because it surfaces hidden mule networks that a transaction-only graph structurally cannot see — accounts with no direct transaction link but a shared device or introducer are invisible to pattern detectors that only look at money movement.

**Pattern Explanation** — evidence-backed explanation of a detected typology (e.g., circular transaction: A→B→C→A, four cycles, six hours, ₹42L, 96% confidence). Extension of the existing AI-explanation pattern to graph-structural findings rather than just account-level anomalies.

**AI Investigation Copilot** *(status: net-new, higher effort)* — a conversational assistant scoped to the current case ("show the largest outgoing transfers," "why was this account flagged," "which account is the mule," "compare with last month," "explain this circular transaction"). **Design note:** this needs a retrieval/tool-calling layer, not a prompt template — it must answer *arbitrary* questions grounded in live case data (graph state, applied filters, transaction subset). Budget it as a multi-day effort, not an afternoon extension of the existing explanation panels. **Why it matters — and why it's riskier than it looks:** it is the highest-risk feature from a hallucination/prompt-injection standpoint, because unlike the existing static explanations (which only relay server-computed facts), a copilot accepts open-ended natural-language input and may read attacker-controllable fields (transaction narrations, customer-declared purpose). See §6 (AI Guardrails) before building this — the existing guardrail pattern does not automatically transfer.

**Previous Alert & Case History (network-wide)** — not just the primary account, but every connected account's alert/SAR/sanction history (e.g., "Account C: SAR Filed," "Account D: Sanction Match"). Extends the L1 "previous alert summary" to the full network scope appropriate for deep investigation.

**Timeline Investigation & Timeline↔Graph Synchronization** *(status: partial)* — chronological reconstruction of fund movement, with clicking a timeline entry highlighting the corresponding graph edge (and vice versa). Both data sources already exist independently; the bidirectional UI sync is the missing piece. **Why it matters:** investigators currently switch between separate graph and timeline views to reconstruct the same fund flow — synchronizing them removes a real, measurable source of investigation friction, and it's specifically called out in the existing `docs/pitch.md` demo walkthrough, so building it de-risks that walkthrough.

**Graph Replay (animated time-based trail)** *(status: net-new)* — a timeline scrubber that animates the fund trail (deposit → split → layer → merge → withdrawal) instead of showing a static graph. **Design note:** mostly a frontend/visualization task since the underlying temporal transaction data already exists; natural to build after Timeline↔Graph sync since it's a superset of that capability. **Why it matters:** static graphs cannot convey *how* laundering unfolded over time — replay is what makes the mechanism visible, which matters both for investigator understanding and for a compelling live demo.

**Evidence Management** — bookmark transactions/accounts, highlight graph paths, pin evidence, attach documents, save graph snapshots, add notes, collaborate with other investigators.

**Watchlist Management** *(status: net-new)* — mark customers/accounts/devices/merchants/companies for enhanced future monitoring; future alerts touching a watchlisted entity get automatic priority. **Design note:** already scoped as a `WatchlistScreener` design in `IMPROVEMENTS_STRATEGY.md` — implement as written rather than re-designing. **Why it matters:** this maps directly to a real regulatory expectation (FATF Recommendation 10, ongoing due diligence / PEP-sanctions screening) that judges with a banking background are specifically likely to probe, per `cross_questions.md`.

**Auto-generated Investigation Narrative / Report** *(status: partial)* — a full case-level narrative (executive summary, findings, evidence, transactions of interest, network analysis, investigator notes, recommendation), editable before submission. **Design note:** the per-account version already handles the hard part (fact-injection prompting, low temperature to avoid hallucination) — extend it to a multi-account, evidence-citing case summary rather than building a second narrative pipeline. **Why it matters:** this is also what the STR/SAR evidence package needs, so it serves two purposes (report generation + regulatory filing support) from one build.

### 4.3 Cross-Cutting / Orchestrator-Level Features

**Detection Feedback Loop** *(status: built)* — investigator verdicts (false positive / confirmed SAR) feed back into both the Rule Engine (confidence adjustment per rule) and the RL bandit (reward signal). This is one of the strongest existing pieces of the system and should be foregrounded, not treated as plumbing.

**Continuous Learning Feedback Loop (workflow-level)** *(status: roadmapped)* — learning from investigator *behavior patterns* (common investigation paths, common evidence collected, common false-positive reasons), not just final verdicts, to proactively recommend workflows. `docs/RL_USP.md` already lays this out as later phases of the RL roadmap — reuse that roadmap rather than re-specifying it here.

**Audit Trail** *(status: partial)* — every investigator action (alert opened, graph expanded, evidence bookmarked, notes added, decision changed, escalation performed) logged as one unified, queryable, tamper-evident record. **Why it matters:** this is a regulatory requirement, not a nice-to-have — AML platforms are audited on whether investigation actions are reconstructable, and a partial/implicit log is a real gap in a bank pitch even though it's invisible in a demo.

**AI Investigation Orchestrator (framing layer)** — not a new component but the presentation of the above as one active loop: prioritize → explain → retrieve similar cases → recommend next step → update network risk as evidence appears → generate narrative → learn from the final decision. **Why this is worth calling out as its own item:** wiring these together (shared case context object, consistent UI placement, a visible "the system is reasoning" thread through L1 and L2) is what converts "a set of analytics tools" into "an investigation workflow product" — which is the more fundable story and the one `systemrequirements.txt` itself identifies as the strongest USP.

---

## 5. System Architecture & Non-Functional Concerns

### Admin / Investigator Roles (RBAC)
- **Current state:** `infrastructure/security.py` implements JWT + RBAC logic, but it is disconnected from the live API — effectively no auth exists on any route today.
- **Target design:** at minimum two roles (Investigator, Admin/Compliance), matching the L1/L2 split already designed into the workflow — Investigators triage and escalate; only Admin/Compliance closes cases, approves SAR filing, and edits detection rules.
- **Reasoning:** the role model falls directly out of the workflow already committed to (§3), so it needs wiring, not separate design work. **Open question for the user:** should L1 and L2 investigators be a distinct third role with a different UI surface (matching the requirements doc's implicit L1-analyst vs. L2-analyst split), or is the simpler two-role model sufficient?

### Case Assignment & Case Management
- **Current state:** split across two stores — `InvestigationService`'s in-memory `CaseManager` and a separate SQLite `cases` table read directly by `/api/cases`.
- **Target design:** one case store as the single source of truth, a status machine (New → Assigned → In Progress → Awaiting Review → Escalated/Closed), an SLA timer, and workload-based auto-assignment (assign to the investigator with the fewest open high-priority cases).
- **Reasoning:** every case-centric feature (assignment, SLA timers, audit trail, watchlist hits) needs one source of truth — building on the split store now compounds migration cost later. Even a naive workload-balancing rule beats manual assignment; don't over-engineer assignment logic before the store itself is unified.

### Graph Engine
- **Current state:** NetworkX in-memory MultiDiGraph — a deliberate, already-defended choice for hackathon scale (`cross_questions.md` Q8).
- **Gap:** NetworkX is single-process and in-memory; it will not hold a Union-Bank-scale graph (`cross_questions.md` Q22 cites ~20M transactions/day). The k8s manifest already assumes a Neo4j backend in production, but the adapter is only partially implemented.
- **Target design:** keep NetworkX for the pilot/demo (switching now is wasted effort before funding); present the migration path explicitly — windowed/partitioned graph construction (e.g., rolling 90-day subgraphs per investigation) as an interim step, full Neo4j/graph-DB parity as the funded production step.
- **Reasoning:** judges who ask the scale question (and this project already expects they will) respond better to "here is the migration plan and what's already scaffolded for it" than to a claim that the current architecture already scales, which a technical judge can disprove by asking about graph size limits.
- **Open question for the user:** commit to finishing the Neo4j adapter as a real deliverable, or keep NetworkX indefinitely and pitch the migration only conceptually? These require different levels of near-term engineering investment.

### ML Pipeline & Governance
- **Current state:** IsolationForest + XGBoost, ensemble-scored. Metrics currently disagree between `README.md` and `cross_questions.md` — reconcile before presenting either document.
- **Gap:** no confirmed model governance story (versioning, retraining trigger, drift monitoring) beyond "config is adjustable."
- **Target design:** log model version + training date + metrics snapshot alongside every risk score, surfaced through an existing endpoint (`cross_questions.md` Q13 references `/api/model-metrics` — confirm it exposes version/lineage, not just point-in-time metrics).
- **Reasoning:** RBI-regulated institutions will ask about model governance for any ML system touching compliance decisions — this fix is mostly about making existing data visible, not new ML work.

### Scalability
- Same underlying issue as the graph engine: SQLite is fine for a pilot/single-node deployment, not for bank-scale transaction volume.
- **Target design:** be explicit that a pilot phase runs on SQLite/single-node (matching the private-cloud-SaaS deployment model in §6 and the 3-week pilot plan in `docs/pitch.md`), and a funded production phase moves to a proper OLTP + graph-DB split.
- **Reasoning:** stating this explicitly avoids overclaiming production scale that can't currently be demonstrated, while still showing a credible path to it.

### Security
- **RBAC gap** — see above; this is the most consequential of all findings, because unused security code (present but never imported) reads worse in due diligence than no security design at all — it signals the team knew what was needed and didn't finish wiring it.
- **Hardcoded JWT secret** (`JWT_SECRET = "CHANGE_ME_IN_PRODUCTION"`) — already flagged in `cross_questions.md` Q18 as a known issue; the k8s manifest already assumes loading this from a secret store via `secretKeyRef`, so the target pattern is designed — the application code just needs to stop using a hardcoded default.
- **Upload validation** — the CSV ingest endpoint needs file-size limits, MIME/extension checks, and row-count sanity checks (`cross_questions.md` Q21).
- **Data retention policy** — referenced in `cross_questions.md` Q20; needs an explicit answer for a bank pitch.
- **Reasoning:** these are the security items most likely to be probed directly in live Q&A, precisely because they're already pre-answered in the project's own cross-questions document — meaning the team has anticipated the question but not yet the natural follow-up, "show me the fix."

### CI/CD
- **Current state:** `.github/workflows/ci.yml` runs backend pytest and frontend lint/typecheck/build, but the lint/typecheck/build steps use `|| true`, so none of them can fail the pipeline.
- **Target design:** remove `|| true` once lint/typecheck are clean, add a coverage threshold gate, and add the deployment step implied by the existing k8s manifest (build + push image to at least a staging namespace).
- **Reasoning:** a pipeline that cannot fail is worse than no pipeline, because its green checkmark actively misrepresents quality to anyone (investor or engineer) evaluating it.

### AI Guardrails
- **Current state (strong):** per-account LLM explanations inject computed facts into the prompt rather than letting the model generate them, run at low temperature (0.3), are clearly labeled "AI-Generated," and are response-cached (`cross_questions.md` Q14). This is a genuinely defensible existing design.
- **Gap:** none of this automatically extends to the proposed AI Investigation Copilot (§4.2), which by design takes open-ended natural-language input and must query live case state — a fundamentally different risk profile (prompt injection via narration/purpose fields, unbounded queries, potential cross-case data leakage if not scoped correctly).
- **Target design for the Copilot, before it ships:** (1) a fixed set of retrievable tool calls, never free-form DB/graph queries; (2) hard scoping to the current case ID only; (3) input sanitization on any user-supplied text that flows into the prompt (transaction narrations and declared-purpose fields are attacker-controllable, since a launderer writes them); (4) the same "clearly AI-generated, facts independently viewable" pattern already used for account explanations.
- **Reasoning:** the existing explanation feature is defensible today because it cannot be manipulated by the input data flowing through it (facts are computed server-side, not relayed from user text). The Copilot breaks that invariant the moment it accepts natural-language questions or reads narration fields, so the guardrail philosophy needs explicit re-application — it cannot be assumed to carry over. **Open question for the user:** given the Copilot's distinct guardrail requirements and multi-day build effort, is it worth building before the Fest, or better pitched as "on the roadmap" alongside the later RL phases already described in `docs/RL_USP.md`?

### User-Friendliness / UX
- **Current state:** a 9-page frontend covering Dashboard, Graph, Anomaly, Patterns, Profile, Channels, Real-Time, Evidence, Ingest, plus `/rl-queue` and `/rules` — reasonably complete surface area for a hackathon build.
- **Gap:** the frontend is organized by *data type* (a graph page, a patterns page, a profile page) rather than by *investigation stage* (a triage view, a deep-dive view) — the L1/L2 structure in `systemrequirements.txt` is itself a UX blueprint that isn't yet reflected in navigation.
- **Target design:** a case-centric "investigation workspace" that surfaces the L1 fields (alert summary, AI explanation, customer snapshot, geo risk, simplified graph, decision buttons) on one screen, with L2 reachable as an "expand for deep investigation" mode, rather than requiring an investigator to assemble the same picture by navigating between separate top-level pages.
- **Reasoning:** this is the actual difference between "a set of analytics tools" and "an investigation workflow product" — the latter is the UX pattern NICE Actimize and Oracle FCCM deliver, and it is explicitly what the requirements doc's own workflow diagram describes.

---

## 6. Deployment Models

`systemrequirements.txt` names two viable models. Both are legitimate; they serve different points in the sales motion.

| Model | Description | Reasoning |
|---|---|---|
| **Private Cloud SaaS** — TraceX deployed inside the bank's own AWS/Azure/private cloud account; vendor manages the software, bank owns the data | Already the "most realistic today" framing in the original plan, and it matches the pilot approach in `docs/pitch.md` (CSV export only, no core-banking-system integration needed for week one). It sidesteps the biggest bank objection to AML SaaS — data leaving their infrastructure — while preserving a recurring-revenue model, which is what investors want to see over a one-time license. |
| **On-Premise Software License** — bank runs TraceX in its own data center; vendor provides setup + annual license + support contract (market comparable: ~₹50L setup, ~₹20L/yr support) | Higher setup friction and a longer sales cycle, but a larger absolute deal size, and it is literally how Oracle/SAS/NICE already sell into Indian PSU banks. Positioned as the enterprise upsell tier for banks with strict data-residency mandates or existing on-prem infrastructure investment, not as the lead motion for a seed-stage pitch. |

**Prerequisite for either model to be credible:** the k8s manifest already assumes multi-tenant-safe patterns (non-root containers, network policies, secrets via `secretKeyRef`) — but with RBAC unwired and two case stores in play, tenant/data isolation cannot currently be demonstrated if a judge or bank security reviewer asks. The security and case-store fixes in §5 are a prerequisite to pitching *either* deployment model credibly, not a generic hygiene item to defer.

---

## 7. Key Departures From the Raw Plan in `systemrequirements.txt`

1. **Feature #1 (AI prioritization queue) already exists** — effort should go into wiring it visibly into the orchestrator narrative and into features that reuse its feature vector (Path Recommendation, Similar Cases), not into rebuilding it.
2. **The security gap matters more than any of the 14 proposed features.** An unwired RBAC system already sitting in the codebase is a worse signal in due diligence than not having designed RBAC at all.
3. **The two case stores must be unified before case management is extended further** — every new case-centric feature needs one source of truth, and building on the split store compounds the migration cost later.
4. **The L1/L2 workflow should be a UX redesign, not just a backend concept.** It's currently implicit in how the API is organized; making it the actual navigation structure of the frontend is what turns "a set of analytics pages" into "an investigation product."
5. **Net-new features should be sequenced by reuse, not by novelty.** Network Risk Score, Investigation Path Recommendation, and Similar Historical Cases all become cheap once it's clear they can reuse the existing RL feature vector and centrality/SAR data — this reuse should drive build order ahead of expensive net-new items (Copilot, Relationship Explorer) that need genuinely new infrastructure.
6. **AI guardrails are a per-feature question, not a one-time checkbox.** The existing explanation feature is well-guarded; the proposed Copilot is a different risk class entirely and needs its own explicit guardrail design, not an assumption that the existing pattern covers it.
7. **Documentation/metric inconsistencies should be reconciled now**, while the fix is cheap, rather than risking discovery mid-pitch.

---

## 8. Open Decisions

These require a judgment call from the team, not something to guess at:

- **RBAC granularity:** two roles (Investigator / Admin) as the simplest workable model, or a distinct third role for L1 vs. L2 investigators with a different UI surface?
- **Copilot investment level:** build it pre-Fest despite its higher effort and distinct guardrail requirements, or pitch it as roadmap alongside the later RL phases in `docs/RL_USP.md`?
- **Graph engine commitment:** finish the partial Neo4j adapter as a real deliverable before the Fest, or keep NetworkX and present the migration path as a conceptual roadmap item only?
