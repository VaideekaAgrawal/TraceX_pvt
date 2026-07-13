# TraceX Frontend Roadmap

**Status: filled in by Planning Session (2026-07-14).** This is the frontend's execution plan, the same role `docs/ROADMAP.md` plays for backend — derived from `docs/FRONTEND_PLAN.md` (the reference spec) the way that backend roadmap was derived from `SYSTEM_DEVELOPMENT_PLAN.md`. Development sessions work from this document phase by phase, exactly like backend sessions work from `docs/ROADMAP.md`.

**This supersedes `docs/FRONTEND_PLAN.md` §9's open question** — the planning session it asked for has now happened.

**Numbering:** continues backend's phase sequence (`Phase 0`–`Phase 12`) rather than restarting at 1. This is one project timeline with two tracks, not two projects — `phase/13-...` makes it immediately legible in `git log`/branch lists which phase came before which, and avoids ever having two different "Phase 3"s in the same repo's history.

**Budget:** ~14–18 sessions across Phases 13–22. Sized the same way backend was (1–2 sessions/phase), frontend-weighted toward UI construction rather than algorithm work, which is why the count is comparable to backend despite having no ML/graph-theory complexity — the surface area (10 L1 sections, 13 L2 sections, 3 pages, 2 AI-agent UIs) is genuinely large.

**Governing rules (do not re-litigate):** everything in `CLAUDE.md`'s Git workflow, session model, and subagent-workaround sections applies identically to frontend sessions — branch per phase, commit at checkpoints, `/code-review` (+ `/verify`, since every frontend phase has a runtime surface) before merge, PR even solo, `/session-start` / `/session-end` every session, never force-push/skip hooks, `docs/SESSION_LOG.md` is the shared memory across machines/accounts. There is no separate frontend session protocol — it's the same protocol, different phase numbers.

**Execution rigor (per the owner's `CHANGES_PRODUCTION_UPGRADE.md` reference):** that document is the bar this roadmap holds frontend sessions to, not a source of frontend requirements — it's the *previous system's* backend upgrade log, already superseded by the greenfield rebuild. What's worth carrying forward is its **method**: verify each phase against running code before starting the next, diff behavior before/after any change that touches existing output, write down what's still broken instead of glossing over it, and cite exact files/endpoints rather than trusting a spec doc's framing. Every phase below ends with a **Verify** line for this reason — treat it as mandatory, not optional polish.

---

## Committed decisions (this session — do not re-litigate)

1. **Component library: shadcn/ui over Tailwind.** Unopinionated, so "clean/spacious/enterprise" comes from restraint (whitespace, one accent color) rather than a custom design system — matches the owner's explicit "not complicated" requirement. No alternative considered seriously enough to record.
2. **State: Zustand, one store keyed by `case_id`.** Chosen over Redux/Context-only for the tab-persistence requirement (§`FRONTEND_PLAN.md` 3.1) — minimal boilerplate, no provider-tree complexity for a 3-page app.
3. **Graph libraries: `cytoscape` for the L2 full interactive graph, plain SVG (no graph library) for the L1 simplified money-flow view.** Deliberately different tools for the two views — reinforces the L1-is-not-L2 boundary at the implementation level, not just the UX level, so it's structurally hard to accidentally let L2 complexity leak into L1.
4. **Backend-gap routes are scheduled inside the frontend phase that needs them, not deferred to a separate backend-numbered phase.** (Phase 14 bundles the Dashboard/audit/notification routes with the Dashboard UI that consumes them.) They're still implemented by whichever agent/role owns backend code (`tracex-backend`) and go through the same review as any other backend change — bundling is about scheduling, not about skipping backend rigor.
7. **Frontend lives at a clean `frontend/` at repo root — never `fund-flow-tracker/frontend/`.** That path is already archived (`archive/fund-flow-tracker/frontend`, confirmed on disk); no `frontend/` exists at root today, so there's no conflict to resolve, just a fresh directory to create in Phase 13. This mirrors the backend's own `archive/` vs. clean `backend/` split exactly — the frontend gets the same greenfield treatment, not a resurrection of the old tree. `.claude/agents/tracex-frontend.md` and `CLAUDE.md` both still say `fund-flow-tracker/frontend/` in prose — both are config-session-owned files, so this roadmap flags the staleness (see "Open items") rather than editing them from a planning session.
8. **Dashboard and Investigation Workspace read from two different list endpoints, not one shared table.** Dashboard = `GET /alerts`, system-wide, alert-level, aggregated — the "what's happening across the bank today" view, not scoped to any one investigator. Investigation Workspace = `GET /cases` (role-scoped: `assigned_to = me` for Investigators; open-for-review queue for Admin/Compliance) — the "what am I working on" list you pick a case from to open as a tab. This resolves the earlier open question about whether one route could serve both — it can't, because the two pages answer genuinely different questions (system awareness vs. personal queue), and conflating them was the original draft's own ambiguity, not a backend gap. See Phases 14 and 15 below.
5. **AI-feature UI phases (19–21) are hard-blocked on their backend phase, no exceptions.** No "build against a mock response shape and swap later" for the Recommendation Engine or Copilot panels — `docs/FRONTEND_PLAN.md` §6 already made this call (nothing in a demo silently depends on a fake AI response). Graph Replay (frontend-only, §Phase 18) is the one enrichment feature *not* backend-blocked, and is scheduled early deliberately, since it's free relative to the AI phases.
6. **RBAC is enforced server-side; the frontend's job is to not offer a control the API would reject, never to be the actual gate.** Every role-conditional render is a UX courtesy (see `FRONTEND_PLAN.md` §3.3's "Recommend False Positive" reframe) — if frontend and backend ever disagree on a permission, backend wins and the frontend bug gets fixed, not worked around client-side.

---

## Cross-phase invariants

- Nothing in the UI ever presents a mocked/hardcoded value as if it came from a real backend call, in any build reachable from a demo — a `TODO`/disabled/"coming soon" state is always preferred over fake data. This is the frontend's version of the backend's "the LLM never invents facts" invariant, and it exists for the same reason: a judge or bank reviewer who catches one faked number stops trusting all the real ones.
- Every new backend route added for frontend (Phase 14, and any later gap found) sits behind the **existing** auth/RBAC dependencies (`get_current_user`, `require_role`, `require_case_access`) — no route is ever added "temporarily" without auth to unblock frontend faster. That shortcut is exactly how the original system ended up with the unwired-RBAC landmine `CLAUDE.md` warns about.
- Case-tab state (scroll, filters, expanded nodes, notes draft) survives a tab switch with zero refetch, for every phase from 15 onward — this is verified explicitly, not assumed, at the end of each phase that adds a new stateful panel.
- Every new backend route follows the audit-log invariant already established: reads don't need new audit entries beyond what Phase 4 already instrumented; any new *write* path does (e.g. Phase 14's manual reassignment route must call the same audit mechanism `CaseRepository.update`'s `action` override already uses for `case_assigned`).
- Frontend CI (`.github/workflows/ci.yml`'s lint/typecheck/build steps) gets its `|| true` removed in Phase 22, mirroring backend's own CI-tightening item (`SYSTEM_DEVELOPMENT_PLAN.md` §5) — tracked here so it isn't forgotten a second time.

---

## Phase list

Legend: **Status** = not started | in progress | done. All phases below start `not started` — this is a fresh planning pass.

### Phase 13 — Frontend scaffold, auth, global shell
**Goal:** A running Next.js app with real login against the real backend, and the permanent 3-tab nav — nothing case-specific yet.
**Depends on:** Backend Phase 2 (auth/RBAC — done)
**Branch:** `phase/13-frontend-scaffold-auth`
**Scope (checklist):**
- [ ] Next.js 15/16 + TypeScript + Tailwind + shadcn/ui project scaffold under a **clean `frontend/` at repo root** (decision 7) — sibling to `backend/`, not under `fund-flow-tracker/`. That old path is archived (`archive/fund-flow-tracker/frontend`); do not scaffold into it or resurrect it.
- [ ] Typed API client wrapping `POST /auth/login`, `GET /auth/me` (`backend/api/routes/auth.py`), with JWT stored appropriately (httpOnly cookie preferred over localStorage for an enterprise pitch — token-theft-via-XSS is a real question a bank security reviewer asks) and attached to every subsequent request.
- [ ] Login page; role (`INVESTIGATOR` / `ADMIN_COMPLIANCE`) read from `/auth/me` and held in a top-level auth context.
- [ ] Global shell: permanent top nav (`Dashboard | Investigation Workspace | My Center`), notification bell (static shell — no data source until Phase 14), user/role indicator.
- [ ] Route guards: unauthenticated → login; role-conditional rendering hooks (`useRole()`) ready for later phases to consume.
**Explicitly out of scope:** any case/alert data (Phase 14+); the Zustand tab store (Phase 15, nothing to persist yet); notification content (Phase 14).
**Reference:** `FRONTEND_PLAN.md` §1.
**Verify:** log in as a seeded Investigator and a seeded Admin/Compliance user against a real running backend; confirm `/auth/me`'s role correctly drives the `useRole()` hook; confirm an expired/invalid token redirects to login rather than rendering a broken shell.
**Status:** not started

### Phase 14 — Backend read-surface routes + Dashboard (alert-level, system-wide)
**Goal:** Close the concrete backend gaps `FRONTEND_PLAN.md` §2/§8 identified, then build the Dashboard against them for real — no mock data at any point in this phase. **Per decision 8, the Dashboard is alert-level and system-wide** — it is the bank's overall alert landscape, not any one investigator's queue. The personal "cases assigned to me" list is explicitly *not* this phase's concern — that's Phase 15.
**Depends on:** Phase 13; Backend Phases 4 (case store/audit — done), 5 (RL-ranked queue — done)
**Branch:** `phase/14-dashboard-api-ui`
**Scope (checklist):**
- [ ] **Backend:** `GET /alerts` — filterable/sortable/paginated list over the existing `Alert` table (not `Case`), reusing `investigation/prioritization.py::rank_alert_queue` for default ordering. Filters: status, priority, risk-score range, type, date range. **Not scoped to the requesting user** — both roles see the full system-wide landscape (matches the original draft's "quick understanding of the current alert landscape" purpose for *both* Investigator and Admin); only the *controls* differ by role, not the data. Response fields: alert ID, account, type, risk score, priority, generated time, status, assigned investigator.
- [ ] **Backend:** `PATCH /alerts/{alert_id}/assign` (or the equivalent case-assignment route if an alert always has a 1:1 case by the time it's visible here — confirm against `investigation/cases.py::create_case_from_alert`'s auto-assignment behavior before deciding which entity the route actually mutates) — manual (re)assignment, Admin/Compliance only (`require_role(UserRole.ADMIN_COMPLIANCE)`), writes through the same audit mechanism Phase 4's `case_assigned` action uses. Also exposes workload-by-investigator (thin read over `investigation/assignment.py`'s existing workload count) so the Admin dashboard's "filter by investigator workload" control has real data.
- [ ] **Backend:** `GET /audit-log` — filterable (case_id, actor_id, action, since) read over the existing `audit_log` table, scoped to the current user's own actions for Investigators, unscoped for Admin/Compliance. This single route backs both the Dashboard/My Center audit needs *and* Phase 13's notification bell (see next item) — one route, two consumers, not two builds.
- [ ] **Backend:** notification feed = `GET /audit-log` called with a curated `action` allowlist (new assignment, monitoring hit, case reassigned, STR generated) rather than a new subsystem — confirms `FRONTEND_PLAN.md` §1's framing that this shouldn't be a new backend concept.
- [ ] **Backend:** `GET /dashboard/summary` — trivial aggregation over the `Alert` table (active alert count, critical count, open case count, avg risk score) plus a small time-bucketed series for the "alerts over time" chart. Cheap at current data scale (8,002 transactions); no caching layer needed yet.
- [ ] **Frontend:** Dashboard page — summary cards, 1–2 charts (`recharts`), the alert table wired to `GET /alerts` with real filter/sort/pagination controls. Row action opens the alert's case in the Investigation Workspace (deep link, useful for Admin oversight) — but this is a secondary entry point, not the primary one; see Phase 15 for why.
- [ ] **Frontend:** Admin-only assign/reassign/bulk-assign controls and workload filter, wired to the new assign route; Investigator view renders the same system-wide table with no assign controls (the frontend simply doesn't render what the API would 403 — per invariant above).
- [ ] **Frontend:** notification bell now reads the curated feed; dropdown, badge count, never a modal.
**Explicitly out of scope:** any "my cases" or assigned-work list — that's `GET /cases`, built in Phase 15, not here; bulk-assign as anything beyond a multi-select + loop of the single-assign call (no new bulk endpoint needed at this data scale).
**Reference:** `FRONTEND_PLAN.md` §2, §8 items 6; decision 8.
**Verify:** confirm both an Investigator and an Admin/Compliance user see the identical alert landscape (same rows, same counts) and differ only in which action buttons render; confirm a live reassignment shows up in `audit_log` and updates the "assigned investigator" column on the next fetch; confirm summary cards match a manual count against the same DB.
**Status:** not started

### Phase 15 — Investigation Workspace shell: assigned queue + case tabs + persistence
**Goal:** The container the rest of the workspace lives in — the investigator's own work queue, tabs, state model, stage badges — with no L1/L2 case content yet.
**Depends on:** Phase 14 (Dashboard exists as the secondary entry point; this phase is the primary one)
**Branch:** `phase/15-workspace-shell`
**Scope (checklist):**
- [ ] **Backend:** `GET /cases` — role-scoped case list, distinct from Phase 14's system-wide `GET /alerts` (decision 8). For `INVESTIGATOR`: `assigned_to = me` (reuse the same scoping `require_case_access` already enforces per-case detail route, applied here as a list filter). For `ADMIN_COMPLIANCE`: cases in `AWAITING_REVIEW` or `ESCALATED` — i.e. their actual queue is "cases waiting on my review/closure action," not "assigned to me" in the Investigator sense, matching the maker-checker model already established in §1/Phase 16. Filters: status, priority. Fields: case ID, primary account, stage badge, priority, last-updated, current status.
- [ ] **Frontend:** Workspace landing view — "Your Cases" list (the queue described above), rendered before/alongside the tab bar; this is the primary way an investigator finds work, not the Dashboard. Selecting a row opens that case as a tab (see next item). Empty state ("no cases assigned") handled explicitly, not left blank.
- [ ] `Case 102 | Case 245 | +` tab bar; opening a case from the queue list *or* from a Phase-14 Dashboard deep link focuses an existing tab or creates a new one (never duplicates a tab for a case already open) — both entry points converge on the same tab-open logic.
- [ ] Per-`case_id` Zustand store (decision 2): active view (Triage/Deep), scroll offsets, graph filter/expand state placeholders, notes draft, similar-cases expansion state — all wired as empty/default now, populated by later phases.
- [ ] Keep-alive rendering: all open tabs mounted, visibility toggled via CSS, not conditional mount — verified by an actual scroll-position/filter-survival test, not just "looks right."
- [ ] Case stage badge, mapped exactly per `FRONTEND_PLAN.md` §3.2's table (`NEW`/`ASSIGNED`/`IN_PROGRESS` → "Triage", `AWAITING_REVIEW` → "Awaiting Review", `ESCALATED` → "Deep Investigation", `MONITORING` → "Monitoring", `CLOSED_FP`/`CLOSED_TP` → "Closed — …") — used in both the queue list and the tab bar, one mapping, not two.
- [ ] Tab close/reopen behavior (closing a tab doesn't close the case, just the view of it; the case remains in the queue list either way).
**Explicitly out of scope:** any actual Triage/Deep Investigation content (Phases 16–18); persisting tab layout across a browser refresh (nice-to-have, not required by the spec — note as a possible later enhancement, don't build speculatively).
**Reference:** `FRONTEND_PLAN.md` §3.1, §3.2; decision 8.
**Verify:** as an Investigator with a known assigned-case set, confirm the queue list matches exactly (no more, no less, no other investigator's cases — hit the route directly with their token to catch a frontend-only scoping bug); as Admin/Compliance, confirm the queue shows only `AWAITING_REVIEW`/`ESCALATED` cases, not the full system list `GET /alerts` already covers. Open 3 cases (mixing queue-list and Dashboard-deep-link entry points), apply a filter/scroll in one, switch through all three and back — confirm the first tab's state is byte-identical to before switching, with the browser network tab showing zero refetch on the switch itself.
**Status:** not started

### Phase 16 — Triage (L1) workspace
**Goal:** A complete, fast, real-data 15–30 minute triage screen — the highest-value single phase in this roadmap, since every one of its endpoints already exists.
**Depends on:** Phase 15; Backend Phase 5 (L1 triage feature set — done)
**Branch:** `phase/16-l1-triage`
**Scope (checklist):**
- [ ] Alert Summary, Customer Snapshot (+ inline Geo Risk row), Simplified Money Flow (SVG, non-interactive per decision 3), Transaction Summary/Purpose, Previous Investigation History, Network Risk (with manual recompute control) — each wired to its real endpoint per `FRONTEND_PLAN.md` §3.3's table.
- [ ] AI panel: account explanation (`GET .../explanation`) — built and safe to wire now (guardrail pattern already server-enforced); labeled "AI-Generated" per the existing pattern, not a new frontend guardrail decision.
- [ ] Similar Historical Cases, compact top-3 card (`GET .../similar-cases?top_k=3`).
- [ ] Investigator Notes — debounced autosave `POST /notes`, no manual save button, per spec.
- [ ] Decision Panel, **role-aware exactly per `FRONTEND_PLAN.md` §3.3**: Investigator sees Escalate / Request-Info / "Recommend False Positive" (submits via `request_info` with the FP reason, does not close); Admin/Compliance additionally sees a real "Close — False Positive" (`close_fp`) that actually closes. Mandatory reason field enforced client-side *and* verified server-side rejects a missing reason (don't rely on the frontend validation alone).
- [ ] AI Recommendation section: build the **UI slot only** (card shell, "recommendations will appear here once available" empty state) — do not wire to any endpoint, per decision 5. This is intentional, not a placeholder to forget.
**Explicitly out of scope:** Deep Investigation transition UI beyond the button that fires `escalate` (Phase 17 owns what happens after); pattern-explanation (L2, Phase 17 — account explanation is the L1 AI panel, pattern explanation is L2's).
**Reference:** `FRONTEND_PLAN.md` §3.3.
**Verify:** run a real case through triage end-to-end against the live backend: escalate one case (confirm it moves to "Deep Investigation" badge and `ESCALATED` status), request-info another (confirm "Awaiting Review"), and — as Admin/Compliance — close a third as false positive (confirm `CLOSED_FP` + a `DetectionFeedback` row exists, matching Phase 5's own backend verification). Confirm an Investigator attempting the close button literally cannot (button doesn't render `close_fp` as clickable for them).
**Status:** not started

### Phase 17 — Deep Investigation (L2) workspace, part 1: graph & data surfaces
**Goal:** The analyst-grade core: graph, timeline, transactions, profile, behavior — the bulk of L2's data-heavy surface.
**Depends on:** Phase 16; Backend Phase 6 (L2 deep investigation — done)
**Branch:** `phase/17-l2-graph-data`
**Scope (checklist):**
- [ ] Collapsible Triage Summary (reuses Phase 16's own components, collapsed by default — no second implementation).
- [ ] Complete Investigation Graph (`cytoscape`, per decision 3): N-hop expand/collapse, full filter set (risk/amount threshold, time window, channel/direction, role, prior-SAR) wired to `GET .../graph`. No "international" filter control (not backend-supported — don't build a UI for a filter that 400s).
- [ ] Investigation Timeline, wired to `GET .../timeline`; click-to-highlight correlation with the graph done client-side by matching shared `txn_id` (no extra backend call, per the data contract already designed).
- [ ] Transaction Explorer: search/sort/filter over `GET /transactions/search` (case-wide) and the account-scoped variant; client-side CSV export over the fetched result set only (no server export exists — don't imply more than that).
- [ ] Complete Customer Profile, `GET .../profile` — explicitly render the response's `omitted_fields` as "Not available" rows, not blank/missing UI.
- [ ] Historical Behaviour Analysis, `GET .../behavior` — render the 5 built metrics; render the two `"deferred"` ones (salary mismatch, seasonal trends) as "Not yet available," matching the profile page's honesty pattern.
**Explicitly out of scope:** Relationship Explorer, Evidence, Pattern Explanation, full Similar-Cases view, Graph Replay (Phase 18); AI panels (Phases 19–20).
**Reference:** `FRONTEND_PLAN.md` §3.5 (rows 1–6).
**Verify:** on a real escalated case, expand the graph 2–3 hops and confirm filter combinations don't crash on edge cases already known to be tricky server-side (self-loop transactions, blank `from_bank`/`to_bank` — both were real bugs Phase 6's backend verification found and fixed; confirm the frontend renders their fixed output correctly rather than assuming they can't occur). Click a timeline entry, confirm the correct graph edge highlights.
**Status:** not started

### Phase 18 — Deep Investigation, part 2: relationships, evidence, similar cases, replay
**Goal:** The remaining L2 surface — relationship discovery, evidence management, the full similar-cases view, and the one frontend-only enrichment (Graph Replay).
**Depends on:** Phase 17; Backend Phase 7 (reuse-driven intelligence — done)
**Branch:** `phase/18-l2-relationships-evidence`
**Scope (checklist):**
- [ ] Relationship Explorer, `GET /cases/{case_id}/relationships` — interactive relationship graph (can reuse the same `cytoscape` setup as Phase 17's investigation graph, different node/edge semantics). Confidence scores (PAN 0.95, fuzzy-name, income-bracket 0.35, branch-city 0.25) shown per edge — don't collapse them into a single "related" boolean, the confidence *is* the finding.
- [ ] Full Similar Historical Cases view (no `top_k` cap), expanding out of Phase 16's compact card rather than a second component.
- [ ] Pattern Explanation panel, `GET .../pattern-explanation` — same AI-panel treatment as Phase 16's account explanation (labeled, cached, facts-only).
- [ ] Evidence Management: bookmark transactions/accounts, pin evidence (`PATCH .../evidence/{id}/pin`), notes continuity from Phase 16's same notes component. Document "attachment" is a `file_path` text field, explicitly **not** a file uploader (no upload backend exists — building a dropzone here would be a real UI lie).
- [ ] Graph Replay: animated timeline-scrubber over the same transaction data Phase 17's timeline already fetches — no new backend call, pure frontend animation work (decision 5's one non-blocked enrichment).
**Explicitly out of scope:** AI Recommendation / Path Recommendation panels (Phase 19); Copilot (Phase 20); Investigation Narrative / Final Decision Panel completion (Phase 21).
**Reference:** `FRONTEND_PLAN.md` §3.5 (rows 7–13, minus AI/narrative rows).
**Verify:** confirm a relationship discovered via a shared attribute (not a direct transaction) actually surfaces an out-of-case customer in the graph — this is the single feature `SYSTEM_DEVELOPMENT_PLAN.md` §4.2 calls the most likely "no one else does this" reaction, worth a real end-to-end check, not a skim. Confirm pinning evidence and reopening the case tab (or logging in fresh) shows the same pinned state — durable, not session-only.
**Status:** not started

### Phase 19 — AI Recommendation Engine UI
**Goal:** Wire the one AI panel that appears at two workflow stages (Triage §8 + Deep Investigation Path Recommendation) as a single component, per `FRONTEND_PLAN.md` §3.7.
**Depends on:** Backend Phase 9 (Recommendation Engine — **not started**). **Do not begin this phase until Phase 9 has shipped and its response contract is confirmed against real running code** — no building against an assumed shape.
**Branch:** `phase/19-recommendation-engine-ui`
**Scope (checklist):**
- [ ] Recommendation card component: action, rationale, cited facts (rendered as inline chips/links back to the source panel — e.g. a cited network-risk fact links to that section), rule anchor (typology + regulatory citation), confidence.
- [ ] Cross-question affordance: a small scoped follow-up input under each recommendation, posting into the same `ai_interactions` thread the backend already audits — surfaced as a lightweight chat, not a full Copilot UI (that's Phase 20).
- [ ] Mount in both slots built (empty) in Phases 16 and 17 — same component, different context prop (`stage: "triage" | "deep"`), not two implementations.
- [ ] Explicit rejection-state handling: if the backend's grounding validator rejects a claim (per Phase 9's design), the frontend must never render a recommendation that failed validation — confirm the API genuinely never returns one, don't add client-side filtering as a safety net for a guarantee the backend already makes.
**Explicitly out of scope:** Copilot (Phase 20); any recommendation the backend catalog doesn't define (the action space is closed by design — the frontend renders whatever the backend returns, it doesn't add its own suggestion types).
**Reference:** `FRONTEND_PLAN.md` §3.7 (Recommendation Engine).
**Verify:** trigger a real recommendation on a live case, cross-question it, confirm the follow-up response still cites resolvable facts; confirm the audit log shows the full thread (`docs/ROADMAP.md` Phase 9's own "reconstructable by a regulator" bar — the frontend should make that thread visible, e.g. via the My Center audit view, not just functional).
**Status:** not started

### Phase 20 — Copilot UI
**Goal:** The embedded case-scoped Copilot (Investigation Workspace) and the cross-case digest/search widget (My Center) — one component, two mount points, per decision and `FRONTEND_PLAN.md` §3.7.
**Depends on:** Backend Phase 10 (Copilot — **not started**). Same hard-block rule as Phase 19.
**Branch:** `phase/20-copilot-ui`
**Scope (checklist):**
- [ ] Chat-style Copilot panel embedded in the Deep Investigation workspace, scoped to the open case; grounded Q&A rendering with the same "AI-Generated, facts independently viewable" labeling pattern used everywhere else.
- [ ] My Center digest widget: "what changed since last login," find/filter my cases — same chat component, cross-case context injected instead of a `case_id`.
- [ ] PII pseudonym rendering: if the backend returns a token (`CUST_A1`) re-hydrated to a name only within that response, the frontend must not cache/persist the hydrated name client-side beyond the single render — matches the backend's "never persisted" design (Phase 10 decision 9); this is a real constraint on frontend state management, not just a backend concern.
- [ ] Notes read/write through the Copilot: confirm the `notes.body` guardrail (Phase 10's own scope item — the only live free-text attack surface in the system) doesn't get bypassed by a frontend feature that, say, lets a note be pre-filled from unsanitized page content.
**Explicitly out of scope:** any case-decision-mutating action from the Copilot (it assists; decisions stay with Investigator/Admin roles, enforced server-side already).
**Reference:** `FRONTEND_PLAN.md` §3.7 (Copilot), §4.3.
**Verify:** ask the Copilot a cross-case question as an Investigator with 5+ assigned cases, confirm results never include another investigator's case (RBAC-scoped exactly like the Dashboard); ask a case-scoped question referencing a customer name, confirm the pseudonym round-trips correctly and isn't visible in any network payload beyond the single response.
**Status:** not started

### Phase 21 — Reporting, narrative, watchlist & final decision completion
**Goal:** Close the loop: case narrative, STR generation, the Final Decision Panel's non-FP outcomes, and My Center → Monitoring wired to real Watchlist data.
**Depends on:** Backend Phase 11 (Reporting, narrative & watchlist — **not started**). Same hard-block rule as Phases 19–20.
**Branch:** `phase/21-reporting-watchlist`
**Scope (checklist):**
- [ ] Investigation Narrative panel: generated case-level narrative, editable before submission, positioned right before the Final Decision Panel per `FRONTEND_PLAN.md` §3.6.
- [ ] Final Decision Panel wired for real: the UI already built in Phase 18's shell now gets working submit actions for `closed_tp`, `monitoring` (once Phase 11 exposes them on `/decision` or a new route — confirm the actual contract against the shipped backend, don't assume it matches this roadmap's guess), and STR generation/download.
- [ ] STR/SAR generation UI: trigger, show generation status, download the FIU-IND PDF+JSON+SHA-256 package once ready.
- [ ] My Center → Monitoring, wired to real `WatchlistScreener` data: fields (Account/Network Name, Monitoring Reason, Date Added, Current Risk, Latest Activity), "Monitoring (n)" badge driven by watchlist-hit alerts.
- [ ] Role-aware exactly like Phase 16: Investigator can view/recommend; only Admin/Compliance actually closes/places-under-monitoring/generates an STR.
**Explicitly out of scope:** regulatory e-filing integration (backend roadmap already scopes this out too).
**Reference:** `FRONTEND_PLAN.md` §3.6, §4.1.
**Verify:** run one case fully through to `MONITORING` and a second fully through to `CLOSED_TP` with STR generated, as Admin/Compliance; confirm the monitored account then shows up in that investigator's My Center; confirm the narrative's facts trace back to real case data (same grounding bar as the AI panels — a narrative that states a number the case data doesn't support is a shipped bug, not a demo nuance).
**Status:** not started

### Phase 22 — Production polish, accessibility, CI tightening
**Goal:** The frontend equivalent of backend Phase 12 — make the maturity claims true, not just the features present.
**Depends on:** all prior frontend phases; Backend Phase 12 (feedback loop & hardening — not started) for anything surfacing model governance/version info.
**Branch:** `phase/22-frontend-hardening`
**Scope (checklist):**
- [ ] Remove `|| true` from the frontend's lint/typecheck/build CI steps (mirrors the exact backend landmine `CLAUDE.md` already tracks) — a pipeline that can't fail is worse than no pipeline for the same reason on either side of the stack.
- [ ] Responsive check at realistic investigator screen sizes (this is a desktop-first enterprise tool — verify it's usable at a standard 1440p/1080p laptop resolution, not attempting full mobile support that was never in scope).
- [ ] Accessibility pass on the core workflow (Dashboard table, Decision Panel, graph keyboard-navigability where feasible) — not a full WCAG audit, but the baseline a bank procurement review will actually check (contrast, focus states, form labeling).
- [ ] Loading/error/empty states audited across every panel built in Phases 14–21 — confirm none of them silently render blank on a slow or failed request (a real risk after 9 phases of incremental building against a live backend).
- [ ] Model governance surfacing, if Backend Phase 12 has shipped `/api/model-metrics` with version/lineage by this point: a small, unobtrusive "model v{n}, trained {date}" indicator near the Network Risk / detection-derived panels — addresses the RBI model-governance question `SYSTEM_DEVELOPMENT_PLAN.md` §5 flags, on the frontend side.
**Explicitly out of scope:** anything not already scoped in Phases 13–21 — this phase hardens what exists, it doesn't add new features.
**Reference:** `SYSTEM_DEVELOPMENT_PLAN.md` §5 (CI/CD, UX, ML governance).
**Verify:** a full CI run on this phase's branch actually fails when a real lint/type error is introduced (test this deliberately — introduce one, confirm red, revert); a cold run through the entire Dashboard → Triage → Escalate → Deep Investigation → Close flow on a throwaway seeded account with no cache/local-storage warm state, confirming no panel ever shows a blank/broken state during normal loading.
**Status:** not started

---

## Sequencing rationale (why this order)

- **Phases 13–18 depend only on already-shipped backend (Phases 0–7)** — this is the critical path to a fully real, fully demoable product (Dashboard through complete L2 investigation, including Relationship Explorer and Graph Replay) that requires **zero** further backend work beyond Phase 14's small bundled routes. If the Fest deadline forces a cut, this is the line: everything through Phase 18 is real, complete, and requires nothing else to ship. That's the "killer" part — a judge sees a fully wired investigation platform, not a shell with AI stubs.
- **Phases 19–21 are strictly backend-gated**, in the same order their backend phases (9, 10, 11) are sequenced — building them earlier against a guessed contract would mean re-doing the wiring the moment the real backend ships with a different shape, which is slower net of the two passes, not faster.
- **Phase 18 (Graph Replay) is deliberately pulled forward** ahead of the AI phases even though it's listed later in the original draft — it's pure frontend work with zero backend dependency, so there's no reason to sequence it after three phases that are hard-blocked on backend work not yet started.
- **Phase 22 sits last** for the same reason backend's Phase 12 does: hardening claims (CI that can fail, no silent blank states, accessibility) are only meaningful once there's a complete surface to hold to that bar.

---

## How to execute this (step by step, per phase)

This is identical to how backend phases already run — same protocol, just pointed at these phase numbers:

1. **`/session-start`** at the beginning of every session, regardless of which machine/account. Pulls latest `main`, reads `docs/SESSION_LOG.md`, tells you exactly where the last frontend (or backend) session left off — you should never need to re-read this whole roadmap from scratch to resume.
2. **Branch:** `git checkout -b phase/<n>-<slug>` off latest `main` if the phase's branch doesn't exist yet; otherwise check out the existing one and pull.
3. **Implement** using the `tracex-frontend` subagent for frontend-only phases (13, 15–21's UI portions, 22), and `tracex-backend` for Phase 14's bundled backend routes and any backend-portion of later phases. **If `Agent(subagent_type: "tracex-frontend")` 404s** with the known `Agent type not found` error, don't re-diagnose — immediately fall back to a `general-purpose` agent with `.claude/agents/tracex-frontend.md`'s full body pasted into the prompt as a preamble, exactly as `CLAUDE.md`'s Subagents section already documents. This has already been hit and worked around twice on the backend side; expect it here too.
4. **Commit at meaningful checkpoints** within the session — after each scope-checklist item that reaches a working state, not just once at the end. A session that gets interrupted shouldn't lose uncommitted work.
5. **Before opening a PR:** run `/code-review` and `/verify` on the full phase diff (every phase here has a runtime surface — there's no "docs-only, skip verify" phase in this roadmap). For phases touching auth, case storage, or AI features (14, 16, 19, 20, 21), also run the `spec-guardian` agent (same 404-fallback pattern as step 3 if needed) to confirm the diff doesn't reintroduce a `CLAUDE.md` landmine or contradict `FRONTEND_PLAN.md`/`SYSTEM_DEVELOPMENT_PLAN.md`.
6. **PR and merge to `main`**, even solo — it's a review checkpoint and keeps `main` demoable at all times, per `CLAUDE.md`.
7. **`/session-end`** before finishing — commits/pushes anything outstanding, updates this file's phase checklist state, appends a `docs/SESSION_LOG.md` entry so the next session (frontend or backend, any machine) resumes cleanly.
8. **Update this roadmap's checklist boxes and `Status:` field** as part of step 7 — exactly like backend phases already do; this file is meant to visibly track progress the same way, not sit static after being written.

**If you want to start today:** Phase 13 has zero blockers — every backend dependency it needs (auth) already shipped. That's the first branch to cut.

---

## Open items surfaced while writing this roadmap (not yet resolved — flag before relevant phase starts)

- **Config-file staleness, not a planning blocker.** `CLAUDE.md` and `.claude/agents/tracex-frontend.md` both still say `fund-flow-tracker/frontend/` in prose (confirmed by reading both files this session). Decision 7 above resolves *where the frontend actually lives* (`frontend/` at repo root) for the purposes of this roadmap and Phase 13's build — but the config files themselves are owned by a **config session**, not this planning session, per `CLAUDE.md`'s own session-type rules. Flag for the next config session: update `tracex-frontend.md`'s description line and `CLAUDE.md`'s references to point at `frontend/`.
- **Phase 14's alert→case assignment mutation target is unconfirmed** — noted inline in Phase 14's scope now (`PATCH /alerts/{alert_id}/assign` vs. a case-level route), since `investigation/cases.py::create_case_from_alert` already auto-assigns on case creation; confirm during implementation which entity a manual *re*-assignment actually needs to mutate.
- **Phase 21's exact `/decision` contract for `closed_tp`/`monitoring`** is a forward guess based on the FSM already existing in `backend/investigation/fsm.py` — the real backend Phase 11 implementation may expose this differently (e.g. a separate `/cases/{case_id}/close` route rather than extending `/decision`'s enum). Not a blocker for planning now — explicitly deferred per the owner's own note this session — just don't treat this roadmap's phrasing as the confirmed contract when Phase 21 actually starts.
