# TraceX Demo V2 (Investor Cut) — Rendered Cue Sheet

Voice **`en-IN-NeerjaExpressiveNeural`**, baseline rate **+16%**, segment gap **0.22s**.
**Total 3:59 (239s).** Every block is padded to exactly its slot, so each starts at
the timecode below — drop them on a timeline at fixed positions and cues cannot drift.

Segments are silence-trimmed at both ends before assembly, so the only gap between
phrases is the one written here — no dead air from the TTS onset/tail.

Audio: `data/voiceover-v2/`. V1's 3:07 take in `data/voiceover/` is untouched.

Regenerate:

```bash
EDGE_TTS_BIN=$PWD/.venv-tts/bin/edge-tts python3 scripts/make_voiceover.py \
  --cut v2 --edge-rate 16 --seg-gap 0.22 \
  --voice en-IN-NeerjaExpressiveNeural --out-dir $PWD/data/voiceover-v2
```

---

### `[0:00 – 0:20]` — 01-cold-open  (20s)

**Screen:** Alert queue, full list, risk/confidence badges. Cursor idle, then the top row

> Every morning, this ledger throws up thousands of transactions. This queue is what's left.
> Not sorted by time — sorted by risk. Then reshuffled by a system that has watched every case my team has closed.
>  *(0.47s pause)*
> False alarms sink. Confirmed frauds rise. And this one was right at the top.

---

### `[0:20 – 0:49]` — 02-three-systems  (29s)

**Screen:** Click top alert; case opens; Alert Summary + confidence badge, then the network-risk panel beside it

> A round-trip alert. Risk score: eighty-seven. Confidence... very strong.
>  *(0.61s pause)*
> And that isn't one model's opinion. A machine-learning model, a rules engine, a network analysis engine — all three agreed.
>  *(0.54s pause)*
> And a second score asks a different question: not is this account suspicious, but is it inside a suspicious web?
>  *(0.47s pause)*
> One sanctioned entity. A closed cycle. Two accounts everything routes through.

---

### `[0:49 – 1:19]` — 03-the-contrast  (30s)

**Screen:** Customer Snapshot -- Continental Logistics, then scroll to Suresh Bansal. PROTECTED BEAT -- the emotional core

> Two accounts.
>  *(0.68s pause)*
> The first is Continental Logistics — a corporate customer, four crore declared income, KYC verified, medium risk. Nothing about this account asks for my attention.
>  *(2.10s pause)*
> But the second one... does.
>  *(1.95s pause)*
> Suresh Bansal. Retired. Declared income — one lakh, fifty thousand rupees. His KYC was rejected... and he is on a sanctions list.

---

### `[1:19 – 1:30]` — 04-pattern-explanation  (11s)

**Screen:** Pattern-explanation panel -- the 'why was this flagged' text

> Before I open a single transaction, the system has already written why it flagged this — in plain words, not a score.
>  *(0.54s pause)*
> I didn't need to be a data scientist to trust that.

---

### `[1:30 – 1:44]` — 05-similar-cases  (14s)

**Screen:** Triage panel -> Similar Historical Cases card, top-3 expanded

> And I'm not looking at this cold. It pulls up the closest cases we've already closed.
>  *(0.47s pause)*
> Four of them were filed as confirmed reports. One was kept under monitoring.
>  *(0.61s pause)*
> Not one of them was dismissed.

---

### `[1:44 – 2:15]` — 06-the-money  (31s)

**Screen:** Money Flow -- the 2025 seed payment, then the 21 June cluster, then the AI account explanation beside it. PROTECTED BEAT

> So here's what actually passed between them. Last June, Suresh sent the company fifty thousand rupees. One payment.
>  *(0.47s pause)*
> Then nothing... for a year.
>  *(2.05s pause)*
> And then, on the twenty-first of June — in fifteen hours — the company sent it back. Six transfers, five lakh each.
>  *(0.68s pause)*
> Thirty lakh rupees.
>  *(1.76s pause)*
> Sixty times what went out... into the account of a retired man who declares one and a half lakh a year.

---

### `[2:15 – 2:34]` — 07-how-it-moved  (19s)

**Screen:** Transaction rows, channel column; then the branch-cash transfers

> How did it move? N E F T... I M P S... U P I... R T G S.
>  *(0.61s pause)*
> Rotated every three hours — no single rail sees everything.
>  *(0.54s pause)*
> And five cash transfers, each just under the ten lakh threshold.

---

### `[2:34 – 2:47]` — 08-graph-explanation  (13s)

**Screen:** Toggle to Deep view; Investigation Graph, the cycle visible, replay running

> The graph makes it visual. Money out, money back — through a sanctioned counterparty.
>  *(0.61s pause)*
> And I can replay the whole fifteen hours, in order. This is the timeline a regulator will ask for.

---

### `[2:47 – 3:16]` — 09-ai-copilot  (29s)

**Screen:** AI widget -> Recommendations (PRE-GENERATED). Two accepted, open the rejected toggle, then the challenge box. PROTECTED BEAT

> This is where it stops being a dashboard.
>  *(0.54s pause)*
> It tells me what to do next — and which rule says so. F A T F Recommendation ten. The P M L A.
>  *(0.61s pause)*
> And two more it threw away itself — the numbers didn't check out.
>  *(0.81s pause)*
> And I can argue with it. Why isn't this an ordinary business refund?
>  *(0.74s pause)*
> It answers from this case's facts... or not at all. An AI that proves what it says, or says nothing.

---

### `[3:16 – 3:28]` — 10-escalate  (12s)

**Screen:** Decision panel -> Escalate to Compliance, reason typed, submit

> I've seen enough. I escalate.
>  *(0.68s pause)*
> And here's what a bank asks about first: I cannot close this case. I investigate — someone else decides.

---

### `[3:28 – 3:42]` — 11-compliance-str  (14s)

**Screen:** Compliance window; close as true positive; STR generate, finalize, submit

> Compliance confirms it — and only now does the report unlock.
>  *(0.54s pause)*
> F I U India format, written from the case. Every claim cited to a number the system computed.
>  *(0.61s pause)*
> Not one the model invented.

---

### `[3:42 – 3:59]` — 12-close  (17s)

**Screen:** MONTAGE -- the filed report. Hold still, no cursor movement

> Alert... to filed report. What took half a day across four systems took a fraction of that.
>  *(0.61s pause)*
> Fewer false alarms. Faster investigations. And a report that holds up when someone asks how we knew.
>  *(0.94s pause)*
> Every rupee leaves a trail.

---

**Total: 3:59 (239s)**
