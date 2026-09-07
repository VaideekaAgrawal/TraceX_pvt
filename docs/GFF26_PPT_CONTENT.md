# TraceX — GFF '26 Deck Content
### Global Fintech Festival 2026 · PSB Hackathon Winner (Union Bank of India × iDEA 2.0)

> **This file is the script.** The deck itself is **`docs/TraceX_GFF26.pptx`**
> (16:9, minimum font 18pt, white background, 12 slides + 4 appendix).
> Regenerate it with `python docs/build_gff26_deck.py [--video demo.mp4]`.
> The on-slide text below matches the deck exactly — if you edit one, edit both.

---

## Deck brief

| Constraint | Decision |
|---|---|
| Total time | **8:00 hard ceiling, including the demo video** |
| Speaking time | **~5:50** across 11 spoken slides |
| Demo video | **2:00**, slide 5 |
| Aspect ratio | 16:9 (13.333in × 7.5in) |
| Minimum font | 18pt — enforced in the build; nothing smaller exists in the file |
| Audience | Bank leadership, regulators, investors — **product and business people, not engineers** |
| Register | Story-led: problem → stakes → idea → proof → trust → scale → commercial → ask |

**The one rule for this audience:** every technical fact on a slide answers a *business*
question — "can I trust it," "will it break," "will it get me fined," "what does it cost."
Never state a technical fact for its own sake.

## Timing plan

| # | Slide | Time | Cumulative |
|---|---|---|---|
| 1 | Cover | 0:15 | 0:15 |
| 2 | The problem | 0:45 | 1:00 |
| 3 | The idea | 0:40 | 1:40 |
| 4 | The workflow | 0:35 | 2:15 |
| 5 | **DEMO VIDEO** | 2:00 | 4:15 |
| 6 | Why this is different | 0:30 | 4:45 |
| 7 | Trusted AI | 0:35 | 5:20 |
| 8 | Security, privacy & compliance | 0:45 | 6:05 |
| 9 | Scale & deployment | 0:45 | 6:50 |
| 10 | Proof | 0:30 | 7:20 |
| 11 | Business model | 0:35 | 7:55 |
| 12 | Close | 0:15 | 8:10 |

Lands at **~8:10 with zero slack** — this needs a stopwatch rehearsal, not a guess. If
you're consistently over, use the cut order at the bottom. Do **not** speed up.

---

# SLIDE BY SLIDE

---

## Slide 1 — COVER · 0:15

> UNION BANK OF INDIA × iDEA 2.0
> # TraceX
> From suspicious signals to defensible decisions.
> AI-powered AML detection & investigation intelligence
> *Every rupee leaves a trail. TraceX makes it impossible to hide.*
> PSB Hackathon Winner · Global Fintech Festival '26 · Vaideeka Agrawal · Team syntax_error

**Say (with the slide already up):**
> "Good afternoon. I'm Vaideeka. This is TraceX — an AI investigation platform for
> anti-money-laundering, built for Union Bank of India, and one of the winning solutions
> from the PSB hackathon."

---

## Slide 2 — THE PROBLEM · 0:45

**Title:** The alerts aren't the problem. Clearing them is.

**Three stat chips:**

| ₹54 Cr | 90–95% | 21 bn |
|---|---|---|
| RBI penalties levied in FY25 | of AML alerts are false positives | UPI transactions in one month, +29% YoY |

**THE DETECTION GAP**
A single transaction looks normal alone. Launderers structure below ₹10 lakh because
row-by-row rules can't see across accounts.

**THE INVESTIGATION GAP**
Every alert still needs a human to assemble evidence by hand across four systems.
The queue grows faster than the team.

**Banner:** Undetected. Unresolved. Unreported. — and the penalty lands on the bank.

**Say:**
> "Every bank in this room already monitors millions of transactions. That's not where it
> breaks — it breaks afterwards. Ninety to ninety-five percent of AML alerts turn out to be
> false positives, and every single one still needs a human being to pull the evidence
> together by hand. Meanwhile the sophisticated money moves in the gap: structured below the
> reporting threshold, split across accounts, layered through hops no row-by-row rule will
> ever connect. RBI issued fifty-four crore rupees in penalties last financial year. That
> number isn't a detection failure. It's a resolution failure."

*Cue: point at the two gap boxes as you name them, then at the banner.*

---

## Slide 3 — THE IDEA · 0:40

**Title:** What if AML could detect, investigate — and learn?

**01 DETECT** — Six typology detectors plus dual ML, reading the live transaction graph.
**02 PRIORITISE** — Ranked by risk, network context, and what past cases actually proved.
**03 INVESTIGATE** — Money flow, relationships and multi-hop activity on one screen.
**04 EXPLAIN** — Plain language — every claim cited to a fact the system computed.
**05 DECIDE** — Recommend: False Positive · Monitor · Escalate · Report.
**06 LEARN** — Every verdict re-ranks the queue and updates rule confidence.

**Banner:** Every investigation makes the next investigation smarter.

**Say:**
> "TraceX closes the loop. It detects — six money-laundering typologies plus two machine
> learning models, reading the transaction graph rather than one row at a time. It
> prioritises, so your best investigator opens the case that matters most, not the case that
> arrived first. It investigates — the money flow, the relationships, the customer profile,
> all assembled before the analyst sits down. It explains that evidence in plain language.
> It recommends a decision. And then the part that compounds: every verdict your
> investigators give goes back in as a learning signal. The system gets sharper with use."

---

## Slide 4 — THE WORKFLOW · 0:35

**Title:** One alert. One defensible decision.

**Chevron strip:** 01 DETECT → 02 PRIORITISE → 03 TRACE → 04 UNDERSTAND → 05 EXPLAIN → 06 DECIDE → 07 REPORT

**EVIDENCE, PRE-ASSEMBLED** — Profile, history, network and prior cases already on screen. No system-hopping.
**EXPLANATION, NOT JUST A SCORE** — A written narrative of why this account is suspicious, every fact traceable.
**REPORT, IN ONE CLICK** — An integrity-protected record in FIU-IND structure, generated — not re-keyed.

**Banner:** A 15–30 minute triage — instead of a half-day evidence hunt.

**Say:**
> "This is the entire journey, and the point is that it's one journey. Today an investigator
> jumps between four systems to build one case. Here, detection hands off to prioritisation,
> prioritisation to investigation, investigation to a written explanation, and that
> explanation to a report in FIU format — without the analyst re-keying anything. We designed
> the front line around a fifteen-to-thirty-minute triage decision. Let me show you."

---

## Slide 5 — DEMO VIDEO · 2:00

**Title:** See it work. One alert, start to finish.
**Caption:** Detect › Prioritise › Investigate › Trace › Explain › Recommend › Report › Learn

**Before you hit play:**
> "Two minutes. One real alert, all the way to a filed report."

**After it ends, bridging into slide 6:**
> "What you just watched hinges on one idea."

**Say nothing over the video.** Let it run.

**⚠️ Pre-flight — non-negotiable:**
- The video must be **embedded in the .pptx**, not linked and not streamed. Either rerun the
  build as `python docs/build_gff26_deck.py --video path/to/demo.mp4`, or in PowerPoint use
  **Insert → Video → This Device** on slide 5.
- Keep the source `.mp4` in the same folder as the deck as a fallback.
- Test audio levels on the **venue** machine, not your laptop.
- Have the video open in a second window, ready to alt-tab, if the embed misbehaves.

---

## Slide 6 — WHY THIS IS DIFFERENT · 0:30

**Title:** A transaction is a row. Crime is a network.

**TRADITIONAL VIEW — `A → B → C → D`**
– Four transactions
– Four rows, four separate alerts
– No context, no connection

**THE TRACEX VIEW — `A → B → C → D → A`**
• Layering — funds moving through multiple hops
• Circular flows — money returning to origin
• Mule networks — accounts as intermediaries
• Hidden links — shared PAN, zero transactions

**Banner:** The suspicious transaction is rarely the crime. The network is the evidence.

**Say:**
> "A rules engine asks: did this transaction cross a threshold? TraceX asks: does this
> behaviour, in this network, form a suspicious pattern? Same four transactions on the left
> and the right. On the left they're four rows and four separate alerts. On the right they're
> one circular flow — money leaving an account and coming back to it. That's the case. And
> notice the last line: customers connected by a shared PAN or a shared employer, with no
> transactions between them at all. No transaction monitoring system on earth will surface
> that relationship, because there is no transaction to monitor."

---

## Slide 7 — TRUSTED AI · 0:35

**Title:** AI that accelerates investigators — and never decides.

**GROUNDED** — The AI can only state facts our system computed. A validator drops any
sentence that doesn't cite one. → *No fact, no claim.*

**BLIND TO PII** — Customer names never reach the model. Not de-identified — absent, behind
a fail-closed gate. → *Enforced in code, not policy.*

**ACCOUNTABLE** — Every investigator action and AI interaction writes to a tamper-evident
audit chain. → *The AI recommends. A human decides.*

**Strip — what this means for the bank:** Higher throughput · Standardised case files ·
A trail that survives RBI inspection

**Say:**
> "This is the part a compliance officer asks about first, so let me answer it before you
> ask. Our AI is not allowed to be creative. Every factual claim it makes has to cite a
> number our own code computed — and a separate validator checks that citation after the
> text is generated and deletes anything that doesn't resolve. We have watched that gate fire
> in a live test: the model stated a figure that appeared in no cited fact, and it was
> rejected before a human saw it. Second: customer personal data never reaches the model at
> all — enforced in code, not promised in a policy. And third, everything is logged. The AI
> recommends. A human decides. Always."

---

## Slide 8 — SECURITY, PRIVACY & COMPLIANCE · 0:45

**Title:** Built for the regulator — not just for the demo.

**DPDP ACT 2023 — BY DESIGN**
• Runs inside your perimeter — you stay fiduciary
• Legal-obligation ground covers AML (PMLA 2002)
• The AI layer stores identifiers, never names
• PMLA's 5-year retention overrides erasure

**PMLA · RBI · FATF**
• 5-year retention: transactions, cases, STRs
• Detectors mapped to FATF Recs. 10 and 20
• Dormancy and structuring follow RBI guidance
• STR output follows FIU-IND structure

**ACCESS & DATA-LEAKAGE CONTROL**
• Two roles, enforced server-side on every route
• Case-scoped visibility — never the whole ledger
• Identifiers tokenised with a separate key
• Self-host the model and nothing leaves your DC

**CYBER POSTURE**
• SHA-256 audit chain across 693,102 rows
• Non-root, read-only containers, caps dropped
• Zero secrets in code — injected from your vault
• CI gate: 726 tests, 97.7% coverage, no bypass

**Say:**
> "Four things your risk committee will ask, answered. One — the DPDP Act. TraceX runs inside
> your perimeter as a processor; the bank keeps custody of its own data. AML processing sits
> under the Act's legal-obligation ground, because PMLA requires it — and where the Act's
> right to erasure would collide with PMLA's five-year retention, the Act permits retention.
> We've written our policy to that line. Two — access. Two roles, enforced on the server, not
> in the interface. We tested that by calling the API directly and bypassing the UI entirely;
> you get a real permission error. Three — leakage. Every investigator, and the AI, sees only
> the neighbourhood of their own case. Never the whole ledger. And if you self-host the model,
> nothing leaves your data centre at all. Four — tamper evidence. Our audit log is a
> cryptographic chain. Edit one record and every record after it fails verification. We proved
> that across six hundred and ninety-three thousand rows."

*Cue: **slow down here.** This is the slide that converts a curious bank into a piloting
bank. Don't rush it even if you're behind.*

---

## Slide 9 — SCALE & DEPLOYMENT · 0:45

**Title:** 100,000 transactions a day? That's three minutes.

| **5.08 M** | **~646/sec** | **~2.6 min** |
|---|---|---|
| real transactions ingested end-to-end, zero dropped | sustained on one node, audit-written per row | to process a full 100,000-transaction day |

**Strip:** 44,790 accounts from that run · case queries under 100 ms · cost flat as the ledger grows

**COMPUTE** — Stateless API, 3 replicas minimum, auto-scaling to 20 on live load, with zero-downtime rolling updates.
**DATABASE** — SQLite for a pilot, PostgreSQL for production, behind one storage interface. A config change, not a rewrite.
**DEPLOYMENT** — Your Kubernetes, your OpenShift, or plain Docker on a server in your own data centre. Air-gappable.

**Banner:** INSTALLATION: provision node › inject secrets from your vault › point at your
Postgres › load a historical CSV export › run detection › go live

**Say:**
> "Let's talk scale, because 'it works in a demo' is not a business case. We ingested five
> point zero eight million real transactions end to end — not sampled, not simulated — with
> zero rows dropped, and with a cryptographic audit record written for every single one.
> That's about six hundred and fifty transactions a second on one node. So a hundred thousand
> transactions a day — the number we were asked about — is roughly two and a half minutes of
> capacity. On one machine. Before we scale out. Growing is deliberately boring: the API is
> stateless and auto-scales; the database is SQLite for a pilot and PostgreSQL in production
> behind one interface, so it's a config change; and the whole thing runs on your Kubernetes
> or on a physical server in your own data centre. With a self-hosted model it can be fully
> air-gapped. And to install it, you need a CSV export. Not a core-banking integration."

---

## Slide 10 — PROOF · 0:30

**Title:** Measured, not claimed.

| **5,078,345** | **44,790** | **726** |
|---|---|---|
| real benchmark transactions processed, 0 skipped | suspicious accounts surfaced in one detection run | automated tests passing, at 97.7% coverage |

| **693,102** | **0.778** | **< 100 ms** |
|---|---|---|
| audit records, chain integrity verified | AUC-ROC at a 0.48% base rate — real signal, hard problem | case investigation query latency |

**Banner:** Every number here came from a run we can reproduce in front of you.

**Say:**
> "And every number here is measured, not modelled. Five million real transactions through
> the real pipeline. Forty-four thousand suspicious accounts from one run. Seven hundred and
> twenty-six automated tests. Six hundred and ninety-three thousand audit records with the
> chain verified end to end. We can reproduce every one of these in front of you."

---

## Slide 11 — BUSINESS MODEL · 0:35

**Title:** A three-week pilot, not a three-year procurement.

**WEEK 1 · PROVE** — Detection run on your own historical exports. CSV in, alerts out.
**WEEK 2 · CALIBRATE** — Your compliance team tunes thresholds on your typologies.
**WEEK 3 · RUN** — Two real investigators, real cases, an evaluation you own.
**THEN · DEPLOY** — Private cloud in your account, or on-premise. Data never leaves.

**COMMERCIAL MODEL**
• Pilot — 3 weeks, no core-banking integration
• Private-cloud licence — you keep data custody
• On-premise for hard data-residency mandates

**THE MARKET**
• 309 addressable Indian institutions
• ₹114.5 Cr serviceable annual revenue in India
• Global AML software: $3.2 bn → $9.1 bn by 2034

**Banner:** We complement your AML stack. We don't ask you to replace it.

**Say:**
> "And the commercial path is deliberately small at the start. Three weeks. Week one we run
> detection against your own historical exports — all we need is a CSV. Week two your
> compliance team calibrates it on your typologies, not ours. Week three, two real
> investigators work real cases and you write the evaluation. Then it deploys in your private
> cloud or on your own premises, and your data never leaves your custody. We're not asking
> anyone to rip out an existing AML system — we sit downstream of whatever you already run.
> That's a three-week decision, not a three-year procurement."

---

## Slide 12 — CLOSE · 0:15

> Detection finds the signal.
> Investigation finds the story.
> Feedback makes the system smarter.
>
> # TraceX
> Investigate better. Decide faster. Learn continuously.
>
> **THE ASK: a three-week pilot on Union Bank's own historical data.**

**Say:**
> "Detection finds the signal. Investigation finds the story. And feedback makes the whole
> system smarter every time someone uses it. TraceX turns a flood of alerts into a trail no
> launderer can hide from. Our ask is simple — three weeks, on your own historical data.
> Thank you."

*Then stop talking. Hold eye contact. Silence reads as confidence; trailing off does not.*

---

# APPENDIX SLIDES — do not present

| # | Slide | Pull it up when a judge asks... |
|---|---|---|
| A1 | Five layers. One audited database. | "walk me through how it's actually built" |
| A2 | Six typologies. Two models. One graph. | "what exactly does it detect, and how" |
| A3 | Every obligation, mapped to a control. | "show me the compliance mapping" |
| A4 | Economics, market — and what isn't finished. | "what are your margins / what's not done" |

**A3 carries the full regulatory table:** DPDP 2023 §7/§17, §8(5), §8(6), §8(7); PMLA 2002
§12; RBI KYC Master Direction; FATF Recs. 10 & 20 — each mapped to the control that
implements it, with the honest "prototype pending formal compliance sign-off" caveat printed
on the slide.

**A4 carries the gaps deliberately.** Volunteering what isn't finished buys more credibility
with this audience than defending it does.

---

# Q&A — the questions this deck will provoke

**"Your ML precision is only 25%. Is that good?"**
> "That's the honest number on a genuinely hard problem — under half a percent of accounts in
> the benchmark are actually positive. AUC-ROC of 0.778 is where the real signal shows up at
> that base rate. And it's precisely why ML is one signal in an ensemble with the typology
> rules and the graph structure — never the sole decision-maker."

**"Is this a signed pilot with Union Bank?"**
> "No, and I want to be precise about that — this is a hackathon track and an evaluation
> conversation, not a signed deployment."

**"What's genuinely not finished?"**
> "Three things, plainly. The automated retention-purge job and legal-hold flagging are
> designed and documented but not built — nothing auto-deletes today. The PostgreSQL and Neo4j
> production swaps exist as adapter boundaries in code; the implementations are the funded next
> step. And a regulated financial product needs an external security review and a formal
> compliance sign-off on our STR format before it touches a real account. We've done rigorous
> internal testing; we're not going to call that the same thing."

**"How do you stop a rogue insider exfiltrating data?"**
> "Three layers. Case-scoping means an investigator can only reach the neighbourhood of a case
> assigned to them — there's no 'query the whole ledger' surface. Role separation means an
> investigator physically cannot close a case, approve a report, or edit the watchlist. And the
> hash-chained audit log makes every access permanent and tamper-evident, so exfiltration
> leaves a record the exfiltrator can't erase."

**"What if we can't allow any external AI provider?"**
> "Then don't use one. The AI gateway talks to any OpenAI-compatible endpoint, so a model
> self-hosted inside your data centre is a configuration change, not a rewrite. That also takes
> your inference cost to zero and makes the deployment fully air-gappable."

**"Who owns the data?"**
> "You do, at every tier. Even in the SaaS tier we deploy inside your own cloud account. We're
> a processor; you remain the fiduciary."

**"What happens on a data breach under DPDP?"**
> "The Act requires notification to the Data Protection Board and to affected persons. The
> hash-chained audit log is what makes that answerable rather than speculative — you can state
> exactly which records were accessed, by whom, and when, with cryptographic evidence that the
> log itself wasn't edited afterwards."

**"How does this handle our volume as we grow?"**
> "Two axes. Horizontally, the API is stateless and auto-scales from three replicas to twenty
> on live load, with zero-downtime rolling updates. Vertically, the expensive part — graph
> queries — is scoped to one case's neighbourhood, so query cost is flat as your ledger grows.
> The database swap to PostgreSQL is a configuration change behind an interface that already
> exists in code."

---

# If you're running over — the cut order

1. **Cut slide 6 (the network slide) entirely** — the demo video already showed the graph.
   Saves 0:30. Take this cut first.
2. **Trim slide 10 (Proof) to the top three numbers** — "the rest is on the slide." Saves 0:15.
3. **Shorten slide 4** to naming the seven chevrons in one breath, skipping the three cards.
   Saves 0:15.
4. **Never cut slide 8 (Security/DPDP) or slide 9 (Scale).** Those two move a bank from
   interested to piloting. Everything else is negotiable; those are not.

# Delivery reminders

- **Don't read the slides.** This script says more than the slide text — use that gap.
- Eye contact with the panel, not the screen, except at the cued diagram points.
- Rehearse the transition *into* and *out of* the video specifically. That's where decks die.
- Print the deck to PDF as a backup and put it on the presenting laptop.
- The deck uses **Calibri**. If ₹ renders as a box on the venue machine, its Calibri is
  outdated — replace ₹ with "Rs." or present from the PDF instead.

---

# Where every number comes from

All figures trace to `docs/METRICS.md`; do not add one that isn't in that ledger.

| Figure | Source |
|---|---|
| 5,078,345 transactions ingested, 0 skipped; ~2h11m wall time (→ ~646/sec) | METRICS §18 |
| 44,790 alerts, 20 cases auto-created | METRICS §18 |
| 693,102 audit chain rows verified | METRICS §1 |
| 726 tests, 97.73% coverage | METRICS §28 |
| AUC-ROC 0.778 at 0.48% positive base rate | METRICS §18 |
| Case graph query 96 ms (128 nodes / 162 edges, radius 4) | METRICS §8 |
| 3 replicas → 20 via HPA, non-root, read-only FS, secrets via secretKeyRef | `deploy/k8s/api-deployment.yaml` |
| 5-year retention, PMLA §12 / RBI KYC | `docs/DATA_RETENTION.md` |
| 309 institutions, ₹114.5 Cr SAM, $606 M India RegTech, $3.2→9.1 bn global | `docs/QNA_STARTUP_VC.md` |
| $0.07–$0.10 per AI call, ~96% modelled gross margin | `docs/QNA_STARTUP_VC.md` |
| Clari5 → Perfios, Feb 2025 | `docs/QNA_STARTUP_VC.md` |

**DPDP note:** the DPDP Act mapping on slide 8 and appendix A3 is *new to this deck* — the
repo had no DPDP analysis before. It is built on the system's actual properties (processor
role, PII-free AI layer, HMAC tokenisation, server-side RBAC, hash-chained audit, the
5-year retention policy in `docs/DATA_RETENTION.md`). It is a defensible reading, **not a
lawyer's opinion** — A3 says so on the slide, and you should say it out loud if pressed.
