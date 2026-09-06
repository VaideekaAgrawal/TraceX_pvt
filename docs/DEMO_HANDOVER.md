# TraceX Demo — Handover

Everything needed to bring up **the exact system the demo was built and recorded
against**, and to cut the video against the audio that already exists.

Read this first, then `docs/DEMO_VOICEOVER.md` (the narration + timecodes) and
`docs/DEMO_SCRIPT.md` (the longer click-through and all the verified numbers).

---

## 1. What was built, and why

The demo is **one case walked end to end**: an alert lands on an investigator's
desk in the morning, they work it, escalate it, Compliance confirms it, and an
STR is filed with FIU-IND. One story, told properly — not a feature tour.

Three artefacts came out of it:

| File | What it is |
|---|---|
| `docs/DEMO_VOICEOVER.md` | The 3-minute narration: 12 timecoded blocks, delivery direction, the screen action each block sits over |
| `docs/DEMO_SCRIPT.md` | The full click-through, every number verified live, plus the failure playbook |
| `scripts/make_voiceover.py` | Renders the narration to audio. **Holds the spoken text as data — this file, not the markdown, is what actually gets spoken** |
| `backend/scripts/prep_demo_live.py` | Resets the demo DB to the exact starting state between takes |
| `data/voiceover/*.mp3` | The rendered audio — the take the video should be cut against |

**The audio is recorded first; the video is cut to match it.** That is why the
timecodes are the contract.

---

## 2. Set up the software (30–40 minutes, mostly waiting on installs)

### Prerequisites

- Python 3.12+ (this machine ran 3.14.6)
- Node 20+
- `ffmpeg` — `brew install ffmpeg` (needed only to re-render audio)

### Steps

```bash
git clone https://github.com/VaideekaAgrawal/TraceX_pvt.git
cd TraceX_pvt
# (already cloned? just: git pull)

# backend
cd backend
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# frontend
cd ../frontend
npm install
```

### Create `backend/.env`

Copy `backend/.env.example` to `backend/.env`, then set these five:

```ini
ENV=dev
DATABASE_URL=sqlite:///../data/tracex_demo_live.db

JWT_SECRET=<openssl rand -hex 32>
PII_HMAC_KEY=<openssl rand -hex 32>

LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_PROVIDER=openrouter
LLM_MODEL=anthropic/claude-sonnet-4.5
OPENROUTER_API_KEY=<ask the team — NOT in git, never commit it>
```

Three things worth knowing:

- **`DATABASE_URL` is relative to `backend/`.** Keep the `../data/` prefix and run
  the server from `backend/`.
- **`JWT_SECRET` and `PII_HMAC_KEY` can be anything you generate.** They don't have
  to match anyone else's. `PII_HMAC_KEY` only keys hashes at *write* time, and the
  relationship rows are already in the committed database — so a different key
  changes nothing you'll see. (Corollary: **don't run
  `scripts/discover_relationships.py`.** It would rewrite those hashes for no gain.)
- **`OPENROUTER_API_KEY` is the one real secret.** It has to come from a teammate
  over Signal/WhatsApp/1Password — not email, not a commit, not a screenshot in a
  group chat. Without it the three AI panels return 503; everything else still works.

### Bring it up

```bash
# terminal 1
cd backend && .venv/bin/python scripts/prep_demo_live.py
cd backend && .venv/bin/uvicorn api.app:create_app --factory --host 127.0.0.1 --port 8001

# terminal 2
cd frontend && npm run dev
```

Open **http://localhost:3000**.

> ### ⚠️ Port 8001, not 8000
> `frontend/.env.local` contains `BACKEND_API_URL=http://127.0.0.1:8001`. Start the
> backend on 8000 and every panel goes blank **with no error message** — it looks
> like the app is broken. This costs people 20 minutes every single time.

### Logins

| Role | Username | Password |
|---|---|---|
| Investigator | `investigator1` | `TraceX@2026` |
| Admin / Compliance | `compliance1` | `TraceX@2026` |

Both already exist in the committed database — no user creation needed.

**Open two browser windows before recording**: one logged in as `investigator1`,
one as `compliance1`. The role switch at 2:32 must be a window switch, never a
logout on camera.

---

## 3. The database — read this before you touch it

There are two files and they do different jobs:

- **`data/tracex_demo.db`** — committed to git. The shared pitch dataset: 200
  customers, 207 accounts, 2,316 transactions, 105 alerts, 105 cases, 3 users.
  **Never run the app against this one.** Every click would dirty the dataset
  everyone shares.
- **`data/tracex_demo_live.db`** — gitignored, disposable. What the app actually
  runs against. `prep_demo_live.py` recreates it from the committed copy.

```bash
cd backend && .venv/bin/python scripts/prep_demo_live.py
```

That script copies the committed DB over the live one and rewinds the hero case to
"landed on my desk this morning": status `ASSIGNED`, detected 02:14 today, SLA
clock running, no prior AI interactions or reports.

> ### ⚠️ Reset before EVERY take
> The demo mutates the case: escalate → close as true positive → file the STR.
> **It only walks that path once.** A second take on an un-reset database shows a
> case that is already closed, and the STR panel behaves completely differently.
> If the backend crashes *after* you've escalated, you've lost the take — reset
> and start over.

You do **not** need to re-run detection, retrain the model, or regenerate demo
data. All of that is already baked into the committed DB.

*(Known cosmetic gap: `model_runs.artifact_path` in the committed DB is an
absolute path from the machine that trained it, so the Model Governance page will
show the model as having no artifact file. Metrics and lineage still display. It's
one line on a montage screen — don't stop to fix it.)*

---

## 4. The demo itself

**Hero case: `CASE-20260718-13F5F994`**

**Continental Logistics Pvt Ltd** (`DEMO-ACC-0185`) — corporate customer, ₹4 Cr
declared income, KYC verified, MEDIUM risk. Looks completely ordinary.

**Suresh Bansal** (`DEMO-ACC-0145`) — Retired, ₹1.5 L declared income,
**sanctioned**, **KYC rejected**, CRITICAL risk.

June 2025: Suresh sends the company **₹50,000**. One payment, then a year of
pension-shaped noise. On **21 June 2026, in a 15-hour window**, the company sends
back **six transfers of ₹5,00,000 — ₹30,00,000 total** — rotated across NEFT,
IMPS, UPI and RTGS at exact three-hour intervals. **60× what went out**, into the
account of a retired, sanctioned man declaring ₹1.5 L a year. In the same weeks
the company pushed **five branch-cash transfers to four other accounts, every one
just under the ₹10,00,000 CTR threshold.**

Every 2026 transaction above is labelled `is_laundering = 1` in the dataset; the
2025 seed payment is clean. The story is real, not a coincidence of the seed.

Beat-by-beat narration and screen actions: **`docs/DEMO_VOICEOVER.md`.**

---

## 5. Three things that will bite you

### (a) The AI panels are slow — pre-generate them

Measured live on this case:

| Panel | Latency |
|---|---|
| Recommendations | **126s** |
| Cross-question (challenge) | **76s** |
| STR generation | **113s** |

These are agentic loops — 5–6 model round-trips each — and **nothing is cached**,
so every click re-runs the whole loop. Over five minutes of spinner if you try to
do it live.

**Trigger each one before you start recording that segment, then cut to the
finished panel.** The narration is written assuming the panel is already full.

### (b) Use this challenge question verbatim

The grounding gate rejects the AI's own answer whenever it quotes a number it
can't trace to a cited fact — and on this case the model reliably reaches for
similarity scores. **Five phrasings were tested. Four were rejected.** This is the
one that works:

> `In plain words, and without quoting any statistics or scores, why is this not an ordinary business refund?`

Forbidding statistics is what stops it grabbing the numbers that get it rejected.
**Have it on the clipboard. Do not improvise a different one on camera.**

### (c) Free memory before recording

The backend was killed twice by memory pressure during this work. Quit Cursor,
VS Code, WhatsApp and spare Chrome windows before you start. Losing the server
mid-take costs you the whole run (see the reset warning above).

---

## 6. The audio

`data/voiceover/` — committed as MP3:

- **`voiceover-full.mp3`** — the complete 3-minute track
- **`01-cold-open.mp3` … `12-governance-close.mp3`** — one file per block

**Cut the video against the per-block files, not the full track.** Every block is
padded with silence to exactly its slot length, so each one starts at the timecode
published in `docs/DEMO_VOICEOVER.md`. That means you can drop them on a timeline
at fixed positions and the cues won't drift.

Current take: `edge` engine, voice `en-IN-PrabhatNeural`, base rate +36%.
Spoken content 179.6s against the 180s budget; assembled track 186.9s (five blocks
overrun their slot by 0.5–1.9s).

### Re-rendering it

Only if the words change. Needs internet — it's a hosted service.

```bash
python3 -m venv .venv-tts && .venv-tts/bin/pip install edge-tts
python scripts/make_voiceover.py                      # full 12-beat cut (current)
python scripts/make_voiceover.py --cut story          # 10-beat cut, more room to breathe
python scripts/make_voiceover.py --voice en-IN-NeerjaNeural
python scripts/make_voiceover.py --list-voices
python scripts/make_voiceover.py --dry-run            # timing budget, renders nothing
```

Takes about four minutes. Output goes to `data/voiceover/` as WAV; convert to MP3
with `ffmpeg` if you need to re-share.

**Why `edge`:** free, no API key, no account, and the Indian-English voices
pronounce "lakh" and "crore" correctly — the US/UK voices mangle both, which would
be audible in nearly every line. `--engine openai` and `--engine elevenlabs` are
wired up and sound better still, but need a paid key.

**Two cuts exist.** `--cut full` (current, 12 beats) names every built surface,
using montage lines — one sentence over four or five panels. `--cut story`
(10 beats) drops the montages and gives the story beats more room. Both are 180s.

---

## 7. How the narration is built (if you need to change words)

`scripts/make_voiceover.py` holds each block as a list of `Seg` objects. Each `Seg`
is one span of speech rendered in its own TTS request with its own `rate`, `pitch`
and `volume` offsets. That per-segment prosody is what gives the read a high and a
low instead of one flat machine cadence — e.g. the Continental Logistics
description is deliberately faster, lower and quieter (it's meant to sound dull),
which is what makes the drop on *"The second one does"* and the peak on
*"Thirty lakh rupees"* register at all.

Two rules if you edit it:

1. **Prefer punctuation over spliced silence.** `...` and full stops inside a
   segment let the voice generate its own pause with a continuous intonation
   contour. A `pause=` splices real silence between two separately-synthesised
   chunks — the voice stops dead and restarts with an unrelated pitch line, which
   sounds wrong. Only three or four genuinely dramatic beats should use it.
2. **Watch the `OVERRUN` warnings.** The renderer prints them per block. A block
   that overruns its slot can't be padded and pushes every later cue late.

`--dry-run` prints the words-per-minute each block demands once its own silence is
subtracted. Over ~170 is a gabble.

---

## 8. What is deliberately NOT claimed

- **The 44,790-alert figure is not in the narration.** It comes from the full IBM
  benchmark run; the demo database on screen has 105 alerts. Saying it over that
  queue would be contradicted by the screen. It belongs in the deck, not here.
- **The generated STR narrative reads raw** — it prints `40000000.0` and
  `CLOSED_TP` rather than "₹4 crore" and "closed as true positive". It's accurate
  and fully grounded, but **don't zoom into the body text on camera.** Show that
  the report exists, is finalized, and is submitted.
- **`docs/pitch.md`, `explanation.md`, `pptcontent.md`, `cross_questions.md` are
  pre-refactor artifacts** describing an older system with different ML numbers.
  Don't cite them. See `docs/PRESENTATION_PREP_CHECKLIST.md`.

---

## 9. If something breaks

| Symptom | Cause / fix |
|---|---|
| Every panel blank, no error | Backend on the wrong port. Must be **8001**. |
| AI panels return 503 | `OPENROUTER_API_KEY` missing or invalid in `backend/.env` |
| Case already escalated/closed | Someone ran a take without resetting → `prep_demo_live.py` |
| A panel returns 403 | Wrong role's browser window — switch tabs, don't log out |
| Backend dies unprompted | Memory pressure. Close other apps, restart, reset the DB. |
| Model Governance shows no artifact | Expected — see §3. Cosmetic. |

**Backup case** if the hero case is unusable: `CASE-20260718-A718E13E` — layering,
6 accounts, highest network risk in the dataset (28), primary customer **Silver
Line Exports Pvt Ltd**, sanctioned. Same script shape; the Beat 3 narration would
need rewording.
