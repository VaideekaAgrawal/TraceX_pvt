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
| 1 | The Problem | 1 | 0:38 | 0:48 |
| 2 | The Solution | 1 | 0:36 | 1:24 |
| — | Handoff | — | 0:03 | 1:27 |
| 3 | Architecture | 2 | 0:52 | 2:19 |
| 4 | Features & Trust | 2 | 0:33 | 2:52 |
| 5 | Results | 2 | 0:47 | 3:39 |
| — | Handoff | — | 0:03 | 3:42 |
| 6 | Impact + Close | 1 | 0:46 | 4:28 |

This version has essentially zero slack (4:28, right at the event's upper bound) — treat the per-slide targets above as firm, not approximate, and rehearse against a stopwatch before assuming it fits. If you're consistently over in rehearsal, use the cut order below rather than speeding up.

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
> "Four things prove this actually solves the problem. False positives: an account is only flagged when pattern, graph, and ML signals converge — not one model's opinion — which is why we hit fifty-six percent more predictive than random on the full public benchmark. Time: L1 triage is built around a fifteen-to-thirty-minute decision, with everything pre-assembled on one screen. Coverage: this runs its own six-detector, dual-ML detection engine end to end — it doesn't need an existing AML system to work. And it learns: every investigator verdict updates rule confidence and re-ranks the queue, so it gets sharper with use, not just its explanations."

*Cue: the small chip strip above these four rows (transaction count, test coverage, AUC-ROC, "verified live") is your fallback if you need to cite a raw number fast in Q&A — you don't need to read it aloud here, it's there for the room to see. "Fifty-six percent more predictive than random" is still the number to land clearest. If a judge later asks "why is your precision only 25%," you already told them the honest framing here first. See `docs/QNA_JUDGES.md`.*

**Handoff (Presenter 2 → 1):** "Back to [Name] to close."

### Slide 6 — Impact + Close — Presenter 1
> "Four things to take away. Faster investigation — pre-assembled facts and one-click reporting replace hours of manual evidence work. Deeper detection — six typology detectors plus dual ML catch what row-by-row rules miss. Reduced compliance exposure — this is exactly the gap behind RBI's fifty-four crore rupees in FY25 penalties. And a proven commercial path — a real market, a three-week pilot, and an export precedent Clari5 already proved before its Perfios acquisition. TraceX turns a flood of alerts into a trail no launderer can hide from — built end-to-end, tested at scale, and ready to pilot. Thank you."

*Cue: land on "thank you," stop talking, hold eye contact. If tight on time, drop the "private-cloud SaaS" clause — it's still on the slide for anyone reading afterward.*

---

## If you're running over: the cut order

1. **Trim Slide 4 (Features & Trust) to three tiles** — say "the rest is on the slide" and move on. Saves ~10 seconds.
2. **Shorten the architecture walk-through** — name only Gateway, the three services, and the PII gate; skip the platform/database layers verbally (they're still visible on the slide). Saves ~15 seconds.
3. Do **not** cut Slide 5 (Results) — the four rows are your direct answer to "how did this actually solve the problem," which is the hardest question in the room to leave unaddressed.

## Delivery reminders (from the event's own guidelines)

- Don't read the slides — the script says more than the slide text; use that gap.
- Eye contact with the panel, not the screen, except the cued diagram-points above.
- Rehearse both handoffs specifically.
- Silence after "thank you" reads more confident than trailing off.
