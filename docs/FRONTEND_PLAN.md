# TraceX Frontend Plan

*Derived from the owner's `frontendreuirements.txt` draft, reconciled against `SYSTEM_DEVELOPMENT_PLAN.md` and the real, already-built backend surface (`backend/api/routes/*.py`, `docs/ROADMAP.md` Phases 0–8). This is the frontend's equivalent of the backend plan: a reference spec for the eventual frontend roadmap phases, not a sprint list.*

**Status: draft, planning-level.** Frontend has no roadmap phases yet (`docs/ROADMAP.md` line 3: "Frontend runs in parallel on its own track later"). This document is what that track should be built from. Backend Phases 0–8 are **done**; Phases 9–12 (Recommendation Engine, Copilot, Reporting/Watchlist, Feedback loop) are **not started** — §6 below sequences frontend work against that reality so nothing gets built against an API that doesn't exist yet.

---

## 0. What's kept, unchanged, from the original draft

The owner's core idea is right and is **kept exactly as designed**:

- Three pages only: **Dashboard → Investigation Workspace → My Center**. No Graphs/Timeline/Transactions/Evidence/AI/Reports as top-level pages.
- The investigator lives inside the Investigation Workspace once a case is open; every tool appears where it's needed, never behind separate navigation.
- Cases open as horizontal tabs, state preserved per tab (scroll, filters, expanded graph, selected transactions, notes) — nothing resets on switching.
- Triage (L1) is fast and minimal; Deep Investigation (L2) is comprehensive but still inside the same case, no new page/tab.
- Notifications are a header icon, never interrupt an open investigation.

Everything below is the same shape, with backend-accurate content: correct field names, correct endpoints, correct role behavior, and features placed where the *data actually lives* rather than where the draft guessed.

---

## 1. Global Shell

### Top navigation (unchanged: 3 items)
`Dashboard | Investigation Workspace | My Center` — permanent, plus a notification bell and user/role indicator on the right. That's the entire top-level chrome.

### Roles (RBAC — confirmed in code: `backend/foundation/auth.py`, `UserRole.INVESTIGATOR` / `UserRole.ADMIN_COMPLIANCE`)
Two roles, exactly as the draft assumed — **but with one correction that changes UI behavior**, not navigation:

> **Investigators can triage, escalate, request info, add evidence/notes, and run every L1/L2 tool. They cannot close a case.** `POST /cases/{case_id}/decision` hard-blocks `close_fp` for non-`ADMIN_COMPLIANCE` users with a 403 (`backend/api/routes/cases.py:596`). Only Admin/Compliance closes a case (false positive, true positive, or monitoring) or approves an STR. This is a deliberate maker-checker control, not a gap — the same pattern real AML platforms (Actimize, FCCM) use, and it's a *stronger* enterprise story than "investigator does everything," which is worth pitching as a feature, not hiding.

This means the Decision Panel (§3.3, §3.6) is **role-aware**, not just admin-vs-investigator on the Dashboard as the draft had it.

### Notifications
Header bell, badge count, dropdown list — never a modal, never blocks the workspace. Backed by the audit log (§4.2) filtered to events relevant to the logged-in user (new assignment, monitoring hit, case reassigned, STR completed). No dedicated notifications endpoint exists yet — flagged in §6 as a small backend addition (a filtered view over `audit_log`, not a new subsystem).

---

## 2. Page 1 — Dashboard

Unchanged in purpose from the draft: system awareness + entry point, no investigation happens here.

| Section | Content | Backend reality |
|---|---|---|
| Summary cards | Total Active Alerts, Critical Alerts, Open Cases, Avg Risk Score | **Gap.** No aggregate/stats endpoint exists yet. Needs a small new route (`GET /dashboard/summary` or similar) — trivial aggregation over existing `cases`/`alerts` tables, not new logic. |
| Trend charts | Alerts over time, severity distribution | Same gap — needs a lightweight aggregation endpoint. Keep to one or two charts, not a BI dashboard (per the draft's own "should not dominate the page"). |
| Alert/case table | Alert ID, Account, Type, Risk Score, Priority, Generated Time, Status, Assigned Investigator | **Gap.** `investigation/prioritization.py::rank_alert_queue` and the case store both exist, but there is **no HTTP list route** over them yet (only per-case detail routes exist in `cases.py`/`l2.py`). This is the single most important backend gap for the frontend to unblock — it's what makes the Dashboard possible at all. Needs `GET /cases` (or `/alerts`) with filter/sort/pagination params. Low effort: it's a thin route over already-built ranking + repository code. |
| Row action | "Open in Investigation Workspace" | Opens/focuses the case tab (§3.1) rather than navigating away. |
| Admin-only controls | Assign / Reassign / Bulk assign, filter by investigator workload | `investigation/assignment.py` has workload-based **auto**-assignment logic, but no confirmed **manual** reassignment route yet. Flag before wiring — likely a small new endpoint, not new logic. |
| Investigator view | Same table, scoped to `assigned_to = me`, no assign controls | Enforced server-side already (`case.assigned_to != user.user_id` → 403 in `require_case_access`), so the frontend only needs to *not render* controls the API would reject anyway — good defense in depth. |

**Simplicity rule:** cards and charts stay compact and fixed height — the table is the page. No drill-down analytics here; that's what the workspace is for.

---

## 3. Page 2 — Investigation Workspace

This is the product. Structure kept from the draft, content and endpoints corrected.

### 3.1 Case tabs & state model

`Case 102 | Case 245 | Case 418 | +` — unchanged. Each tab is a **mounted, not-unmounted** component (keep-alive pattern: render all open tabs, toggle visibility with CSS rather than conditional mount/route change) so scroll position, expanded graph nodes, applied filters, and draft notes survive a tab switch with zero refetch. One client-side store per case (`case_id` keyed), holding: active view (Triage/Deep), scroll offsets, graph expand/filter state, selected transactions, notes draft, similar-cases expansion state.

### 3.2 Case stage badge ↔ real backend status

The draft's four stages (Triage / Deep Investigation / Monitoring / Closed) map cleanly onto the **real** FSM in `backend/investigation/fsm.py` — which actually has *more* precision than the draft assumed (it already distinguishes true-positive from false-positive closes):

| Tab badge (shown to investigator) | Backend `CaseStatus` |
|---|---|
| Triage | `NEW`, `ASSIGNED`, `IN_PROGRESS` |
| Awaiting Review | `AWAITING_REVIEW` (investigator requested info; sits in Admin/Compliance's queue) |
| Deep Investigation | `ESCALATED` |
| Monitoring | `MONITORING` |
| Closed — False Positive | `CLOSED_FP` |
| Closed — Confirmed | `CLOSED_TP` |

No new backend state needed — this is a display-label mapping only.

### 3.3 Triage Workspace (L1)

Same 10-section shape as the draft, each now pointed at a real endpoint. All of these are **built** (Phase 5, done):

| # | Section | Endpoint |
|---|---|---|
| 1 | Alert Summary | `GET /cases/{case_id}/summary/alerts` |
| 2 | AI Alert Summary | *(folds into §7 below — see AI placement note)* |
| 3 | Customer Snapshot | `GET /cases/{case_id}/accounts/{account_id}/customer-snapshot` |
| — | Geographic Risk *(draft listed under Customer Snapshot; backend exposes it separately — keep as a small inline row inside the same card, not a new section)* | `GET .../geo-risk` |
| 4 | Simplified Money Flow | `GET /cases/{case_id}/accounts/{account_id}/money-flow` — already returns `pct_of_total` per counterparty, so the "most frequent destination" stat in §5 is free from this same call |
| 5 | Transaction Summary | `GET .../transaction-summary`, `GET .../transaction-purpose` |
| 6 | Previous Investigation History | `GET .../previous-alerts` (scoped to the primary account only — network-wide history is an L2 feature, §3.5) |
| 7 | Network Risk | `GET /cases/{case_id}/network-risk` (lazy-computed, cached; `POST .../network-risk/recompute` for a manual refresh button) |
| 8 | AI Recommendation | **Not this phase's engine.** See §3.7 — this section should NOT be built against a real endpoint yet; it's Phase 9 (Recommendation Engine), not started. Build the UI slot now, wire it last. |
| 9 | Investigator Notes | `POST/GET /cases/{case_id}/notes` (autosave = debounced `POST` on pause, not a separate "save" button) |
| 10 | Decision Panel | `POST /cases/{case_id}/decision` |

**AI Alert Summary (§2) and Pattern Explanation:** the draft treats "why was this alert created" as one section. The real backend has two distinct, already-built AI calls worth surfacing as one panel with two tabs/toggle, not two sections: `GET .../accounts/{account_id}/explanation` (account-level, "why is this account anomalous") and, once escalated, `GET /cases/{case_id}/alerts/{alert_id}/pattern-explanation` (typology-level, "why is this a circular-transaction pattern"). Both already follow the same guardrail pattern (facts injected server-side, low temperature, labeled AI-generated, response-cached) — safe to build now.

**Similar Historical Cases — placement correction:** the draft puts this in Deep Investigation (L2); `SYSTEM_DEVELOPMENT_PLAN.md` §4.1 scopes it as an **L1** feature, and it's already built (`GET /cases/{case_id}/similar-cases`). Recommendation: show a **compact top-3 card in Triage** (it directly informs the FP-vs-escalate decision — that's the entire point of the feature) with a "view all" link that expands the same data into a fuller list once in Deep Investigation. One dataset, two densities — not two separate builds.

#### Decision Panel — role-aware (correction from §1)

- **Investigator sees:** "Escalate to Deep Investigation" and "Request More Info" — both call `/decision` with `escalate`/`request_info`, both open to them today.
- **Investigator does NOT see a working "Mark False Positive" button that closes the case** — the API will 403 it. Show it as **"Recommend False Positive"** instead: same UI, but it submits with a mandatory reason and routes the case to `AWAITING_REVIEW` (via `request_info`, reframed) for Admin/Compliance to close. This keeps the draft's UX intent (fast FP triage) while matching the real maker-checker control — a real investigator never hits a dead-end 403 in the browser.
- **Admin/Compliance sees:** the full set including a real "Close — False Positive" button (`close_fp`).
- Every submission is already audited server-side (`transition_case`/`close_case` write `case_status_history` + `audit_log` rows) — no separate frontend audit call needed.

### 3.4 Transition to Deep Investigation

Unchanged from the draft and matches the backend exactly: `escalate` doesn't create a new case or tab — it's the same `case_id` transitioning `IN_PROGRESS → ESCALATED`, and the workspace view swaps from Triage to Deep Investigation components inside the same tab.

### 3.5 Deep Investigation Workspace (L2)

| Draft section | Endpoint | Status |
|---|---|---|
| Collapsible Triage Summary | Reuse the same L1 API calls (§3.3), rendered collapsed by default | Built |
| Relationship Explorer | `GET /cases/{case_id}/relationships` | Built (Phase 7 — "v1": fuzzy name/PAN/branch/income; device/IP explicitly deferred, no backing data) |
| Complete Investigation Graph | `GET /cases/{case_id}/accounts/{account_id}/graph` — full filter set (risk/amount threshold, time window, channel/direction, role, prior-SAR) | Built. Note: "international" filter is explicitly **not** built (no jurisdiction field in the schema) — don't add a filter control for it. |
| Investigation Timeline | `GET .../accounts/{account_id}/timeline` | Built. Timeline↔graph sync: every event carries the same `txn_id` the graph edges carry — the frontend does the highlight correlation client-side by matching that key; no extra backend call needed. |
| Transaction Explorer | `GET /cases/{case_id}/transactions/search`, `GET .../accounts/{account_id}/transactions/search` | Built. No server-side CSV export exists — if "export" is wanted in the UI, do it client-side over the already-fetched result set, don't assume a backend export route. |
| Complete Customer Profile | `GET .../accounts/{account_id}/profile` | Built, with documented omissions (beneficial owner, linked cards/loans/deposits, risk-score trend — no backing schema; response includes an `omitted_fields` list, worth surfacing in the UI as "not available" rather than hiding silently) |
| Historical Behaviour Analysis | `GET .../accounts/{account_id}/behavior` | Built — 5 of 7 draft items (monthly spend, cash-deposit trend, transfer trend, dormancy/reactivation, velocity). Salary mismatch / seasonal trends are marked `"deferred"` in the response — show as "not yet available," not blank. |
| Pattern Explanation | `GET /cases/{case_id}/alerts/{alert_id}/pattern-explanation` | Built |
| Similar Historical Cases (full view) | Same endpoint as §3.3, no `top_k` cap | Built |
| Evidence Management | `POST/GET .../evidence`, `PATCH .../evidence/{id}/pin`, `POST/GET .../notes` | Built. "Attach documents" is metadata-only (`file_path` string) — **no file upload/storage backend exists.** Don't build a file-picker/dropzone that implies real upload; a "link a document path" field is what the backend actually supports today. |
| Investigation Path Recommendation | `investigation/path_facts.py` computes the facts, but there is **no reasoning/ranking layer or HTTP route yet** — this is literally what Phase 9 builds | **Not built.** Same UI-slot-now, wire-later treatment as §3.3 AI Recommendation. |
| AI Investigation Copilot | See §3.7 | **Not built** (Phase 10) |
| Investigation Narrative | See §3.6 | **Not built** (Phase 11) |
| Graph Replay (animated) | Draft's own §4.2 item; underlying temporal data exists, animation is frontend-only work, sequenced after Timeline↔Graph sync | Frontend build, no backend blocker — reasonable to build early since it needs no new API |

### 3.6 Final Decision Panel

**This is the one real backend gap in the entire L2 surface**, worth being explicit about rather than assuming it exists: `POST /cases/{case_id}/decision` today only accepts `escalate` / `request_info` / `close_fp`. The FSM already defines the transitions the draft's Final Decision Panel needs (`ESCALATED → CLOSED_TP`, `ESCALATED → MONITORING`, `AWAITING_REVIEW → CLOSED_TP`, `AWAITING_REVIEW → MONITORING`) — they exist in `fsm.py`'s transition graph, but no route exposes `closed_tp` or `monitoring` as decision values yet, and STR generation (the "Escalate to Compliance / Generate STR" action) doesn't exist until Phase 11.

**Frontend recommendation:** design and build the Final Decision Panel UI now (it's pure layout + form work), but treat its submit action as **not wireable until Phase 11** ships the extended `/decision` values + STR generation + watchlist-write. Sequence this explicitly (§6) rather than discovering the 404 mid-build.

Role-aware exactly like §3.3: Investigator can recommend/escalate; only Admin/Compliance actually closes, places under monitoring, or triggers STR.

### 3.7 The two AI agents — where each lives

The draft's plan flattens "AI Recommendation" (L1), "Investigation Path Recommendation" (L2), and "AI Copilot" (L2) into what reads like three similar boxes. The backend design (`SYSTEM_DEVELOPMENT_PLAN.md` §9.3, `docs/ROADMAP.md` Phases 9–10) is deliberately **two distinct agents** with different scopes — the frontend should make that distinction visible, not flatten it:

- **Recommendation Engine** (Phase 9) — case-scoped, deterministic-guarded. This is what powers §3.3's "AI Recommendation" and §3.5's "Investigation Path Recommendation" — **same agent, same panel type, shown at both stages**, not two separate features. It only ever suggests actions from a fixed catalog, each cited to a rule + regulation anchor + tool-computed fact. UI treatment: a recommendation card with a visible "why" (cited facts, rule anchor) and a **"cross-question"** affordance (a small chat-like follow-up box scoped to just that recommendation) — this directly implements the draft's implicit want for the AI to be interrogable, not just a static suggestion.
- **Copilot** (Phase 10) — investigator-scoped, cross-case. The draft says the Copilot should "never open as a separate page" and "answer questions only about the currently opened investigation" — the real backend design is slightly broader: it also does cross-case things (find/filter *my* cases, a "what changed since last login" digest) that don't make sense scoped to one case. Resolution: **one Copilot component, two mount points** — embedded in the Investigation Workspace (case-scoped Q&A, matching the draft exactly) *and* a smaller instance in My Center (§4) for the cross-case digest/search. Same chat UI, different context injected — not two builds, and it doesn't violate the draft's "never a separate page" rule since My Center is already one of the three approved pages.

Both agents are unbuilt on the backend today (§6 sequences this).

---

## 4. Page 3 — My Center

Two sections, unchanged from the draft.

### 4.1 Monitoring

**This section *is* the Watchlist feature** (`SYSTEM_DEVELOPMENT_PLAN.md` §4.2, Phase 11, not started) — the draft independently arrived at the same UI the backend spec calls "Watchlist Management," which is a good sign the two documents were pointed at the same problem from different directions. No separate "Watchlist" concept needs to be designed; when Phase 11 ships `WatchlistScreener`, this section is its UI, full stop. Fields (Account/Network Name, Monitoring Reason, Date Added, Current Risk, Latest Activity) map directly to what a watchlist entry needs to store. The notification badge ("Monitoring (3)") is driven by future alerts touching a watchlisted entity auto-escalating — exactly Phase 11's stated behavior.

### 4.2 Audit Logs

Backed by the **already-built, already-unified** audit trail (Phase 4, done) — `audit_log` rows exist for case assignment, escalation, decisions, evidence pinning, note creation, and (once Phase 8 ships) every AI interaction. This section needs a list/search/filter endpoint over `audit_log` scoped to the current investigator, which — like the Dashboard's alert table — doesn't have a dedicated HTTP route yet (same shape gap: the data model and writes are done, the read route isn't). Flag alongside the Dashboard gap in §6; likely one shared "list + filter" route pattern serves both.

### 4.3 Copilot digest (see §3.7)

Small panel: "3 things happened since you last logged in," "find my cases matching X." Same component as the workspace Copilot, cross-case context.

---

## 5. Feature coverage matrix

Every feature `SYSTEM_DEVELOPMENT_PLAN.md` §2 tracks, mapped to where it now lives in this 3-page plan:

| # | Feature | Frontend location | Backend status |
|---|---|---|---|
| 1 | AI Case Prioritization Queue | Powers Dashboard's alert ordering (not a separate page) | Built |
| 2 | Similar Historical Cases | Triage (compact) + Deep Investigation (full) | Built |
| 3 | Timeline↔Graph Sync | Deep Investigation | Built (data contract); frontend does the click-to-highlight |
| 4 | Graph Filters | Deep Investigation graph panel | Built |
| 5 | Network Risk Score | Triage | Built |
| 6 | AI Investigation Copilot | Deep Investigation (embedded) + My Center (digest) | Not started (Phase 10) |
| 7 | Auto-generated Investigation Narrative | Final Decision Panel, pre-submit | Not started (Phase 11) |
| 8 | Relationship Explorer | Deep Investigation | Built (v1: fuzzy attributes) |
| 9 | Graph Replay | Deep Investigation | Frontend-only, no backend blocker |
| 10 | Watchlist Management | My Center → Monitoring | Not started (Phase 11) |
| 11 | Detection Feedback Loop | Invisible to frontend (backend loop) | Built |
| 12 | Audit Trail | My Center → Audit Logs | Built (data); list route needed |
| 13 | Investigation Path Recommendation | Triage + Deep Investigation (Recommendation Engine) | Not started (Phase 9) |
| 14 | Continuous Learning Feedback Loop | Not a frontend surface | Roadmapped, later |

---

## 6. Build sequencing (frontend against real backend readiness)

Don't build UI against endpoints that don't exist — sequence by what's already live:

**Now (Phases 0–8 backend already done — build against real data):**
1. Global shell (nav, roles, tabs, notification shell)
2. Dashboard — *blocked on* the small list-route gap (§2); worth filing as a one-session backend add-on before this can go past mock data
3. Triage workspace — fully buildable except the AI Recommendation slot (leave empty/placeholder)
4. Deep Investigation — fully buildable except Copilot, Investigation Narrative, and the extended Final-Decision transitions
5. My Center → Audit Logs — same small list-route gap as Dashboard
6. Graph Replay animation — buildable now, no backend dependency at all

**After Phase 9 ships (Recommendation Engine):**
7. Wire the AI Recommendation panel (Triage) and Investigation Path Recommendation panel (Deep) — same component, per §3.7

**After Phase 10 ships (Copilot):**
8. Wire the embedded Copilot (workspace) and digest widget (My Center)

**After Phase 11 ships (Reporting/Narrative/Watchlist):**
9. Investigation Narrative + STR generation UI
10. Extended Final Decision Panel (`closed_tp`/`monitoring` values)
11. My Center → Monitoring, wired to real Watchlist data

This lets frontend development start immediately and stay entirely truthful — nothing in the demo silently depends on a mocked AI response pretending to be real.

---

## 7. Tech approach (kept deliberately light)

- Next.js 15/16 + TypeScript + Tailwind, per `CLAUDE.md` — no framework change.
- Component library: something Tailwind-native and unopinionated (e.g. shadcn/ui) so the "clean, spacious, minimal, enterprise" look is achieved by restraint (whitespace, one accent color, no visual clutter) rather than custom design-system work — matches "don't make it complicated."
- State: one lightweight store (Zustand or React Context) keyed by `case_id` for tab persistence (§3.1); no heavier state library needed for a 3-page app.
- Graph rendering: `cytoscape` or `react-force-graph-2d` (already named in the repo's frontend agent scope) for the L2 full graph; the L1 simplified money-flow view should be a much lighter, non-interactive SVG/small component — reinforcing the draft's own point that conflating the two graph views is a real UX mistake to avoid.
- Charts: `recharts` for the Dashboard's one or two trend charts — nothing more elaborate needed.

---

## 8. Deviations from the raw draft (explicit, so nothing is silently changed)

1. **Decision Panel is role-aware**, not a flat set of buttons — Investigators recommend, only Admin/Compliance closes. This is a real backend RBAC rule (§1), not a design opinion.
2. **Similar Historical Cases moves to Triage** (compact) as its primary home, with a fuller view in Deep Investigation — matches `SYSTEM_DEVELOPMENT_PLAN.md`'s own L1 classification and the fact it's already built and cheap to show early.
3. **Copilot gets a second, smaller mount point in My Center** — the real backend design (Phase 10) is intentionally cross-case as well as case-scoped; a single case-only Copilot would under-use what's actually being built.
4. **Recommendation Engine and Investigation Path Recommendation are the same component**, shown at two workflow stages, not two separate AI features — avoids building the same thing twice.
5. **Final Decision Panel is designed but not wired yet** — the backend route for its non-FP outcomes doesn't exist until Phase 11. Build the UI, stub the submit, don't fake a working STR flow in a demo.
6. **Dashboard's alert table and My Center's audit log both need a small new backend list/filter route each** — neither is a UI problem; both are one-session backend additions over data and logic that already exist.

---

## 9. Open question for the owner

`docs/ROADMAP.md` currently has no frontend phases at all — this document is written to become the source those phases are cut from, the same way `SYSTEM_DEVELOPMENT_PLAN.md` fed the backend roadmap. Worth a short planning session to turn §6 above into actual `phase/13-frontend-*`-style roadmap entries once you're ready to start building, so frontend sessions get the same "resume without re-deriving context" treatment backend sessions already have via `docs/SESSION_LOG.md`.
