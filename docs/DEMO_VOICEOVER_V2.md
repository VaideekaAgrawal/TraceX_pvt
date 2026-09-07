# TraceX — Demo Voiceover V2 (Investor Cut)

A second narration track, for a different audience than `DEMO_VOICEOVER.md`.

**V1** is written for a bank's own investigators — a tight, unhurried "here's my
Tuesday morning" script. **V2** is for the room that matters more right now: a
**Global Fintech Fest investor audience** and Union Bank stakeholders deciding
whether to fund/pilot this. It keeps V1's device — an investigator working a
real case, in first person — because that's still the best way to show the
product without it turning into a feature tour. But it:

- **Covers more of the USP surface.** V1 doesn't touch the network risk score,
  the pattern explanation panel, the similar-historical-cases panel, the
  ranked/re-ranked queue, watchlist-driven monitoring, or graph replay. This
  script puts all six on screen, because they're the differentiators an
  investor needs to see, not just the round-trip story.
- **Names the "three systems" explicitly and correctly.** The confidence label
  on this platform comes from three independent signals agreeing — an ML
  classifier, a rules engine, and a graph/network analysis engine. (It does
  **not** include the IsolationForest anomaly score — that scorer's output is
  currently dead code in this build, never read into the confidence formula.
  Do not claim a fourth system. See `docs/SESSION_LOG.md` if this changes.)
- **Lets value land as a line, not just an implication.** V1 is deliberately
  restrained — the investigator never says "this is good for the bank." For an
  investor audience, a handful of moments (marked below) earn one direct
  sentence tying what was just shown to bank economics: fewer false positives,
  faster investigations, audit defensibility, staff-onboarding cost. Everywhere
  else, the benefit still stays implicit in what the investigator does and
  notices — same restraint as V1.
- **Is explainable to a non-technical audience.** No "XGBoost," no "LinUCB
  contextual bandit," no "IsolationForest," no "ego-graph." Every ML/graph
  concept is translated to plain language in the script itself — see the
  glossary at the bottom if you need the technical mapping while recording.

**Total: ~4:45** (longer than V1's 3:00 — it's carrying six more panels).
Trim options are listed at the end if a take runs long.

---

## Before you record: five things to verify live

V1 earned its numbers by running the case for real (see its own Production
Notes and `docs/DEMO_SCRIPT.md` → Verification). This script reuses every one
of those verified numbers unchanged. It also adds five panels that weren't
part of V1's verified run — **do not record until you've confirmed these
against the actual reset case**, the same way V1's challenge-question wording
was tested before being locked in:

1. **Network risk score value** — the actual number the network-risk panel
   shows for this case (marked `[VERIFY]` below).
2. **Pattern-explanation exact wording** — the panel's actual generated text
   for this alert may not match the paraphrase below word-for-word; reread it
   live and adjust the spoken line to match what's genuinely on screen.
3. **Graph replay run time** — confirm the six-transfer cluster actually plays
   back as a legible, distinct sequence at normal speed, and note what speed
   multiplier (the control supports 1×–8×) makes the demo clip land inside its
   18-second slot.
4. **Watchlist demo data** — confirm `prep_demo_live.py` actually seeds a
   watchlisted entity with a fresh alert in its history. If it doesn't, add
   one manually before recording: `POST /watchlist` on a suitable account,
   then let a detection run (or the seeded historical data) generate an alert
   against it, so the Monitoring panel has something real to show, not an
   empty list.
5. **Similar Historical Cases outcomes** — read the actual top-3 results and
   their outcomes off the panel for the hero case; the spoken line is written
   generically ("most confirmed, one legitimate") specifically so it can be
   adjusted to match whatever the panel genuinely returns, rather than
   asserting counts that weren't checked.

Run `cd backend && .venv/bin/python scripts/prep_demo_live.py` first, exactly
as V1 requires — same hero case, same reset step.

---

## Delivery direction

Same voice as V1: a working investigator, calm and unhurried, faintly dry. The
facts do the selling — the delivery should not. The lines marked **(value
beat)** are the only places where the register shifts slightly: still the
investigator's voice, but said the way someone says something they've
noticed is genuinely rare, not read to camera as a slogan.

1. **Numbers get room.** Every rupee figure and every score lands alone, with
   a beat after it.
2. **The contrast at ~1:00 is still the emotional core.** Don't let the four
   extra feature panels crowd it — if anything runs long, that block is the
   one that must not be cut (see trim options).
3. **No upward inflection at line ends.** An investigator reporting findings,
   not pitching a product — even in the value-beat lines.

`(...)` marks a pause. **Bold** marks the stressed word. `—` is a short breath.

---

## The script

### `[0:00 – 0:31]` — Cold open: the ranked queue, and the watchlist
**Screen:** Alert queue, full list visible, risk/confidence badges showing. Cursor idle, then moves to the top row. Then a quick cut to My Center → Monitoring — the watchlist panel — showing the watched entity with its new alert listed under "Alerts Since Added." Cut back to the queue.

> Every day, this bank's ledger produces thousands of transactions. This queue
> is what's left after the system has already decided which of them deserve a
> person's time.
> (...)
> It isn't sorted by time. It's sorted by risk — then reshuffled again by a
> reinforcement-learning system that's watched every case my team has ever
> closed. When something looks like the false positives we've already ruled
> out, it gets pushed down. When it looks like the frauds we've confirmed, it
> moves up.
> (...)
> **(value beat)** And if an account is already being watched — flagged once
> before, kept under monitoring instead of filed away — a new alert on it
> doesn't wait in this line at all. It jumps straight to the top.
> (...)
> I don't have to take the system's word for that, either. This is my own
> watchlist — and there's the same account, the same new alert, sitting right
> in its history the moment it landed. `[VERIFY: confirm the reset demo case seeds a watchlisted entity with a fresh alert — see Production Notes]`
> (...)
> This is what's sitting at the top of my queue this morning.

*Delivery: flat, procedural. A person sitting down at their desk. The value-beat line and the watchlist aside get the same restrained treatment as the others — a fact stated, not sold. The watchlist line reads like someone double-checking, not demonstrating a feature.*

---

### `[0:31 – 0:48]` — The alert: three systems, one confidence
**Screen:** Click the top alert → case opens. Alert Summary panel, confidence badge visible.

> A round-trip alert. Risk score: **eighty-seven**. (...) Confidence — **very
> strong**.
> (...)
> That confidence isn't one model's opinion. Three separate systems looked at
> this account — a machine-learning model trained on transaction behaviour, a
> rules engine that knows the shape of known laundering patterns, and a
> network analysis engine that looks at who this account sits next to. (...)
> All three agreed.
> (...)
> **(value beat)** One system flagging something is a hint I can ignore on a
> busy day. Three agreeing is something I can act on — and something a
> regulator can't wave away either.

*Delivery: "very strong" read as if quoting the screen. The value-beat line gets a half-step more weight, not more speed.*

---

### `[0:48 – 1:04]` — Network risk score
**Screen:** Network risk score panel/badge, shown separately from the account's own risk score.

> There's a second number here, separate from the account's own score — a
> **network** risk score.
> (...)
> It isn't asking "is this account suspicious." It's asking "is this account
> sitting inside a suspicious web of other accounts" — including ones that
> look completely clean on their own.
> (...)
> `[VERIFY: read the actual score off the panel]` — high enough that I widen
> the investigation before I've opened a single transaction.

*Delivery: this is the first time the investigator looks past the one account — a small shift in posture, not just tone.*

---

### `[1:04 – 1:36]` — The contrast **(core of the demo — protect this block)**
**Screen:** Customer Snapshot. Continental Logistics first, then scroll to Suresh Bansal.

> Two accounts.
> (...)
> The first is Continental Logistics. A corporate customer. Four crore
> declared income. KYC verified. Medium risk. (...) Nothing about this account
> asks for my attention.
> (...)
> **The second one does.**
> (...)
> Suresh Bansal. **Retired.** Declared income — one lakh fifty thousand
> rupees. (...) His KYC was **rejected**. (...) And he is on a **sanctions
> list**.

*Delivery: identical to V1 — the longest pause in the script sits before "The second one does." Do not compress this to make room for the new panels.*

---

### `[1:36 – 1:52]` — Pattern explanation
**Screen:** Pattern-explanation panel for this alert — the "why was this flagged" text.

> Before I even open a transaction, the system has already written down why it
> flagged this pair. Plain words — not a score. `[VERIFY exact wording, then paraphrase to match]`
> money leaves, disappears for a year, comes back at sixty times the amount,
> through a channel that keeps changing.
> (...)
> **(value beat)** I didn't need to be a data scientist to trust that. Neither
> will the analyst who inherits this case after I've moved on.

---

### `[1:52 – 2:08]` — Similar historical cases
**Screen:** Triage panel → Similar Historical Cases card. Expand from the top-3 view.

> And I'm not looking at this cold. The system pulls up past cases that had
> the same type as this one — `[VERIFY: read the actual outcomes off the panel for this case]`
> filed exactly the way I'm about to file this
> one. One turned out to be legitimate, for a reason that plainly doesn't
> apply here.
> (...)
> **(value beat)** I'm not starting from zero. I'm standing on every case my
> colleagues have already closed — and it's the same judgment behind the
> queue ordering, made visible.

*Delivery: this line explicitly ties back to the queue's opening claim — say it like a connection being noticed, not a callback being performed.*

---

### `[2:08 – 2:40]` — The money, and the AI account explanation
**Screen:** Money Flow panel — the single 2025 payment, then the 21 June cluster. Then the AI explanation panel beside it.

> Here's what actually passed between them.
> (...)
> Last June, Suresh sent the company **fifty thousand rupees**. One payment.
> (...) Then nothing — for a year.
> (...)
> On the twenty-first of June, in **fifteen hours**, the company sent it back.
> Six transfers. Five lakh each. (...) **Thirty lakh rupees.**
> (...)
> Sixty times what went out — into the account of a retired man who declares
> one and a half lakh a year.
> (...)
> And next to the numbers, the system has already written this up in plain
> English. **(value beat)** The same explanation, whether it's read by me, a
> new hire, or an auditor eighteen months from now.

*Delivery: "Thirty lakh rupees" is still the peak. Let the pause after it do the arithmetic before moving to the value beat.*

---

### `[2:40 – 2:56]` — How it moved
**Screen:** Transaction rows — the six transfers, channel column visible. Then the branch-cash transfers.

> And look at how it moved. NEFT. IMPS. UPI. RTGS. (...) Rotated every three
> hours, so no single payment rail ever sees the whole picture.
> (...)
> In those same three weeks, the company pushed **five cash transfers** to
> four other accounts. Every one just under the ten lakh reporting threshold.

---

### `[2:56 – 3:08]` — Graph explanation
**Screen:** Toggle to Deep view. Investigation Graph — the cycle visible.

> The graph makes it visual. Money out, money back, through a sanctioned
> counterparty.
> (...)
> And there's a written explanation sitting right beside it, so nobody has to
> trace the lines by hand to know what they mean.

---

### `[3:08 – 3:26]` — Graph replay
**Screen:** Graph replay controls — press play, timeline scrubs through the 21 June cluster.

> I can also replay it.
> (...)
> Watch the same fifteen hours happen in order. Six transfers, each one
> landing before the last could raise a flag on its own.
> (...)
> **(value beat)** This is the same timeline a regulator will eventually ask
> for. I'm not rebuilding it by hand from six separate statements — it's
> already here, and it plays.

*Delivery: let the replay actually run on screen while this is spoken — the pacing of the words should roughly track the pacing of the transfers appearing.*

---

### `[3:26 – 3:58]` — The AI recommendation copilot
**Screen:** AI widget → Recommendations (pre-generated — see Production Notes). Show the two accepted, open the rejected toggle, then the challenge box.

> This is where it stops being a dashboard.
> (...)
> It tells me what to do next — and which rule it comes from. FATF
> Recommendation ten. (...) The PMLA.
> (...)
> And **two more it threw away on its own** — because the numbers behind them
> didn't check out against our own data.
> (...)
> I can question it, too. Why not close this as a legitimate business refund?
> (...)
> It answers from the facts of **this** case — or it doesn't answer at all.
> (...)
> **(value beat)** For a bank, that line is the whole point. An AI that either
> proves what it says or says nothing. Never one that guesses and hopes.

**Type this challenge question, exactly — the only one verified to survive
the grounding gate (see `DEMO_VOICEOVER.md` for the four rejected phrasings):**

> `In plain words, and without quoting any statistics or scores, why is this not an ordinary business refund?`

**The two rejected recommendations, real and worth showing on screen:**
`INVESTIGATE_ROUND_TRIP` (invented a `137.11` velocity ratio) and
`EXPAND_NETWORK_INVESTIGATION` (invented a `4,771,733.37` total). What
survived was `FILE_STR`.

---

### `[3:58 – 4:10]` — Escalate (maker–checker)
**Screen:** Decision panel → Escalate to Compliance. Reason typed. Submit.

> I've seen enough. I escalate.
> (...)
> And here's the part a bank will ask about first: **I cannot close this case
> myself.** (...) I investigate. Someone else decides.

*Delivery: say "I cannot close this case myself" with a touch of pride — a designed limit, not a bug.*

---

### `[4:10 – 4:25]` — Compliance and the STR
**Screen:** Switch to the compliance window. Close as true positive → STR panel unlocks → Generate → Finalize → Submit.

> Compliance picks it up. Confirms it. (...) Only now does the report unlock.
> (...)
> FIU-IND format, written from the case itself — every claim cited to a
> number the system computed. **(value beat)** Not one the model invented.

---

### `[4:25 – 4:45]` — Close
**Screen:** The filed report on screen. Hold still. No cursor movement.

> Alert, to filed report.
> (...)
> **(value beat)** What used to be half a day, jumping between four separate
> systems to build one case, just took me a fraction of that.
> (...)
> One ranked queue that's learned what a false alarm looks like. Three
> systems agreeing before I ever look. An AI that only speaks when it can
> prove it. And a trail nobody has to reconstruct by hand.
> (...)
> For a bank, that isn't a better dashboard. **(value beat)** That's fewer
> false alarms, faster investigations, and a report that holds up when
> someone asks how we knew.
> (...)
> **Every rupee leaves a trail.**

*Delivery: full stop. Two seconds of silence before the cut, same as V1.*

---

## Production notes

Everything from V1's Production Notes section applies unchanged (pre-generate
the slow AI panels before recording — recommendations and cross-question are
agentic loops measured at 126s/76s live; reset with `prep_demo_live.py` before
every take; two pre-logged-in browser windows; 1440p+, ~125% zoom; cursor
discipline). Additional notes for the panels new to this cut:

1. **Network risk score, pattern explanation, and similar historical cases are
   not agentic loops** — they're server-computed facts (a similarity lookup
   over stored feature vectors, not an LLM call), so they should render fast.
   No pre-generation needed, but load each panel once before recording to warm
   any cache and confirm the copy fits the read.
2. **Graph replay is a frontend-only timeline scrubber** (no new backend call
   per tick) — safe to record live rather than pre-rendering. Rehearse the
   play button placement once so the click doesn't stall on camera.
3. **Don't let the queue re-ranking claim get ahead of the demo.** The cold
   open only shows the queue *as currently ordered* — it does not need to
   demonstrate the reranking happening live. The spoken line describes what
   produced this ordering, not an action performed on screen.
4. **The watchlist panel does not visually highlight new alerts today.**
   Confirmed in code: entries in "Alerts Since Added" render with no badge,
   unread marker, or age-based styling — they're just listed, newest first.
   The script's watchlist line is written to match this honestly (the
   investigator *finds* the alert already listed, rather than claiming it was
   flagged/highlighted for them) — do not stage the shot to imply a visual
   alert that the product doesn't have. If a highlight badge gets built later,
   this line can be tightened to say so directly.
5. **The "reinforcement-learning" line is a defensible simplification, not the
   precise term.** The engine is a LinUCB contextual bandit — a narrower
   technique than general RL (single-step reward per case closure, no
   sequential planning). "Reinforcement learning" is acceptable as a loose,
   audience-appropriate umbrella term for an investor demo; do not have the
   investigator claim anything more specific (e.g. "it plans ahead" or
   "it simulates outcomes") that would overclaim the mechanism. The reward
   signal itself is real and precisely as described: confirmed fraud and
   monitoring outcomes push an alert's profile up, false positives push it
   down (`investigation/rl_features.py:29-37`).
6. **The time-saving line in Close is deliberately unquantified.** It reuses
   the bank's own established framing from `docs/GFF26_PPT_CONTENT.md`
   ("a 15–30 minute triage instead of a half-day evidence hunt") rather than
   inventing a number for this specific recording. Don't replace "a fraction
   of that" with a specific minute count unless it's been timed on this exact
   take.

---

## Word/timing budget (estimated — re-time once locked)

Unlike V1's table, these numbers are **not yet measured against a rendered
track** — V1's were confirmed by actually running `scripts/make_voiceover.py`;
this script hasn't been rendered yet. Treat the seconds below as a drafting
target, then regenerate for real once the `[VERIFY]` lines are filled in:

| Block | Start | Slot (target) | On screen |
|---|---|---|---|
| Cold open / ranked queue / watchlist | 0:00 | 31s | Alert queue → Monitoring panel |
| Alert / three systems | 0:31 | 17s | Alert Summary |
| Network risk score | 0:48 | 16s | Network risk panel |
| **The contrast** | **1:04** | **32s** | **Customer Snapshot** |
| Pattern explanation | 1:36 | 16s | Pattern explanation panel |
| Similar historical cases | 1:52 | 16s | Similar Cases card |
| Money + AI account explanation | 2:08 | 32s | Money Flow + AI panel |
| How it moved | 2:40 | 16s | Transaction rows |
| Graph explanation | 2:56 | 12s | Investigation Graph |
| Graph replay | 3:08 | 18s | Replay controls |
| **AI copilot + challenge** | **3:26** | **32s** | **Recommendations panel** |
| Escalate | 3:58 | 12s | Decision panel |
| Compliance + STR | 4:10 | 15s | Report panel |
| Close | 4:25 | 20s | Filed report |
| **Total** | | **~4:45** | |

**If a take runs long, in this order:**
1. Cut "How it moved" to just the four rail names + threshold sentence (~6s).
2. Cut "Graph replay" to the play action with no spoken line but the value
   beat (~10s) — the visual still lands without narration.
3. Drop "Network risk score" entirely and fold its value beat into the
   three-systems line (~14s) — it's the newest, least load-bearing beat.
4. Cut "Similar historical cases" entirely (~16s) — the queue's opening RL
   line already carries the "learned from past cases" idea on its own.
5. Cut the watchlist panel visit out of the cold open, keeping only the
   spoken value-beat line with no screen cut (~10s) — the queue still reads
   fine as "sorted by risk, then reshuffled by outcomes" alone.
6. Cut the time-saving line out of Close (~6s) if the ending is running long
   — it's a bonus beat, not the close's point.
7. **Never cut:** the contrast, the money, the AI copilot's challenge
   exchange, or the final two lines of the close.

To actually render this once finalized, add its text as a new block set in
`scripts/make_voiceover.py` (or a `--script v2` flag if you want both tracks
selectable) — see V1's "Rendering the audio" section for the `edge-tts`
setup, voice choice rationale (Indian-English pronounces "lakh"/"crore"
correctly), and padding-to-slot behavior. Not done as part of writing this
script; flag if you want it wired up next.

---

## Glossary (for whoever records this — keep off screen and unspoken)

| Script says | Actually is |
|---|---|
| "a machine-learning model trained on transaction behaviour" | XGBoost fraud classifier |
| "a rules engine that knows the shape of known laundering patterns" | Rule-based pattern detectors (`backend/detection/detectors/*`) — layering, structuring, round-trip, dormancy, fan-out |
| "a network analysis engine that looks at who this account sits next to" | Graph centrality signals (PageRank, betweenness) feeding `compute_confidence` |
| "reshuffled again by a reinforcement-learning system... false positives... pushed down... confirmed frauds... moves up" | `rank_alert_queue` (`investigation/prioritization.py`) sorts by `risk_score`, then a `LinUCBAgent` contextual bandit reranks the top 200. Reward signal is real investigator feedback: `CLOSING_REWARD` (`investigation/rl_features.py:29-37`) maps `TRUE_POSITIVE_SAR`→+1.0, `FALSE_POSITIVE`→−0.3, `ENHANCED_MONITORING`→+1.0, persisted to the `rl_arm_state` table on every case close. "Reinforcement learning" is a loose but defensible umbrella term — the precise term is contextual bandit (no sequential planning) |
| "the system pulls up past cases that had the same shape... most confirmed fraud... one legitimate" | Similar Historical Cases (`investigation/similar_cases.py`) — cosine similarity between the current case's 16-dim RL context vector and every resolved case's stored vector, top-k with outcomes, surfaced in the workspace triage panel |
| "what used to be half a day... just took me a fraction of that" | Reuses the bank's own established claim from `docs/GFF26_PPT_CONTENT.md` ("a 15–30 minute triage instead of a half-day evidence hunt") — deliberately not a new fabricated number |
| "a network risk score" | `network_risk.py` — a 0–100 score aggregating role/cycle/centrality across the case's linked accounts, distinct from any single account's own risk score |
| "the system has already written down why it flagged this pair" | Pattern-explanation endpoint, generated only from the persisted alert's `detection_type`/`rule_ids`/`score` |
| "the system has already written this up in plain English" (account panel) | AI account-explanation panel — server-computed facts only, narration/purpose fields excluded, cached |
| "a written explanation sitting right beside" the graph | AI graph-explanation panel |
| "it tells me what to do next... or it doesn't answer at all" | Recommendation engine + Investigation Copilot Q&A, both behind the grounding gate (three independent checks: citation resolves, cited value matches, every number in prose is grounded) |
| "if an account is already being watched... a new alert on it... jumps straight to the top" | Watchlist screening (`backend/investigation/watchlist.py`) — a flagged entity's new alerts are auto-escalated to P1 priority regardless of computed score; separately, `CaseResolution.ENHANCED_MONITORING` lets a case be closed as "keep watching" instead of confirmed-fraud/false-positive |

**Not claimed, deliberately:** IsolationForest anomaly scoring is not
mentioned anywhere in this script. Its output does not currently feed the
confidence label — see `backend/detection/scoring/ensemble.py`. If that
changes in a future session, this script (and the "three systems" line) needs
updating to match, not before.
