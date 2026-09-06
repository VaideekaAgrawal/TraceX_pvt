# TraceX — Live Demo Script (scripted click-through)

The **demo** counterpart to `docs/PRESENTATION_SPEAKER_NOTES.md` (which covers the
*deck*). One case, walked end to end: **alert → triage → AI recommendation →
cross-question → escalate → compliance close → STR → FIU-IND submission.**

Every number, id, name and screen below is taken from the actual committed demo
database (`data/tracex_demo.db`) and the actual component tree — not written from
memory. If you rebuild the demo DB with `backend/scripts/build_demo_db.sh`, the
fixed `DEMO_SEED = 20260701` reproduces all of it identically.

> **Timing assumption:** written as a **~6-minute** full walk with marked cuts down
> to **~3 minutes**. If your actual demo slot is a different length, cut using the
> "If you're running over" order at the bottom rather than speaking faster.

---

## 0. Pre-flight (do this before the room fills, not during)

### Reset to a known state

The demo mutates the database (a case gets escalated, closed, and an STR gets
filed). It is **not** re-runnable without a reset. Reset from the *committed*
copy, not the working-tree one:

```bash
cd /Users/vedansh.kapoor/tracex-2/TraceX_pvt
git checkout -- data/tracex_demo.db      # only if it shows as modified
cp data/tracex_demo.db data/tracex_demo_live.db
```

`data/tracex_demo_live.db` is the gitignored throwaway the app actually runs
against — `backend/.env` already points `DATABASE_URL` at it. Never demo against
`data/tracex_demo.db` directly; that's the shared committed dataset and every
click would dirty it.

### Start the stack

```bash
# terminal 1
cd backend && .venv/bin/uvicorn api.app:create_app --factory --port 8001

# terminal 2
cd frontend && npm run dev          # → http://localhost:3000
```

Port **8001** is not arbitrary — `frontend/.env.local` has
`BACKEND_API_URL=http://127.0.0.1:8001`. Starting the backend on 8000 will make
every panel fail with no obvious cause.

### Logins

| Who | Username | Password |
|---|---|---|
| Investigator (Act 1) | `investigator1` | `TraceX@2026` |
| Admin/Compliance (Act 2) | `compliance1` | `TraceX@2026` |

Password is `build_demo_db.sh`'s `DEMO_PASSWORD` default — if that DB was built
with the env var overridden, it's whatever was passed instead.

### Pre-flight checklist

- [ ] Live DB reset from the committed copy (above)
- [ ] Backend up on 8001 — `curl localhost:8001/healthz` returns OK
- [ ] Frontend up on 3000
- [ ] **Log in as `compliance1` in a second browser profile / private window
      before you start**, so Act 2 is one tab-switch, not a logout-login on stage
- [ ] AI recommendation panel actually returns (needs a working
      `OPENROUTER_API_KEY` in `backend/.env` — see "If the AI panel fails")
- [ ] Zoom the browser to ~125% — the graph and the panel text are small from the
      back of a room

---

## The case

**`CASE-20260718-13F5F994`** — the highest-risk open case in the dataset.

| | |
|---|---|
| Alert | `ALT-B5A0826EAC55` |
| Typology | `round_trip` |
| ML score | **0.90** |
| Risk score | **87.42** |
| Severity / Priority | HIGH / **P2** |
| Confidence | **"Very Strong"** |
| Network risk | **24** — *1 sanctioned entity, 1 cycle detected, 2 high-centrality accounts* |
| Status at demo start | `IN_PROGRESS`, L1, assigned to `investigator1` |

### The cast — two accounts, and the whole story is in the contrast

**Continental Logistics Pvt Ltd** — `DEMO-ACC-0185`
Current account, Lucknow. Food Processing. Declared income **₹4,00,00,000**.
KYC **VERIFIED**. Risk rating **MEDIUM**. *Looks like an ordinary corporate customer.*

**Suresh Bansal** — `DEMO-ACC-0145`
Savings account, Chennai. Occupation **Retired**. Declared income **₹1,50,000**.
**SANCTIONED.** KYC **REJECTED**. Risk rating **CRITICAL**.

### What actually happened

**June 2025 — the seed.** Suresh Bansal sends Continental Logistics **₹50,000**
by RTGS. A single, unremarkable payment. For the next year his account does
nothing but look like a pension: ~₹19–20K credited monthly, small debits out.
All of it clean (`is_laundering = 0`).

**21 June 2026 — the return.** In one **15-hour window**, Continental Logistics
sends **six transfers of ₹5,00,000 each — ₹30,00,000 total — back to Suresh
Bansal**, at exact three-hour intervals, deliberately rotated across four
different payment rails:

| Time | Amount | Channel |
|---|---|---|
| 00:00 | ₹5,00,000 | NEFT |
| 03:00 | ₹5,00,000 | IMPS |
| 06:00 | ₹5,00,000 | IMPS |
| 09:00 | ₹5,00,000 | UPI |
| 12:00 | ₹5,00,000 | RTGS |
| 15:00 | ₹5,00,000 | UPI |

**₹50,000 went out. ₹30,00,000 came back — 60 times the original amount,**
into the account of a retired, sanctioned, KYC-rejected individual whose declared
annual income is ₹1,50,000. **The return is 20× his entire declared annual income.**

**The context around it.** In the same three weeks, Continental Logistics also
pushed **five branch-cash transfers to four other accounts** — ₹9,39,661 /
₹9,81,136 / ₹9,38,797 / ₹9,78,797 / ₹9,33,341 — **every single one just under the
₹10,00,000 CTR reporting threshold.** That is the exact behaviour Slide 1 of the
deck opens on. This case is not an isolated pair; it's one visible edge of a wider
structure.

*(Five transfers, four distinct accounts — `DEMO-ACC-0089` received two of them.
Say "five cash transfers," not "five accounts.")*

*(Ground truth: every 2026 transaction above is labelled `is_laundering = 1` in
the dataset; the 2025 activity is labelled clean. You don't say this on stage —
it's how you know the story is real and not a coincidence of the seed.)*

---

## Act 1 — The Investigator (≈3:30)

Logged in as **`investigator1`**.

### Beat 1 — Dashboard (0:25)

**Land on `/dashboard`.**

> "This is what an investigator sees when they sit down. Alerts, ranked — and the
> ranking is learned, not a sort by score. The queue adapts to which alerts
> investigators actually confirm."

*Cue: don't linger. Point at the summary cards and the queue, then move.*
*Fallback: if the charts are slow to paint, keep talking over them — they are not the point of this beat.*

### Beat 2 — Open the case (0:20)

**Open `CASE-20260718-13F5F994` from the queue.** It opens as a tab in the
workspace shell.

> "Top of the queue: a round-trip alert on a corporate account. Risk 87. The
> model's confidence is 'Very Strong' — and that phrasing is the model's, not a
> label we painted on afterwards."

*Cue: read the risk score and confidence off the screen, so the panel is doing the talking.*

### Beat 3 — Triage: the contrast (0:50) — **the emotional centre of the demo**

Scroll the **Triage** view: `Alert Summary` → `Customer Snapshot` → `Money Flow`.

> "Customer Snapshot. Continental Logistics — a verified corporate customer,
> four crore declared income, medium risk. Nothing here asks for attention."
>
> "Now the counterparty. Suresh Bansal. Retired. Declared income: one lakh fifty
> thousand. KYC **rejected**. And he's on a **sanctions list**."
>
> "Money Flow. A year ago he sent this company fifty thousand rupees. On the
> twenty-first of June, they sent him **thirty lakh** — six transfers of five
> lakh each, in fifteen hours, rotated across NEFT, IMPS, UPI and RTGS so no
> single rail sees the whole picture. Sixty times what went out, into an account
> that declares one and a half lakh a year."

*Cue: this is where you slow down. Let the ₹1,50,000 vs ₹30,00,000 sit for a beat before moving on. If one thing lands with the panel, make it this.*

### Beat 4 — Network Risk (0:25)

Scroll to **`Network Risk`**.

> "The account-level score is one signal. This is the network score — computed
> across the case's whole subgraph. One sanctioned entity, one closed cycle, two
> high-centrality accounts. The cycle is the round-trip; the centrality is what
> tells you these accounts matter to more than just each other."

*Cut this beat first if you're short on time — Beat 5 is stronger.*

### Beat 5 — AI Recommendation + cross-question (0:50) — **the differentiator**

Open the floating **AI widget → Recommendations**. **Generate this before the
demo starts — it takes 126 seconds** (see the slow-beats warning below).

**What it actually returns on this case** (live-verified, not predicted):

- **`APPLY_ENHANCED_DUE_DILIGENCE`** — rank 1, confidence 0.743, 8 cited facts.
  FATF **R.10** / RBI KYC MD 2016.
- **`FILE_STR`** — rank 2, confidence 0.743, **14 cited facts**. FATF **R.20** /
  **PMLA 2002 s.12**.

> "This is where most systems stop at 'suspicious.' Ours recommends the next
> step — and cites the regulation it comes from. FATF Recommendation 10, PMLA
> section 12. Not a generic LLM suggestion: the action space is a fixed
> catalogue, and a recommendation the case's own detections don't support can't
> be produced at all."

**Then open the rejected toggle — don't skip this, it's your trust beat.** Two
recommendations were thrown out by the grounding gate:
`INVESTIGATE_ROUND_TRIP` (invented a `137.11` velocity ratio) and
`EXPAND_NETWORK_INVESTIGATION` (invented a `4,771,733.37` total).

> "And these two it threw away — because the model quoted a number it couldn't
> trace back to a fact our own code computed. The guardrail isn't a slide; it
> ran on this case."

**Then challenge it.** Paste into the *"Challenge a recommendation…"* box —
**this exact wording, which is the only one verified to survive the gate:**

> `In plain words, and without quoting any statistics or scores, why is this not an ordinary business refund?`

> "And the investigator can push back. This isn't a black box handing down a
> verdict — it has to defend the recommendation against the facts of this case,
> or not answer at all."

*Cue: have this on the clipboard — do not compose it on stage, and do not reword it. Four other phrasings were tested live and all four were rejected.*
*This is the single most differentiating beat in the demo. If you cut everything else, keep this.*

### Beat 6 — Deep view: see the cycle (0:30)

Toggle **Triage → Deep**. Land on **`Investigation Graph`**.

> "The graph is case-scoped — an investigator sees this network, not the bank's
> entire customer base. The loop closes on screen."

Optionally scroll past `Graph Explanation` / `Investigation Timeline`.

*Fallback: if the graph renders collapsed or empty, say "the graph view is here" and move straight to Beat 7 — don't debug on stage. (This exact rendering bug was fixed in `35a2c1ea`, but it's the highest-risk visual in the demo.)*

### Beat 7 — Escalate (0:20)

**Decision panel → "Escalate to Compliance for Review."** Reason:

> `Round-trip to a sanctioned, KYC-rejected counterparty; ₹30L returned against a ₹50K origin.`

> "The investigator does not close this case. They can't — and that's deliberate."

*Cue: this line sets up Act 2. Say it as a feature, not an apology.*

---

## Act 2 — Compliance (≈1:30)

**Switch to the browser window already logged in as `compliance1`.**

### Beat 8 — The review queue (0:20)

> "Different role, different system. Compliance doesn't see the whole alert
> queue — they see exactly what's been escalated to them, and nothing else.
> That's enforced on the server, not hidden in the UI."

The case is now in the `ESCALATED` queue. Open it.

### Beat 9 — Close as true positive (0:20)

**Decision panel → close as True Positive.** Reason:

> `Confirmed round-tripping via sanctioned counterparty. Filing STR.`

> "Only Compliance can close a case. Maker and checker are different people —
> that's the control a bank's audit function will ask about first."

### Beat 10 — STR generation (0:30) — **the payoff**

The **STR/SAR report panel** unlocks *only now* — report generation is gated
server-side on `status == CLOSED_TP`. **Generate report.**

> "And the moment it's confirmed, the report writes itself — in FIU-IND's format,
> from the facts of the case. Every claim in this narrative is cited against a
> value our own code computed. If the AI can't ground a sentence in a real
> number, it doesn't get shown."

### Beat 11 — Finalize & submit (0:20)

**Finalize** → **Submit to FIU-IND** (requires an FIU reference — have one typed:
`FIU-DEMO-2026-0001`).

> "Finalize. Submit. From an alert in a queue to a filed regulatory report —
> one case, one system, full audit trail behind it."

*Cue: stop here. Don't wander back into the app looking for something else to show.*

---

## Closing line

> "Every rupee leaves a trail. That's the whole product."

---

## Numbers to know cold (demo-specific)

These are **in addition to** the deck numbers in `PRESENTATION_PREP_CHECKLIST.md`:

- **₹50,000 out → ₹30,00,000 back** = 60×
- **6 transfers × ₹5,00,000, 15 hours, 4 channels** (NEFT / IMPS / UPI / RTGS)
- **₹1,50,000** declared annual income vs **₹30,00,000** received = **20×**
- Risk **87.42**, ML score **0.90**, confidence **"Very Strong"**
- Network risk **24** — 1 sanctioned entity, 1 cycle, 2 high-centrality accounts
- The five side transfers: **all just under the ₹10,00,000 CTR threshold**

---

## If it breaks

| Failure | What you say / do |
|---|---|
| **AI panel errors or hangs** | "The recommendation layer calls out to a model — I'll describe what it returns." Then say the FATF/PMLA anchor line from Beat 5 from memory and move on. It fails **open** (nothing else in the app breaks). |
| **Graph renders collapsed/empty** | Skip to Beat 7. Do not refresh twice on stage. |
| **A panel 403s** | You're in the wrong role's window. Switch tabs — don't log out mid-demo. |
| **Backend not reachable** | Check it's on **8001**, not 8000 (`frontend/.env.local`). |
| **Case is already escalated/closed** | Someone ran the demo without resetting. Reset (§0) — it takes seconds — or fall back to `CASE-20260718-A718E13E` (layering, 6 accounts, sanctioned primary: Silver Line Exports Pvt Ltd). |

**Have a screen recording of a clean full run on the presenting laptop**, per the
demo-backup item in `PRESENTATION_PREP_CHECKLIST.md`. Same reasoning as the deck's
PDF fallback.

---

## If you're running over — cut in this order

1. **Beat 4 (Network Risk)** — the sanctions fact already landed in Beat 3. *Saves ~25s.*
2. **Beat 6 (Deep view / graph)** — visually nice, but Beat 3 carries the story. *Saves ~30s.*
3. **Beat 1 (Dashboard)** — open the case directly by deep-link instead. *Saves ~25s.*

That floors the demo at roughly **3 minutes**: Beat 2 → 3 → 5 → 7 → 8 → 9 → 10 → 11.

**Never cut Beat 3 (the contrast), Beat 5 (recommendation + challenge), or Beat 10
(STR).** Those three are the demo. Everything else is context around them.

---

## Backup case

**`CASE-20260718-A718E13E`** — layering, 6 accounts, network risk 28 (the highest
in the dataset). Primary: **Silver Line Exports Pvt Ltd** (`DEMO-ACC-0012`,
Surat) — CRITICAL risk, **sanctioned**. A 5-hop chain ₹9,49,996 → ₹9,17,077 →
₹15,00,000 → ₹10,20,000 → ₹6,93,600 that runs *through* the sanctioned entity.
Same script shape; swap the Beat 3 narration.

---

## Verification status — live-fired 2026-09-05

The whole arc was driven against a running backend on the reset live DB. Every
step below returned what this script claims it returns.

| Step | Result | Latency |
|---|---|---|
| `POST /auth/login` (both roles) | 200 | instant |
| `GET /alerts` | 200 — **hero alert is row 1** | instant |
| `POST /cases/{id}/start` | 200 → `IN_PROGRESS` | instant |
| Triage panels (snapshot, money-flow, network-risk, similar-cases) | 200 | <0.02s |
| `POST /recommendations` | 200 — 2 accepted, 2 rejected, 6 iterations | **126s** |
| `POST /recommendations/challenge` | 200 — but `answered: false` (see below) | **76s** |
| `POST /decision` escalate | 200 → `ESCALATED` | instant |
| Compliance queue | 200 — hero case present, queue of 1 | instant |
| `POST /decision` close_tp | 200 → `CLOSED_TP` / `TRUE_POSITIVE_SAR` | instant |
| `POST /cases/{id}/reports` | 201 → `DRAFT` | **113s** |
| `finalize` → `submit` → `pdf` | 200 / 200 / 200 (PDF bytes) | instant |

### ⚠️ The three slow beats — this changes how you record

`recommendations` (126s), `challenge` (76s) and STR generation (113s) are
**agentic loops**, not single LLM calls — 5–6 model round-trips each. Together
that's over five minutes of spinner. Nothing is cached: every click re-runs the
loop.

**You cannot show these generating in real time.** Trigger each one *before* you
start recording that segment and cut to the finished panel.

### ⚠️ The cross-question: use THIS question, verbatim

The grounding gate rejects the AI's own answer whenever it volunteers a number it
can't trace to a cited fact — and on this case, the model reliably reaches for
similarity scores and velocity ratios. **Five different phrasings were tested
live. Four were rejected.** Every rejection was the model quoting a statistic
(`0.37`, `0.999`, `0.9937`, `11.0`) that wasn't in its own cited facts.

**The one that works — type it exactly:**

> `In plain words, and without quoting any statistics or scores, why is this not an ordinary business refund?`

Explicitly forbidding statistics stops the model reaching for the numbers that
get it rejected, and the grounded answer that survives is genuinely strong:

> *"The business account received a tiny initial payment from a retired individual
> and then, almost a year later, sent back sixty times that amount in a single
> day… The six payments back to the retiree were sent in rapid succession on the
> same day using different channels, which is inconsistent with how businesses
> process legitimate refunds. The business account was dormant for nearly a year,
> then suddenly reactivated to move millions through multiple accounts in a short
> burst."*

Note it independently reached the **same 60× figure** the narration uses.

**Do not improvise a different challenge question on camera.** These four were all
rejected live: *"Why not just close this as a legitimate business refund?"*,
*"Could this simply be a legitimate loan repayment between two customers?"*,
*"What makes this different from an ordinary business refund?"*, *"Is the
sanctions match on its own enough to justify filing?"*

If it does get rejected on the day, the honest framing is still a strong line, not
a failure: **"it refused to answer rather than give me a number it couldn't stand
behind."** The narration at `[1:44]` is written to stay true either way.

### What the recommendation panel actually returns for this case

**Accepted (2):**
1. `APPLY_ENHANCED_DUE_DILIGENCE` — confidence 0.743, 8 cited facts.
   FATF R.10 / RBI KYC MD 2016.
2. `FILE_STR` — confidence 0.743, **14 cited facts**. FATF R.20 / PMLA 2002 s.12.
   Its narrative cites the 87.42 risk score, **four similar historical cases that
   all closed as `TRUE_POSITIVE_SAR`**, the ₹9,43,912.50 cash deposit into
   `DEMO-ACC-0145` immediately before the round-trip began, 38.6% of dispersed
   funds returning in the circular pattern, and the network's 1 sanctioned entity.

**Rejected by the grounding gate (2)** — visible behind the panel's rejected
toggle, and worth showing deliberately:
- `INVESTIGATE_ROUND_TRIP` — stated a velocity ratio of `137.11` that wasn't in
  any cited fact.
- `EXPAND_NETWORK_INVESTIGATION` — stated a `4,771,733.37` dispersal total that
  wasn't in any cited fact.

Note the irony worth naming out loud: the model's *round-trip* recommendation was
thrown out for sloppiness, and the system still recommended filing an STR on
grounds it could fully support. **`FILE_STR` being the surviving recommendation is
the demo's own punchline** — the AI recommends filing, and then you file.

### Still unverified

- **Rendering** of the Investigation Graph in the browser for this case (API
  verified; the visual was not).
- The generated STR narrative reads **raw** — it prints `40000000.0` and
  `CLOSED_TP` rather than "₹4 crore" and "closed as true positive". It is
  accurate and grounded, but don't zoom into the body text on camera; show that
  the report exists, is finalized, and is submitted.
