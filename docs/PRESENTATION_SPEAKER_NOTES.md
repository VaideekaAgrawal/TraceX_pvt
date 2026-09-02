# TraceX — Speaker Notes (5-Minute, 2-Presenter Version)

Companion to the pitch deck (`docs/pptcontent.md` is the *old* pre-refactor hackathon deck — **do not use it**, see the note in `docs/PRESENTATION_PREP_CHECKLIST.md`). This document is for the current 6-slide deck: Problem → Solution → Architecture → Features → Results → Impact.

**Target: finish speaking by 4:35, hard ceiling 5:00.** Script below is ~625 words, which runs ~4:15 at a calm 145 wpm — that leaves real buffer for stage nerves, a slower pace, and the two handoffs. Rehearse with a stopwatch; if you're over, cut words, don't speed up (per the event's own instructions).

This is a **script to internalize, not read verbatim** — say it in your own words once you know the beats. Bullet cues are there for exactly that: knowing the beat, not the sentence.

---

## Roles for this version

- **Presenter 1** — opens, does Slides 1–2, closes on Slide 6. (Same person opens and closes — makes the talk feel bookended, not like two separate pitches stapled together.)
- **Presenter 2** — does Slides 3–5, the technical middle.
- Whoever is *not* talking drives the deck (arrow keys / dot-nav at the bottom of the artifact) so the speaker never has to break eye contact with the room to click.

Fill in real names before you rehearse — don't present from a doc that still says "Presenter 1."

---

## Timing table

| # | Slide | Presenter | Target | Cumulative |
|---|-------|-----------|--------|------------|
| — | Intro | 1 | 0:10 | 0:10 |
| 1 | The Problem | 1 | 0:35 | 0:45 |
| 2 | The Solution | 1 | 0:40 | 1:25 |
| — | Handoff | — | 0:03 | 1:28 |
| 3 | Architecture | 2 | 0:55 | 2:23 |
| 4 | Key Features | 2 | 0:35 | 2:58 |
| 5 | Results | 2 | 0:40 | 3:38 |
| — | Handoff | — | 0:03 | 3:41 |
| 6 | Impact + Close | 1 | 0:40 | 4:21 |

That leaves ~15–40 seconds of slack against the 4:30–4:40 guidance before you're anywhere near 5:00. Use it for a breath, not extra content.

---

## The script

### Intro — Presenter 1
> "Good afternoon. We're Team syntax_error, and this is TraceX — an AI investigation platform for anti-money-laundering, built for Union Bank of India."

*Cue: say this while Slide 1 is already up. Don't wait for it.*

### Slide 1 — The Problem — Presenter 1
> "Banks don't have an alert problem — they have a resolution problem. A single detection run on real transaction data produced almost forty-five thousand alerts. Industry-wide, ninety to ninety-five percent of AML alerts turn out to be false positives, so real laundering cases hide inside that noise. And sophisticated launderers know the rules — they structure transactions just below the ten-lakh reporting threshold specifically to stay invisible to static, rule-based systems."

*Cue: gesture at the diagram's three boxes converging on "Risk Goes Undetected" as you say the second sentence. Don't read the stat chips — you've just said the numbers.*

### Slide 2 — The Solution — Presenter 1
> "TraceX sits downstream of a bank's existing rules engine — it doesn't replace it, it finishes the job. It's built on three pillars: graph intelligence that traces multi-hop fund flows a flat ledger can't show; dual machine learning — an Isolation Forest that works from day one with no labels, plus XGBoost, ensemble-scored together; and an AI layer that explains every flagged account in plain language, with a reinforcement-learning queue that gets smarter with every investigator decision. A pilot needs nothing more than a CSV export — three weeks, no core-banking integration required."

*Cue: one hand sweep across the three pillar cards as you name them. "Nothing more than a CSV export" is the line to land — it's your objection-handler for "how disruptive is this to deploy."*

**Handoff (Presenter 1 → 2):** "I'll hand it over to [Name] to walk through how it's actually built."

### Slide 3 — Architecture — Presenter 2
> "Under the hood, TraceX is three domain layers over one shared platform. A request comes in through our Next.js frontend, hits a FastAPI gateway where authentication and role-based access are enforced on every single route — not most routes, every route. From there it fans out to Detection, Investigation, and AI Orchestration, all backed by one audited database. The one thing we want you to remember: our AI layer never invents a number. Every claim the model makes has to cite a fact our own code computed — a validator checks that citation, and if it doesn't resolve, the claim is dropped before an investigator ever sees it. That's enforced in code, not just asked for in a prompt — and we've watched it actually reject bad output live."

*Cue: this is your one "wow, that's real engineering" beat — slow down slightly on "enforced in code, not just asked for in a prompt." Point at the External LLM box and the gate arrow as you say it.*

### Slide 4 — Key Features — Presenter 2
> "On top of that architecture, an investigator gets a case-scoped graph explorer for multi-hop chains and cycles, a single network risk score that packages centrality and mule-adjacency into one explained number, AI-grounded explanations, a recommendation engine with thirteen actions anchored to FATF and RBI guidance, a cross-case copilot that never lets personal data reach the model, and one-click STR generation — narrative to JSON to a SHA-256 hash to a filed PDF."

*Cue: fast slide, don't stop on any one tile — this is a "we thought of everything" beat, delivered briskly.*

### Slide 5 — Results — Presenter 2
> "This isn't a mockup. We ingested over five million real transactions with zero skipped. We have seven hundred twenty-six backend tests passing at ninety-seven-point-seven percent coverage, behind an enforced CI gate. Our detection model scores point-seven-seven-eight AUC-ROC — real discriminative signal on a genuinely hard problem, where under half a percent of accounts are actually positive. And we didn't just unit-test the AI guardrails — we watched them work live: the grounding gate rejected a real ungrounded claim from the model, and a direct attempt to bypass role permissions came back with a real four-oh-three."

*Cue: if a judge later asks "why is your precision only 25%," this slide is where you already told them the honest number — don't get defensive, you said it first. See `docs/QNA_JUDGES.md` Q on this.*

**Handoff (Presenter 2 → 1):** "Back to [Name] to close."

### Slide 6 — Impact + Close — Presenter 1
> "TraceX maps directly onto PMLA, FIU-IND's STR format, RBI's AML and KYC directions, and FATF's recommendations. Built bottom-up from published RBI institution counts, the serviceable Indian market alone is worth about one hundred fourteen crore rupees a year — and because FATF's framework is global, this exports, the same path Clari5 took to fifteen-plus countries before being acquired by Perfios earlier this year. TraceX turns a flood of alerts into a trail no launderer can hide from — built end-to-end, tested at scale, and ready to pilot. Thank you."

*Cue: land on "thank you," stop talking, hold eye contact — don't trail into "so yeah that's basically it." Silence after the last line is more confident than a filler sentence.*

---

## Delivery reminders (from the event's own guidelines)

- Don't read the slides — you now have a script that says more than the slide text; use that gap.
- Maintain eye contact with the panel, not the screen, except for the two cued diagram-points above.
- Rehearse the handoffs specifically — a clean "I'll hand it to [Name]" lands better than an awkward pause.
- If you're cut off or the clock runs short: cut Slide 4 (Features) first — it's the least load-bearing slide for a judge decision, and the fastest to skip cleanly by saying "we've built out a full feature set here, happy to walk through it in Q&A" while advancing past it.
