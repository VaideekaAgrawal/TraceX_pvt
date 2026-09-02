# TraceX — Presentation Prep Checklist

Everything else worth doing before you're on stage in front of Union Bank officials, beyond the deck and the speaker notes.

---

## ⚠️ Read this first: don't cite the old docs

`docs/pitch.md`, `docs/explanation.md`, `docs/pptcontent.md`, and `docs/cross_questions.md` already exist in this repo — and they describe a **different, older version of the system**: "TraceX v3.0," a 4-role RBAC model (Admin/Investigator/Analyst/Viewer — the current system has 2 roles), a different architecture (no case-scoped graph, no AI grounding gate), and ML metrics (Precision 0.778 / F1 0.683 / AUC-ROC 0.933) that were later found to have **never been reproduced** against this codebase at full scale — the real, current, honestly-measured numbers are Precision 0.254 / Recall 0.173 / F1 0.206 / AUC-ROC 0.778 (`docs/METRICS.md`). Those four files are pre-refactor hackathon-era artifacts; they were not updated when the system was rebuilt.

**Use only:** this checklist, `docs/PRESENTATION_SPEAKER_NOTES.md`, `docs/PROJECT_EXPLAINED_SIMPLY.md`, `docs/QNA_JUDGES.md`, `docs/QNA_STARTUP_VC.md`, and the live pitch deck artifact. If a teammate pulls up an old doc while prepping and starts memorizing "F1 0.683," that's the single easiest way to contradict yourself on stage if a judge cross-checks numbers between what you say and what's in the deck.

---

## Your deck depends on the internet — plan around that

The pitch deck is a hosted web page, not a local file. The event's own guidance says nothing critical should depend on internet connectivity. Two things to do before the day:

1. **Print it to PDF now, while you have a link.** Open the deck, `Cmd/Ctrl+P` → save as PDF. Each slide becomes one landscape page. Put that PDF on the presenting laptop, not just in the cloud.
2. **Keep a local copy of the actual HTML file too**, in case you need to reopen it without internet — you were sent one alongside this checklist. Opening it offline will fall back to system fonts instead of the exact typeface; that's cosmetic, not a problem.

If the room's projector setup is unfamiliar, test both the live link *and* the offline PDF on that exact machine before your slot — not the night before on a different laptop.

---

## Team roles (from the event's own instructions — fill these in)

- [ ] Primary Presenter: ______________________
- [ ] Backup Presenter: ______________________ (must be able to deliver the *whole* talk solo, not just their half)
- [ ] Technical / Demo Coordinator: ______________________
- [ ] PPT / AV Coordinator: ______________________ (owns the laptop, the link, and the PDF backup at the venue)

## Rehearsal plan

- [ ] **Content rehearsal** — both presenters read the script in `docs/PRESENTATION_SPEAKER_NOTES.md` out loud once, alone, to internalize it (not memorize word-for-word)
- [ ] **Timed rehearsal** — full run with a stopwatch, both presenters, both handoffs. If over 4:40, cut content (Slide 4 first — see the speaker notes), don't speed up
- [ ] **Final simulation** — present off the *actual* deck link on the *actual* presenting laptop, practice the handoff lines out loud, practice walking up and starting cold (no "let me just pull this up")
- [ ] Do this at least twice on separate days — once to find the rough edges, once to confirm they're fixed

## Know these numbers cold (rapid-fire proof, don't fumble them)

- 5,078,345 real transactions ingested, 0 skipped
- 726 backend tests passing, 97.7% coverage
- 44,790 alerts from one detection run
- AUC-ROC 0.778 (be ready to explain *why* precision/recall look lower in isolation — see `docs/QNA_JUDGES.md`)
- 2 roles: Investigator, Admin/Compliance — enforced server-side, not just in the UI
- ₹114.5 Cr serviceable Indian market, 309 institutions, bottom-up from RBI counts
- Clari5 → Perfios, Feb 2025 — the market precedent, know it well enough to say it without reading it

## Hard questions to say out loud before the day, not for the first time on stage

Practice saying these two sentences until they don't feel awkward — they'll come up, and hesitating on them reads worse than the honest answer itself:

- *"Is this a signed pilot with Union Bank?"* → "No — this is a competition track and an evaluation conversation, not a signed deployment."
- *"Your ML precision is only 25% — is that good?"* → "That's the honest number on a genuinely hard, extremely imbalanced problem — it's one signal in an ensemble, not the sole decision-maker, and AUC-ROC of 0.778 is where the real signal shows up."

Don't let either of these be the first time you've said them out loud to another person.

## Demo backup

- [ ] If you're planning to click through the live deck during the actual talk (not just present the PDF), have a recorded screen-capture video of a full click-through as a silent fallback
- [ ] Test the recorded video plays without internet on the presenting laptop
- [ ] Decide in advance: if the live version fails mid-talk, who says the recovery line ("we'll continue with the backup") and keeps going — don't let a broken link cost you 30 seconds of dead air deciding

## Day-of logistics (from the event brief)

- [ ] Formal/official dress, all team members
- [ ] College ID cards worn visibly, entire event — not just during your slot
- [ ] Arrive well before the 3:50–4:20 PM team-presentation window; be ready for a quick transition from the team before you
- [ ] Final PPT + PDF backup + offline video with the PPT/AV Coordinator, confirmed on the venue laptop if possible, not assumed
- [ ] Everyone in the room before your slot — no one arriving mid-changeover

## Delivery reminders

- Formal, confident tone — this is in front of dignitaries, not a peer demo
- No reading directly from slides — the speaker notes exist so you have more to say than what's on screen
- Eye contact with the panel, steady pace, don't rush to beat the clock — cut content instead (see speaker notes)
- If a judge interrupts with a question mid-flow, answer it briefly and bridge back ("good question — and that connects to...") rather than derailing your remaining time
