# TraceX — Speaker Notes (5-Minute, 2-Presenter Version)

Companion to the pitch deck (`docs/pptcontent.md` is the *old* pre-refactor hackathon deck — **do not use it**, see the note in `docs/PRESENTATION_PREP_CHECKLIST.md`). This document is for the current **6-slide timed deck** — compliant with the event's "recommended maximum 6 slides" guideline: Problem → Solution → Architecture → Features & Trust → Results → Impact.

**The deck file has 8 slides total, not 6.** Slides 7–8 ("Appendix A1 — Pipeline" and "Appendix A2 — Low-Level Design") are backup material for technical Q&A — a full working-pipeline diagram and a data-model/request-lifecycle diagram — not part of the timed 5-minute run. **Do not present them on stage** unless a judge specifically asks a question deep enough to warrant pulling one up (e.g. "walk me through what happens end to end" → Appendix A1; "what does your data model actually look like" → Appendix A2). Know they exist and roughly what's on them; don't rehearse a script for them.

**Target: finish speaking by 4:14, hard ceiling 5:00.** The architecture slide is dense on purpose — that density is doing work even when you're not narrating every line out loud. Don't try to read the diagram; walk down the five layers top to bottom in one breath, and let the audience *see* the depth. That's what lets a technically rich slide still fit inside 5 minutes.

This is a **script to internalize, not read verbatim** — say it in your own words once you know the beats.

---

## Roles for this version

- **Presenter 1** — opens, does Slides 1–2, closes on Slide 6.
- **Presenter 2** — does Slides 3–5, the technical middle (architecture, features & trust, results).
- Whoever is *not* talking drives the deck (arrow keys / dot-nav at the bottom of the artifact).

Fill in real names before you rehearse.

---

## Timing table

| # | Slide | Presenter | Target | Cumulative |
|---|-------|-----------|--------|------------|
| — | Intro | 1 | 0:10 | 0:10 |
| 1 | The Problem | 1 | 0:40 | 0:50 |
| 2 | The Solution | 1 | 0:38 | 1:28 |
| — | Handoff | — | 0:03 | 1:31 |
| 3 | Architecture | 2 | 0:55 | 2:26 |
| 4 | Features & Trust | 2 | 0:35 | 3:01 |
| 5 | Results | 2 | 0:35 | 3:36 |
| — | Handoff | — | 0:03 | 3:39 |
| 6 | Impact + Close | 1 | 0:48 | 4:27 |

That lands at 4:27 — right in the event's 4:30–4:40 target band. There's almost no slack left, so this version needs an actual timed rehearsal, not a guess — if you're consistently over, cut per the "running over" section below rather than trimming on the fly.

---

## The script

### Intro — Presenter 1
> "Good afternoon. We're Team syntax_error, and this is TraceX — an AI investigation platform for anti-money-laundering, built for Union Bank of India."

*Cue: say this while Slide 1 is already up.*

### Slide 1 — The Problem — Presenter 1
> "Static rules can't see the graph, and investigators can't clear what's left. Banks are legally required under PMLA 2002 to both detect and report suspicious activity — RBI issued fifty-four crore rupees in penalties last year alone. A single detection run of ours on real transaction data found almost forty-five thousand suspicious accounts. Industry-wide, ninety to ninety-five percent of AML alerts turn out to be false positives — and sophisticated launderers know it, structuring transactions just below the ten-lakh threshold specifically because a row-by-row rule engine can't see the pattern across accounts."

*Cue: gesture at the two boxes — Detection Gap, Investigation Gap — converging on "Undetected. Unresolved. Unreported." Say "a detection run of ours" clearly — this is TraceX's own output, not alerts fed in from somewhere else. If tight on time, cut the RBI-penalty clause — the chip row above the diagram carries that stat visually.*

### Slide 2 — The Solution — Presenter 1
> "TraceX both detects and investigates. On detection: six typology detectors — layering, round-trip, structuring, dormancy, profile mismatch, mule networks — plus a dual ML ensemble, reasoning over the live transaction graph. On investigation: a fifteen-to-thirty-minute triage, escalating to full deep-dive exploration when needed. Every AI explanation is cited against a computed fact and validated before display — never invented — with a learning queue that adapts from every verdict. A pilot needs nothing more than a CSV export."

*Cue: sweep across the three pillar cards. The small proof line under each card is your evidence if a judge interrupts here.*

**Handoff (Presenter 1 → 2):** "I'll hand it over to [Name] to walk through how it's actually built."

### Slide 3 — Architecture — Presenter 2
> "This is a layered design, five tiers top to bottom. A request comes in through our gateway, where authentication and access control are enforced on every one of thirteen route modules — not most, every one. That calls into three peer services: Detection, with six typology detectors and our ML ensemble; Investigation, running the case lifecycle end to end; and AI Orchestration. All three sit on one shared platform and one audited database. The one thing to remember: our AI layer never invents a number — every claim has to cite a fact our own code computed, or it's dropped before an investigator sees it. And it's the only layer that ever leaves our Kubernetes deployment boundary — through a gate we've watched reject bad output live."

*Cue: trace your hand straight down the stack, layer by layer, as you speak — you don't need to read a single line inside any band out loud. The clean layout is what makes that legible from the back of the room.*

### Slide 4 — Features & Trust — Presenter 2
> "On top of that: a case-scoped graph explorer, one explained network risk score, AI-grounded recommendations anchored to FATF and RBI guidance, a cross-case copilot that never lets personal data reach the model, and one-click STR generation. And this is built to survive scrutiny, not just work in a demo — role-based access enforced server-side, a SHA-256 audit chain, and we went looking for race conditions instead of hoping there weren't any."

*Cue: brisk delivery across the first five tiles, then land slightly slower on the sixth ("Security & Audit") — that's your credibility tile, let it breathe for half a second.*

### Slide 5 — Results — Presenter 2
> "This isn't a mockup. Over five million real transactions ingested, zero skipped. Seven hundred twenty-six tests passing at ninety-seven-point-seven percent coverage. Our model scores point-seven-seven-eight AUC-ROC — real signal on a genuinely hard, imbalanced problem. And we watched the guardrails work live, not just in a test file."

*Cue: if a judge later asks "why is your precision only 25%," you already told them the honest framing here first. See `docs/QNA_JUDGES.md`.*

**Handoff (Presenter 2 → 1):** "Back to [Name] to close."

### Slide 6 — Impact + Close — Presenter 1
> "TraceX maps directly onto PMLA, FIU-IND's STR format, RBI's AML and KYC directions, and FATF's recommendations. Built bottom-up from published RBI institution counts, the serviceable Indian market alone is worth about one hundred fourteen crore rupees a year. It deploys as private-cloud SaaS inside a bank's own cloud account — their data never leaves custody — and because FATF's framework is global, this exports, the same path Clari5 took to fifteen-plus countries before being acquired by Perfios earlier this year. TraceX turns a flood of alerts into a trail no launderer can hide from — built end-to-end, tested at scale, and ready to pilot. Thank you."

*Cue: land on "thank you," stop talking, hold eye contact. If tight on time, drop the "private-cloud SaaS" clause — it's still on the slide for anyone reading afterward.*

---

## If you're running over: the cut order

1. **Trim Slide 4 (Features & Trust) to three tiles** — say "the rest is on the slide" and move on. Saves ~10 seconds.
2. **Shorten the architecture walk-through** — name only Gateway, the three services, and the PII gate; skip the platform/database layers verbally (they're still visible on the slide). Saves ~15 seconds.
3. Do **not** cut Slide 5 (Results) — it's your strongest evidence slide for a technical audience, and it's already the shortest.

## Delivery reminders (from the event's own guidelines)

- Don't read the slides — the script says more than the slide text; use that gap.
- Eye contact with the panel, not the screen, except the cued diagram-points above.
- Rehearse both handoffs specifically.
- Silence after "thank you" reads more confident than trailing off.
