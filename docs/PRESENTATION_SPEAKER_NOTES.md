# TraceX — Speaker Notes (5-Minute, 2-Presenter Version)

Companion to the pitch deck (`docs/pptcontent.md` is the *old* pre-refactor hackathon deck — **do not use it**, see the note in `docs/PRESENTATION_PREP_CHECKLIST.md`). This document is for the current **7-slide** deck: Problem → Solution → Architecture → Security & Trust → Features → Results → Impact.

**Target: finish speaking by 4:37, hard ceiling 5:00.** The architecture slide is deliberately dense — that density is doing work even when you're not narrating every box out loud. Don't try to read the diagram; say 2–3 sentences while pointing at the numbered path, and let the audience *see* the depth. That's what resolves the tension between "comprehensive" and "5 minutes": the diagram carries more information than you speak.

This is a **script to internalize, not read verbatim** — say it in your own words once you know the beats.

---

## Roles for this version

- **Presenter 1** — opens, does Slides 1–2, closes on Slide 7.
- **Presenter 2** — does Slides 3–6, the technical middle (architecture, security, features, results).
- Whoever is *not* talking drives the deck (arrow keys / dot-nav at the bottom of the artifact).

Fill in real names before you rehearse.

---

## Timing table

| # | Slide | Presenter | Target | Cumulative |
|---|-------|-----------|--------|------------|
| — | Intro | 1 | 0:10 | 0:10 |
| 1 | The Problem | 1 | 0:33 | 0:43 |
| 2 | The Solution | 1 | 0:38 | 1:21 |
| — | Handoff | — | 0:03 | 1:24 |
| 3 | Architecture | 2 | 0:55 | 2:19 |
| 4 | Security & Trust | 2 | 0:32 | 2:51 |
| 5 | Key Features | 2 | 0:28 | 3:19 |
| 6 | Results | 2 | 0:32 | 3:51 |
| — | Handoff | — | 0:03 | 3:54 |
| 7 | Impact + Close | 1 | 0:40 | 4:34 |

That lands at 4:34 — inside the event's own 4:30–4:40 guidance, with real margin against the 5:00 hard cap. If you're running long in rehearsal, cut Slide 5 first (see the cut-line at the bottom).

---

## The script

### Intro — Presenter 1
> "Good afternoon. We're Team syntax_error, and this is TraceX — an AI investigation platform for anti-money-laundering, built for Union Bank of India."

*Cue: say this while Slide 1 is already up.*

### Slide 1 — The Problem — Presenter 1
> "Banks don't have an alert problem — they have a resolution problem. A single detection run on real transaction data produced almost forty-five thousand alerts. Industry-wide, ninety to ninety-five percent of AML alerts turn out to be false positives, so real laundering cases hide inside that noise — and sophisticated launderers know it, structuring transactions just below the ten-lakh reporting threshold to stay invisible."

*Cue: gesture at the diagram's three boxes converging on "Risk Goes Undetected."*

### Slide 2 — The Solution — Presenter 1
> "TraceX sits downstream of a bank's existing rules engine — it doesn't replace it, it finishes the job. Three pillars: graph intelligence that traces multi-hop fund flows a flat ledger can't show; dual machine learning, ensemble-scored together; and an AI layer that explains every flagged account in plain language and learns from every investigator decision. A pilot needs nothing more than a CSV export."

*Cue: sweep across the three pillar cards. Note the small proof line under each card — that's your evidence if a judge interrupts here.*

**Handoff (Presenter 1 → 2):** "I'll hand it over to [Name] to walk through how it's actually built."

### Slide 3 — Architecture — Presenter 2
> "Under the hood, this is three domain layers over one shared platform — follow the numbers. A request comes in through our gateway, where authentication and access control are enforced on every one of thirteen route modules — not most, every one. It fans out to Detection — six typology detectors plus our ML ensemble — Investigation, and AI Orchestration, all backed by one audited database. The one thing to remember: our AI layer never invents a number — every claim has to cite a fact our own code computed, or it's dropped before an investigator sees it. And only that AI layer ever leaves the deployment boundary — through a gate we've watched reject bad output live."

*Cue: this is your one "serious engineering" beat. Point at badges ①→⑥ in sequence as you go — you don't need to read a single chip in the diagram out loud, the density is doing the convincing.*

### Slide 4 — Security & Trust — Presenter 2
> "And this isn't just built to work — it's built to survive scrutiny. Two roles enforced server-side, not just hidden in the UI — we tested a direct API bypass and got back a real permission error. Every AI claim is validated before display, not just prompted to be accurate. And we didn't hope there were no race conditions — we went looking: two simultaneous requests to create the same case both come back successful, and exactly one case row exists in the database."

*Cue: pick 2–3 of the six tiles to say out loud (RBAC, grounding, concurrency are the strongest); the other three are there for anyone reading the deck afterward, or for Q&A.*

### Slide 5 — Key Features — Presenter 2
> "On top of that: a case-scoped graph explorer, one explained network risk score, AI-grounded explanations, a thirteen-action recommendation engine anchored to FATF and RBI guidance, a cross-case copilot that never lets personal data reach the model, and one-click STR generation — narrative to a SHA-256-hashed PDF."

*Cue: fast slide, brisk delivery — this is a "we thought of everything" beat.*

### Slide 6 — Results — Presenter 2
> "This isn't a mockup. Over five million real transactions ingested, zero skipped. Seven hundred twenty-six tests passing at ninety-seven-point-seven percent coverage. Our model scores point-seven-seven-eight AUC-ROC — real signal on a genuinely hard, imbalanced problem. And we watched the guardrails work live, not just in a test file."

*Cue: if a judge later asks "why is your precision only 25%," you already told them the honest framing here first. See `docs/QNA_JUDGES.md`.*

**Handoff (Presenter 2 → 1):** "Back to [Name] to close."

### Slide 7 — Impact + Close — Presenter 1
> "TraceX maps directly onto PMLA, FIU-IND's STR format, RBI's AML and KYC directions, and FATF's recommendations. Built bottom-up from published RBI institution counts, the serviceable Indian market alone is worth about one hundred fourteen crore rupees a year — and because FATF's framework is global, this exports, the same path Clari5 took to fifteen-plus countries before being acquired by Perfios earlier this year. TraceX turns a flood of alerts into a trail no launderer can hide from — built end-to-end, tested at scale, and ready to pilot. Thank you."

*Cue: land on "thank you," stop talking, hold eye contact.*

---

## If you're running over: the cut order

1. **Cut Slide 5 (Features) first** — say "we've built a full feature set here, happy to walk through it in Q&A" and advance past it. Saves ~30 seconds cleanly.
2. **Trim Slide 4 (Security) to one sentence** — RBAC + grounding gate only, drop the concurrency line. Saves ~15 seconds.
3. Do **not** cut Slide 3 (Architecture) or Slide 6 (Results) — those are your two strongest evidence slides for a technical audience.

## Delivery reminders (from the event's own guidelines)

- Don't read the slides — the script says more than the slide text; use that gap.
- Eye contact with the panel, not the screen, except the cued diagram-points above.
- Rehearse both handoffs specifically.
- Silence after "thank you" reads more confident than trailing off.
