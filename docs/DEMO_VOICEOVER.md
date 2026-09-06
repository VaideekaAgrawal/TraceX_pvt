# TraceX — 3-Minute Demo Voiceover

Narration script for the recorded demo video. Written in **first person as the
investigator** — the case lands on their desk this morning and they work it to a
filed report.

The audio is recorded **first**; the screen recording is then cut to match it.
So these timecodes are the contract: each block names the seconds it occupies and
the screen action it must sit over.

**Hero case:** `CASE-20260718-13F5F994` — reset with
`backend/scripts/prep_demo_live.py` before recording (see `docs/DEMO_SCRIPT.md` §0).

**Total: 3:00.** 387 words at ~149 wpm, with 24s of deliberate pause built in.

---

## Delivery direction (read this before recording)

The voice is a **working investigator**, not a narrator and not a salesperson.
Calm, unhurried, faintly dry. The facts are alarming — the delivery should not
be. Underplaying it is what makes it land.

Three rules:

1. **Numbers get room.** Every rupee figure lands on its own, with a beat after
   it. Never rush a number to make time; cut a word elsewhere.
2. **The turn at 0:24.5 is the whole script.** "Nothing about this account asks for
   my attention" → *pause* → "The second one does." That pause is the demo.
3. **No upward inflection at line ends.** Statements, not questions. An investigator
   reporting what they found, not pitching it.

`(...)` marks a **pause**. **Bold** marks the stressed word. `—` is a short breath.

---

## The script

### `[0:00 – 0:10.5]` — Cold open
**Screen:** Dashboard. Alert queue visible. Cursor idle, then moving to the top row.

> This morning, the detection engine finished its run across the bank's ledger.
> (...)
> This is what was waiting at the top of my queue.

*Delivery: flat, procedural. This is a person sitting down at their desk. Do not sell it.*

---

### `[0:10.5 – 0:24.5]` — The alert
**Screen:** Click the top alert → the case opens in the workspace. Alert Summary panel.

> A round-trip alert. Risk score: **eighty-seven**. (...) Confidence — **very strong**.
> (...)
> It isn't just telling me something looks wrong. It's telling me what **shape** of
> wrong, and how certain it is.

*Delivery: "very strong" is read as if quoting the screen — because you are.*

---

### `[0:24.5 – 0:55]` — The contrast **(the centre of the demo — do not rush)**
**Screen:** Customer Snapshot. Continental Logistics first. Then scroll to the counterparty, Suresh Bansal.

> Two accounts.
> (...)
> The first is Continental Logistics. A corporate customer. Four crore declared
> income. KYC verified. Medium risk. (...) Nothing about this account asks for my
> attention.
> (...)
> **The second one does.**
> (...)
> Suresh Bansal. **Retired.** Declared income — one lakh fifty thousand rupees.
> (...) His KYC was **rejected**. (...) And he is on a **sanctions list**.

*Delivery: the pause before "The second one does" is the longest in the script — a full beat. Then slow down and let the three facts land separately. Do not run them together.*

---

### `[0:55 – 1:24.5]` — The money
**Screen:** Money Flow panel. The single 2025 payment, then the 21 June cluster.

> Here is what passed between them.
> (...)
> Last June, Suresh sent the company **fifty thousand rupees**. One payment. (...)
> Then nothing — for a year.
> (...)
> On the twenty-first of June, in **fifteen hours**, the company sent it back.
> Six transfers. Five lakh each. (...) **Thirty lakh rupees.**
> (...)
> Sixty times what went out — into the account of a retired man who declares one
> and a half lakh a year.

*Delivery: "Thirty lakh rupees" is the peak of the script. Land it, then stop. The pause after does the arithmetic for the listener.*

---

### `[1:24.5 – 1:45]` — How it moved
**Screen:** Transaction rows — the six transfers, channel column visible. Then the branch-cash transfers.

> And look at how it moved. NEFT. IMPS. UPI. RTGS. (...) Rotated every three hours,
> so no single payment rail ever sees the whole picture.
> (...)
> In those same three weeks, the company pushed **five cash transfers** to four
> other accounts. Every one of them just under the ten lakh reporting threshold.

*Delivery: the four rail names are a clipped list — four beats, even spacing. Then open back up for the last sentence.*

---

### `[1:45 – 2:15]` — The AI recommendation, and arguing with it
**Screen:** AI widget → Recommendations (**pre-generated** — see production note). Show the two accepted, then open the rejected toggle. Then the challenge box.

> This is where it stops being a dashboard.
> (...)
> It tells me what to do next — and which rule it comes from. FATF Recommendation
> ten. (...) The PMLA.
> (...)
> And **two more it threw away** — because the model cited a number it couldn't
> trace back to our own data.
> (...)
> I can **argue** with it, too. Why not close this as a legitimate business refund?
> (...)
> It answers from the facts of **this** case — or it doesn't answer at all.

*Delivery: "argue" carries the weight — this is the differentiator. Slight lift on it, the only real warmth in the read.*

**Why the last line is phrased that way — do not "fix" it.** The grounding gate
genuinely rejects the AI's own answer when it can't cite a fact, and it did
exactly that on this case in testing (see `docs/DEMO_SCRIPT.md` → Verification).
"…or it doesn't answer at all" stays true on camera whether the challenge comes
back answered or rejected. A line that promises an answer would be a lie half the
time.

**Type this challenge question, exactly — it is the only one verified to survive
the grounding gate:**

> `In plain words, and without quoting any statistics or scores, why is this not an ordinary business refund?`

Four other phrasings were tested live and **all four were rejected**, because the
model reached for a similarity score or velocity ratio it couldn't cite. Banning
statistics in the question is what gets a grounded answer back. Have it on the
clipboard; do not improvise one on camera.

**The two rejected recommendations are real and worth showing on screen:**
`INVESTIGATE_ROUND_TRIP` (invented a `137.11` velocity ratio) and
`EXPAND_NETWORK_INVESTIGATION` (invented a `4,771,733.37` total). What survived
was `FILE_STR` — so the system recommends filing the report you then go and file.

---

### `[2:15 – 2:26]` — The graph
**Screen:** Toggle to Deep view. Investigation Graph — the cycle visible.

> The graph closes the loop. Money out, money back, through a sanctioned
> counterparty.
> (...)
> And I only see **this** network. Not the bank's entire customer base.

---

### `[2:26 – 2:38]` — Escalate (maker–checker)
**Screen:** Decision panel → Escalate to Compliance. Reason typed. Submit.

> I've seen enough. I escalate.
> (...)
> And this is the part a bank will ask about first: **I cannot close this case.**
> (...) I investigate. Someone else decides.

*Delivery: say "I cannot close this case" as a feature, with a touch of pride — not as a limitation.*

---

### `[2:38 – 2:53]` — Compliance and the report
**Screen:** Switch to the compliance window. Close as true positive → STR panel unlocks → Generate → Finalize → Submit.

> Compliance picks it up. Confirms it. (...) And only now does the report unlock.
> (...)
> FIU-IND format, written from the case itself — every claim in it cited to a
> number the system computed. Not one the model invented.

*Delivery: "Not one the model invented" is the trust line. Say it plainly and stop.*

---

### `[2:53 – 3:00]` — Close
**Screen:** The filed report on screen. Hold still. No cursor movement.

> Alert, to filed report. (...) One case. One system.
> (...)
> **Every rupee leaves a trail.**

*Delivery: full stop. Let two seconds of silence run before the video cuts — do not clip the tail.*

---

## Rendering the audio

The narration is rendered by `scripts/make_voiceover.py`, which holds the spoken
text as data — **that script, not this doc, is what actually gets spoken.** Keep
the two in step if you edit either.

```bash
# one-time install (free, no API key, no account)
python3 -m venv .venv-tts && .venv-tts/bin/pip install edge-tts

# render — Indian-English male, the default
python scripts/make_voiceover.py

# other voices
python scripts/make_voiceover.py --voice en-IN-NeerjaNeural          # Indian English, female
python scripts/make_voiceover.py --voice en-US-AndrewMultilingualNeural
python scripts/make_voiceover.py --list-voices

# nudge the pace if a block overruns its slot
python scripts/make_voiceover.py --edge-rate -6
```

Default engine is **`edge`** — Microsoft's Edge read-aloud neural voices. Free,
no key, no signup, and markedly more natural than macOS `say`. The Indian-English
voices are the right pick here for two reasons: the audience is Union Bank, and
they pronounce **"lakh"** and **"crore"** correctly, which the US/UK voices do not.
It needs an internet connection — it's a hosted service, not a local model.

`--engine say` renders offline with macOS voices. It sounds robotic; use it only
as a scratch timing track if you have no connection. `--engine openai` and
`--engine elevenlabs` are wired up too and sound better still, but both need a
paid API key.

**Output:** `data/voiceover/` — one WAV per block plus `voiceover-full.wav`.
Gitignored: it's a build artifact, regenerated in about a minute.

### Why every block is padded to its slot

Each block is padded with silence to exactly the target length in the table
below. That means **every block starts at its published timecode no matter which
engine or voice rendered it.** Re-render in a different voice and your video cut
points do not move. If a block's speech *overruns* its slot it can't be padded —
the renderer prints `OVERRUN` and names it, because that one would push every
later cue late.

---

## Production notes (read before you record the screen)

1. **Pre-generate the three AI panels — they are slow.** Measured live on this
   case: **recommendations 126s, cross-question 76s, STR generation 113s.** They
   are agentic loops (5-6 model round-trips each), and nothing is cached — every
   click re-runs the whole loop. Over five minutes of spinner if you try to do it
   on camera. Trigger each one *before* you record that segment and cut to the
   finished panel.

2. **Reset before every take:** `cd backend && .venv/bin/python scripts/prep_demo_live.py`.
   The demo mutates the case (escalate → close → file), so take two on an
   un-reset DB will show a case that is already closed.
3. **Two browser windows, pre-logged-in** — `investigator1` and `compliance1`.
   The switch at `[2:42]` is a window switch, never a logout on camera.
4. **Record at 1440p or higher**, browser at ~125% zoom. The Customer Snapshot
   text at `[0:32]` is the most important thing on screen and it is small.
5. **Cursor discipline.** No idle wiggling. Move deliberately, stop moving while a
   number is being read. Motion pulls the eye away from the figure being spoken.
6. **The `[0:32]` and `[1:04]` blocks are 32 and 26 seconds** — the two longest.
   Do not fill them with scrolling. Land on the panel and let it sit.

---

## Word/timing budget

| Block | Start | Slot | Spoken | On screen |
|---|---|---|---|---|
| Cold open | 0:00 | 10.5s | 8.0s | Dashboard queue |
| The alert | 0:10.5 | 14.0s | 13.1s | Alert Summary |
| **The contrast** | **0:24.5** | **30.5s** | 29.7s | **Customer Snapshot** |
| The money | 0:55 | 29.5s | 28.4s | Money Flow |
| How it moved | 1:24.5 | 20.5s | 20.2s | Transaction rows |
| **AI + challenge** | **1:45** | **30.0s** | 28.1s | **Recommendations panel** |
| The graph | 2:15 | 11.0s | 10.7s | Investigation Graph |
| Escalate | 2:26 | 12.0s | 11.3s | Decision panel |
| Compliance + STR | 2:38 | 15.0s | 14.7s | Report panel |
| Close | 2:53 | 7.0s | 6.8s | Filed report |
| **Total** | | **180.0s** | 171.1s | |

"Spoken" is measured from the rendered scratch track; the remainder of each slot
is padded silence, so **every block starts at the timecode above no matter which
voice engine you use.** Re-render with a different engine and the cut points do
not move. Regenerate the numbers any time with:

```bash
python scripts/make_voiceover.py --engine say --voice Samantha --rate 140
```

If a take runs long, cut **"How it moved"** to just the four rail names and the
threshold sentence (saves ~6s), or drop **"The graph"** entirely (saves 14s).
Never cut the contrast, the money, or the challenge.
