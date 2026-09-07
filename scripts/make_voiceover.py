#!/usr/bin/env python3
"""
Render the 3-minute demo voiceover (`docs/DEMO_VOICEOVER.md`) to audio.

The script text lives here as data, not parsed out of the markdown, so the
timing metadata travels with the words and a stray edit to the doc's prose
can't silently desync the audio. `docs/DEMO_VOICEOVER.md` stays the human-
readable version (delivery notes, screen actions); this file is what actually
gets spoken. **If you change one, change the other.**

Output: one WAV per block plus a concatenated full track, and a manifest of
actual-vs-target durations so you can see which block ran long before you cut
any video to it.

Engines
-------
  edge       DEFAULT. Microsoft Edge read-aloud neural voices. Free, no API key,
             no account — the best-sounding option available without a paid
             credential, and the Indian-English voices say "lakh" and "crore"
             correctly. Needs internet. Install:
                 python3 -m venv .venv-tts && .venv-tts/bin/pip install edge-tts
  say        macOS built-in. Free, offline, no key. Robotic — a timing scratch
             track to cut video against, not for the final video.
  openai     OpenAI TTS (`gpt-4o-mini-tts`). Genuinely natural, and takes a
             free-text `instructions` string for delivery/tone. Needs
             OPENAI_API_KEY. This is the one that sounds human.
  elevenlabs ElevenLabs. Also excellent. Needs ELEVENLABS_API_KEY (+ optionally
             ELEVENLABS_VOICE_ID).

Usage
-----
    python scripts/make_voiceover.py                       # edge, Indian-English male
    python scripts/make_voiceover.py --voice en-IN-NeerjaNeural
    python scripts/make_voiceover.py --list-voices
    python scripts/make_voiceover.py --engine say --voice Samantha   # offline scratch
    OPENAI_API_KEY=... python scripts/make_voiceover.py --engine openai --voice onyx
    python scripts/make_voiceover.py --engine openai --dry-run   # timing estimate only

Requires `ffmpeg` on PATH for silence generation and concatenation.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "data" / "voiceover"

#: Delivery direction handed to engines that accept one (OpenAI TTS). Mirrors
#: the "Delivery direction" section of `docs/DEMO_VOICEOVER.md`.
DELIVERY_INSTRUCTIONS = (
    "You are a bank anti-money-laundering investigator narrating a case you worked "
    "this morning. Calm, unhurried, professional, faintly dry. The facts are alarming; "
    "your delivery is not — the understatement is what makes it land. Let every "
    "monetary figure land on its own with a beat after it, and never rush a number. "
    "Statements, not questions: no upward inflection at the end of lines. "
    "This is a person reporting what they found, not a salesperson pitching it."
)

#: A hard silence splice, in seconds. Used ONLY for the two or three genuinely
#: dramatic beats. Every other pause is punctuation inside a segment, so the
#: neural voice generates the pause itself with a continuous intonation contour.
#: Splicing silence between separately-synthesised chunks is what made the first
#: pass sound wrong: the voice stopped dead and restarted with a fresh, unrelated
#: pitch contour every single time.


#: block key -> spoken length before target padding, filled in during render.
_spoken_len: dict[str, float] = {}


@dataclass
class Seg:
    """One span of speech rendered in a single TTS request, with its own
    prosody. `rate`/`pitch`/`volume` are deltas applied on top of the global
    baseline, which is what gives the read its high and low points instead of
    one flat machine cadence.

    `pause` is hard silence appended AFTER this segment — reserve it for real
    dramatic beats; prefer a comma, full stop or ellipsis inside `text`."""

    text: str
    rate: int = 0      # % delta on the baseline rate
    pitch: int = 0     # Hz delta (negative = lower, heavier)
    volume: int = 0    # % delta (negative = quieter, more intimate)
    pause: float = 0.0  # hard silence after, seconds


@dataclass
class Block:
    key: str
    start: str
    target_s: float
    screen: str
    parts: list[Seg]
    words: int = field(init=False)
    pause_s: float = field(init=False)

    def __post_init__(self) -> None:
        self.words = sum(len(p.text.split()) for p in self.parts)
        self.pause_s = sum(p.pause for p in self.parts)

    @property
    def text(self) -> str:
        return " ".join(p.text for p in self.parts)

    @property
    def required_wpm(self) -> float:
        """Words per minute the voice must actually hit once the block's own
        hard silence is subtracted. Anything over ~170 here is a gabble."""
        speaking_s = self.target_s - self.pause_s
        return self.words / speaking_s * 60 if speaking_s > 0 else float("inf")


BLOCKS_STORY: list[Block] = [
    # Prosody arc, block by block. The read has to have a floor and a ceiling:
    # the corporate account is deliberately DULL (flat, low, slightly quick —
    # it's throwaway), which is what makes the drop on "The second one does"
    # and the peak on "Thirty lakh rupees" register at all. A flat read of
    # alarming facts sounds like a machine listing them.
    Block(
        "01-cold-open", "0:00", 10.5,
        "Dashboard, alert queue, cursor moving to the top row",
        [
            Seg("This morning, the detection engine finished its run "
                "across the bank's ledger.", pitch=-2),
            Seg("This is what was waiting at the top of my queue.", rate=-6, pitch=-3),
        ],
    ),
    Block(
        "02-the-alert", "0:10.5", 14.0,
        "Click top alert; case opens; Alert Summary panel",
        [
            Seg("A round-trip alert. Risk score: eighty-seven.", rate=-4),
            # Read off the screen — flatter, quieter, like quoting.
            Seg("Confidence... very strong.", rate=-12, pitch=-4, volume=-6, pause=0.5),
            Seg("It isn't just telling me something looks wrong.", pitch=1),
            Seg("It's telling me what shape of wrong, and how certain it is.",
                rate=-4, pitch=-2),
        ],
    ),
    Block(
        "03-the-contrast", "0:24.5", 30.5,
        "Customer Snapshot — Continental Logistics, then scroll to Suresh Bansal",
        [
            Seg("Two accounts.", rate=-8, pause=0.45),
            # Deliberately dull: quick, low, uninterested. This is the floor.
            Seg("The first is Continental Logistics. A corporate customer. "
                "Four crore declared income. KYC verified. Medium risk.",
                rate=6, pitch=-3, volume=-4),
            Seg("Nothing about this account asks for my attention.",
                rate=-6, pitch=-5, volume=-6, pause=1.15),
            # The drop. Slower and LOWER than anything around it.
            Seg("The second one does.", rate=-20, pitch=-6, pause=1.0),
            Seg("Suresh Bansal. Retired.", rate=-14, pause=0.4),
            Seg("Declared income... one lakh, fifty thousand rupees.",
                rate=-16, pitch=-2, pause=0.6),
            Seg("His KYC was rejected.", rate=-10, pause=0.55),
            # Only real lift in the block — the last fact is the worst one.
            Seg("And he is on a sanctions list.", rate=-12, pitch=3),
        ],
    ),
    Block(
        "04-the-money", "0:55", 29.5,
        "Money Flow panel — the 2025 payment, then the 21 June cluster",
        [
            Seg("Here is what passed between them.", pitch=-2, pause=0.4),
            # Small and quiet — the ₹50k is meant to sound trivial.
            Seg("Last June, Suresh sent the company fifty thousand rupees. "
                "One payment.", rate=-4, pitch=-3, volume=-7),
            Seg("Then nothing, for a year.", rate=-14, pitch=-5, volume=-5, pause=1.0),
            # Pick the energy up — this is the turn.
            Seg("On the twenty-first of June, in fifteen hours, "
                "the company sent it back.", rate=4, pitch=3),
            Seg("Six transfers. Five lakh each.", rate=2, pitch=2, pause=0.5),
            # The peak of the whole script: slowest, highest, loudest.
            Seg("Thirty lakh rupees.", rate=-22, pitch=5, volume=6, pause=1.2),
            # Straight back down — the contrast is the point.
            Seg("Sixty times what went out. Into the account of a retired man "
                "who declares one and a half lakh a year.",
                rate=-8, pitch=-4, volume=-3),
        ],
    ),
    Block(
        "05-how-it-moved", "1:24.5", 20.5,
        "Transaction rows with the channel column; then the branch-cash transfers",
        [
            Seg("And look at how it moved.", pitch=1),
            # Clipped staccato list — the commas do the beats, not spliced silence.
            Seg("N E F T... I M P S... U P I... R T G S.",
                rate=-10, pitch=2, pause=0.5),
            Seg("Rotated every three hours, so no single rail ever sees "
                "the whole picture.", rate=-2, pitch=-2, pause=0.55),
            Seg("And in those same three weeks, five more cash transfers "
                "went out.", pitch=-1),
            Seg("Every one just under the ten lakh reporting threshold.",
                rate=-14, pitch=-3),
        ],
    ),
    Block(
        "06-ai-and-challenge", "1:45", 30.0,
        "AI widget → Recommendations (PRE-GENERATED), rejected panel, then the challenge box",
        [
            # The other lift in the script — this is the differentiator.
            Seg("This is where it stops being a dashboard.",
                rate=-6, pitch=4, pause=0.55),
            Seg("It tells me what to do next, and which rule says so.", pitch=2),
            Seg("F A T F Recommendation ten. The P M L A.", rate=-8, pause=0.5),
            # Conspiratorial — lower and quieter, like leaning in.
            Seg("And two more it threw away. The model cited numbers it "
                "couldn't trace to our own data.",
                rate=-4, pitch=-5, volume=-5, pause=0.8),
            Seg("I can argue with it, too.", rate=-8, pitch=4, pause=0.35),
            Seg("Why not close this as a legitimate business refund?",
                rate=-2, pitch=1, pause=0.6),
            Seg("It answers from the facts of this case... or it doesn't "
                "answer at all.", rate=-12, pitch=-3),
        ],
    ),
    Block(
        "07-the-graph", "2:15", 11.0,
        "Toggle to Deep view; Investigation Graph with the cycle visible",
        [
            Seg("The graph closes the loop. Money out, money back, "
                "through a sanctioned counterparty.", rate=-2, pitch=1, pause=0.5),
            Seg("And I only see this network. Not the bank's entire "
                "customer base.", rate=-6, pitch=-3),
        ],
    ),
    Block(
        "08-escalate", "2:26", 12.0,
        "Decision panel → Escalate to Compliance; reason typed; submit",
        [
            Seg("I've seen enough. I escalate.", rate=2, pitch=2, pause=0.55),
            # Weighty — this is the governance point, say it low and slow.
            Seg("And this is the part a bank will ask about first: "
                "I cannot close this case.", rate=-12, pitch=-5, pause=0.5),
            Seg("I investigate. Someone else decides.", rate=-10, pitch=-3),
        ],
    ),
    Block(
        "09-compliance-str", "2:38", 15.0,
        "Switch window; close as true positive; STR panel unlocks; generate",
        [
            Seg("Compliance picks it up. Confirms it.", pitch=1, pause=0.4),
            Seg("And only now does the report unlock.", rate=-6, pitch=2, pause=0.5),
            Seg("F I U India format, written from the case itself. Every claim "
                "cited to a number the system computed.", rate=-2, pitch=-1),
            # The trust line. Flat, quiet, certain.
            Seg("Not one the model invented.", rate=-16, pitch=-5, volume=-3),
        ],
    ),
    Block(
        "10-close", "2:53", 7.0,
        "The filed report on screen, still, no cursor movement",
        [
            Seg("Alert, to filed report. One case. One system.",
                rate=-8, pitch=-2, pause=0.6),
            # Slowest and lowest thing in the whole track.
            Seg("Every rupee leaves a trail.", rate=-20, pitch=-4),
        ],
    ),
]


#: FULL-COVERAGE cut. Same 180 seconds, but every built surface gets named —
#: bought by compressing the story beats and using montage lines (one sentence
#: naming a cluster while the video cuts through four panels). Denser and less
#: dramatic than BLOCKS_STORY; that is the actual trade, and it is not about
#: loading time — 180s at a natural 150wpm is ~430 words however the video is cut.
BLOCKS_FULL: list[Block] = [
    Block(
        "01-cold-open", "0:00", 12.0,
        "Dashboard; alert queue; hover the RL-ranked ordering",
        [
            Seg("This morning the detection engine finished its run across "
                "the bank's ledger.", pitch=-2),
            Seg("My queue ranks by what investigators actually confirmed "
                "before, not just by score.", rate=-2),
            Seg("This was at the top.", rate=-10, pitch=-3),
        ],
    ),
    Block(
        "02-the-alert", "0:12", 10.0,
        "Open case; Alert Summary panel",
        [
            Seg("A round-trip alert. Risk eighty-seven.", rate=-4),
            Seg("Confidence... very strong.", rate=-12, pitch=-4, volume=-6, pause=0.4),
            Seg("It tells me the shape of what's wrong, and how sure it is.",
                rate=-2, pitch=-1),
        ],
    ),
    Block(
        "03-the-contrast", "0:22", 24.0,
        "Customer Snapshot — Continental Logistics, then Suresh Bansal",
        [
            Seg("Two accounts.", rate=-8, pause=0.35),
            Seg("Continental Logistics. Corporate customer, four crore declared "
                "income, KYC verified, medium risk.", rate=6, pitch=-3, volume=-4),
            Seg("Nothing here asks for my attention.",
                rate=-6, pitch=-5, volume=-6, pause=1.0),
            Seg("The second one does.", rate=-20, pitch=-6, pause=0.9),
            Seg("Suresh Bansal. Retired. Declared income, one lakh fifty thousand.",
                rate=-14, pause=0.45),
            Seg("KYC rejected.", rate=-10, pause=0.4),
            Seg("And he is on a sanctions list.", rate=-12, pitch=3),
        ],
    ),
    Block(
        "04-the-money", "0:46", 25.0,
        "Money Flow — the 2025 seed payment, then the 21 June cluster",
        [
            Seg("Last June, Suresh sent the company fifty thousand rupees. "
                "One payment.", rate=-2, pitch=-3, volume=-7),
            Seg("Then nothing, for a year.", rate=-14, pitch=-5, volume=-5, pause=0.9),
            Seg("On the twenty-first of June, in fifteen hours, they sent back "
                "six transfers of five lakh each.", rate=4, pitch=3),
            Seg("Thirty lakh rupees.", rate=-22, pitch=5, volume=6, pause=1.1),
            Seg("Sixty times what went out. Into an account declaring one and "
                "a half lakh a year.", rate=-8, pitch=-4, volume=-3),
        ],
    ),
    Block(
        "05-how-it-moved", "1:11", 13.5,
        "Transaction rows, channel column; then the branch-cash transfers",
        [
            Seg("N E F T... I M P S... U P I... R T G S.",
                rate=-8, pitch=2, pause=0.35),
            Seg("Rotated every three hours, so no single rail sees the whole "
                "picture.", rate=-2, pitch=-2),
            Seg("And five more cash transfers that month, every one just under "
                "ten lakh.", rate=-8, pitch=-3),
        ],
    ),
    Block(
        "06-network-and-reuse", "1:24.5", 12.5,
        "Network Risk panel, then Similar Cases and Previous Alerts",
        [
            Seg("The network score catches what the account score misses. "
                "One sanctioned entity, a closed cycle, two high-centrality "
                "accounts.", rate=2, pitch=1),
            Seg("Four past cases look almost identical. All four were confirmed.",
                rate=-10, pitch=-3),
        ],
    ),
    Block(
        "07-deep-montage", "1:37", 15.0,
        "MONTAGE — graph replay, timeline, relationship explorer, behaviour "
        "analysis, transaction explorer, pattern explanation, evidence panel",
        [
            Seg("Underneath, the whole investigation surface.", pitch=2, pause=0.3),
            Seg("The graph replayed hour by hour. A full timeline. Shared "
                "addresses and phones. Behavioural shift. Every pattern "
                "explained.", rate=4),
            Seg("And an evidence file that builds itself as I work.",
                rate=-8, pitch=-2),
        ],
    ),
    Block(
        "08-ai-and-challenge", "1:52", 27.0,
        "AI widget → Recommendations (PRE-GENERATED); rejected toggle; challenge box",
        [
            Seg("Then it tells me what to do next, and which rule says so.",
                rate=-4, pitch=4),
            Seg("F A T F Recommendation ten. P M L A section twelve.",
                rate=-8, pause=0.45),
            Seg("Two more it threw away. The model cited numbers it couldn't "
                "trace to our own data.", rate=-2, pitch=-5, volume=-5, pause=0.7),
            Seg("And I can argue with it.", rate=-8, pitch=4, pause=0.3),
            Seg("Why isn't this an ordinary business refund?", pitch=1, pause=0.5),
            Seg("It answers from this case's facts... or not at all.",
                rate=-12, pitch=-3),
        ],
    ),
    Block(
        "09-copilot", "2:19", 13.0,
        "AI widget → Copilot tab; cross-case question; My Center",
        [
            Seg("I can also just ask. Across my whole caseload, not one case.",
                pitch=3),
            Seg("What's due. What's gone quiet. What looks like this.",
                rate=-6, pause=0.35),
            Seg("And personal data never reaches the model.",
                rate=-10, pitch=-4, volume=-3),
        ],
    ),
    Block(
        "10-escalate", "2:32", 8.0,
        "Decision panel → Escalate to Compliance",
        [
            Seg("I've seen enough. I escalate.", rate=2, pitch=2, pause=0.4),
            Seg("And I cannot close this case. I investigate. Someone else "
                "decides.", rate=-12, pitch=-5),
        ],
    ),
    Block(
        "11-compliance-str", "2:40", 13.0,
        "Compliance window; close TP; STR generate, finalize, submit",
        [
            Seg("Compliance confirms it, and only then does the report unlock.",
                pitch=1, pause=0.35),
            Seg("F I U India format, written from the case. Every claim cited "
                "to a number we computed.", rate=-2, pitch=-1),
            Seg("Not one the model invented.", rate=-16, pitch=-5, volume=-3),
        ],
    ),
    Block(
        "12-governance-close", "2:53", 7.0,
        "MONTAGE — watchlist, model governance, rule review queue, audit log; "
        "then hold on the filed report",
        [
            Seg("Watchlist. Model governance. Rule review. An audit trail on "
                "every action.", rate=4, pitch=-1, pause=0.5),
            Seg("Every rupee leaves a trail.", rate=-20, pitch=-4),
        ],
    ),
]

#: INVESTOR cut (`docs/DEMO_VOICEOVER_V2.md`), rendered to a 239s / 3:59 budget.
#:
#: The V2 markdown's own timing table is an UNRENDERED estimate and is wrong by
#: roughly 40%: its 1,022 words need ~6:50 at a natural 150wpm, not the 4:45 it
#: claims (it says so itself -- "not yet measured against a rendered track").
#: These blocks are that script compressed to fit, using V2's own trim-priority
#: list and honouring its "never cut" set (the contrast, the money, the AI
#: challenge exchange, the last two lines of the close).
#:
#: Three deviations from the V2 markdown, all forced by what the reset database
#: actually contains -- verified against `data/tracex_demo_live.db`:
#:   1. The cold open's watchlist SCREEN VISIT is cut (V2 trim option 5). The
#:      `watchlist` table is empty after `prep_demo_live.py`, so there is no
#:      panel to cut to. The spoken value beat is kept; nothing claims a screen.
#:   2. The network-risk `[VERIFY]` number is NOT spoken. The real value is 24.0,
#:      which lands as an anticlimax straight after "eighty-seven" even though it
#:      is near the top of this dataset. The panel's actual reasons are narrated
#:      instead -- 1 sanctioned entity, 1 cycle, 2 high-centrality accounts,
#:      straight out of `cases.network_risk_reasons`.
#:   3. The similar-cases line is REWRITTEN. V2 says "one turned out to be
#:      legitimate"; the real top-5 for this case is 4x TRUE_POSITIVE_SAR plus
#:      1x ENHANCED_MONITORING, all round_trip, with no false positive anywhere
#:      in it. The V2 wording would have been a false statement on camera.
BLOCKS_V2: list[Block] = [
    Block(
        "01-cold-open", "0:00", 20.0,
        "Alert queue, full list, risk/confidence badges. Cursor idle, then the top row",
        [
            Seg("Every morning, this ledger throws up thousands of transactions. This queue is what's left.",
                rate=-2, pitch=5, volume=3),
            Seg("Not sorted by time — sorted by risk. Then reshuffled by a system that has watched every case my team has closed.", rate=-2, pitch=2, pause=0.47),
            Seg("False alarms sink. Confirmed frauds rise. And this one was right at the top.", rate=-10, pitch=6, volume=4),
        ],
    ),
    Block(
        "02-three-systems", "0:20", 29.0,
        "Click top alert; case opens; Alert Summary + confidence badge, then the network-risk panel beside it",
        [
            Seg("A round-trip alert. Risk score: eighty-seven. Confidence... very strong.", rate=-8, pitch=4, pause=0.61),
            Seg("And that isn't one model's opinion. A machine-learning model, a rules engine, a network analysis engine — all three agreed.", rate=0, pitch=2, pause=0.54),
            Seg("And a second score asks a different question: not is this account suspicious, but is it inside a suspicious web?", rate=-4, pitch=7, volume=3, pause=0.47),
            Seg("One sanctioned entity. A closed cycle. Two accounts everything routes through.", rate=-16, pitch=-4, volume=2),
        ],
    ),
    Block(
        "03-the-contrast", "0:49", 30.0,
        "Customer Snapshot -- Continental Logistics, then scroll to Suresh Bansal. PROTECTED BEAT -- the emotional core",
        [
            Seg("Two accounts.", rate=-16, pitch=5, volume=5, pause=0.68),
            Seg("The first is Continental Logistics — a corporate customer, four crore declared income, KYC verified, medium risk. Nothing about this account asks for my attention.",
                rate=6, pitch=-8, volume=-9, pause=2.10),
            Seg("But the second one... does.", rate=-26, pitch=11, volume=9, pause=1.95),
            Seg("Suresh Bansal. Retired. Declared income — one lakh, fifty thousand rupees. His KYC was rejected... and he is on a sanctions list.",
                rate=-16, pitch=6, volume=4),
        ],
    ),
    Block(
        "04-pattern-explanation", "1:19", 11.0,
        "Pattern-explanation panel -- the 'why was this flagged' text",
        [
            Seg("Before I open a single transaction, the system has already written why it flagged this — in plain words, not a score.",
                rate=-2, pitch=6, volume=3, pause=0.54),
            Seg("I didn't need to be a data scientist to trust that.", rate=-12, pitch=-3),
        ],
    ),
    Block(
        "05-similar-cases", "1:30", 14.0,
        "Triage panel -> Similar Historical Cases card, top-3 expanded",
        [
            Seg("And I'm not looking at this cold. It pulls up the closest cases we've already closed.", rate=-2, pitch=5, volume=3, pause=0.47),
            Seg("Four of them were filed as confirmed reports. One was kept under monitoring.", rate=-8, pitch=4, pause=0.61),
            Seg("Not one of them was dismissed.", rate=-24, pitch=-6, volume=4),
        ],
    ),
    Block(
        "06-the-money", "1:44", 31.0,
        "Money Flow -- the 2025 seed payment, then the 21 June cluster, then the AI account explanation beside it. PROTECTED BEAT",
        [
            Seg("So here's what actually passed between them. Last June, Suresh sent the company fifty thousand rupees. One payment.",
                rate=-2, pitch=-3, volume=-6, pause=0.47),
            Seg("Then nothing... for a year.", rate=-22, pitch=-9, volume=-7, pause=2.05),
            Seg("And then, on the twenty-first of June — in fifteen hours — the company sent it back. Six transfers, five lakh each.",
                rate=4, pitch=7, volume=3, pause=0.68),
            Seg("Thirty lakh rupees.", rate=-30, pitch=14, volume=10, pause=1.76),
            Seg("Sixty times what went out... into the account of a retired man who declares one and a half lakh a year.", rate=-14, pitch=-4, volume=2),
        ],
    ),
    Block(
        "07-how-it-moved", "2:15", 19.0,
        "Transaction rows, channel column; then the branch-cash transfers",
        [
            Seg("How did it move? N E F T... I M P S... U P I... R T G S.",
                rate=-12, pitch=4, pause=0.61),
            Seg("Rotated every three hours — no single rail sees everything.", rate=-6, pitch=7, volume=4, pause=0.54),
            Seg("And five cash transfers, each just under the ten lakh threshold.", rate=-14, pitch=-4, volume=2),
        ],
    ),
    Block(
        "08-graph-explanation", "2:34", 13.0,
        "Toggle to Deep view; Investigation Graph, the cycle visible, replay running",
        [
            Seg("The graph makes it visual. Money out, money back — through a sanctioned counterparty.", rate=-6, pitch=6, volume=3, pause=0.61),
            Seg("And I can replay the whole fifteen hours, in order. This is the timeline a regulator will ask for.", rate=-8, pitch=3),
        ],
    ),
    Block(
        "09-ai-copilot", "2:47", 29.0,
        "AI widget -> Recommendations (PRE-GENERATED). Two accepted, open the rejected toggle, then the challenge box. PROTECTED BEAT",
        [
            Seg("This is where it stops being a dashboard.",
                rate=-6, pitch=8, volume=5, pause=0.54),
            Seg("It tells me what to do next — and which rule says so. F A T F Recommendation ten. The P M L A.", rate=-6, pitch=3, pause=0.61),
            Seg("And two more it threw away itself — the numbers didn't check out.", rate=-4, pitch=-6, volume=-5, pause=0.81),
            Seg("And I can argue with it. Why isn't this an ordinary business refund?", rate=-6, pitch=9, volume=5, pause=0.74),
            Seg("It answers from this case's facts... or not at all. An AI that proves what it says, or says nothing.",
                rate=-16, pitch=4, volume=3),
        ],
    ),
    Block(
        "10-escalate", "3:16", 12.0,
        "Decision panel -> Escalate to Compliance, reason typed, submit",
        [
            Seg("I've seen enough. I escalate.", rate=-2, pitch=7, volume=5, pause=0.68),
            Seg("And here's what a bank asks about first: I cannot close this case. I investigate — someone else decides.",
                rate=-14, pitch=-4, volume=2),
        ],
    ),
    Block(
        "11-compliance-str", "3:28", 14.0,
        "Compliance window; close as true positive; STR generate, finalize, submit",
        [
            Seg("Compliance confirms it — and only now does the report unlock.", rate=-4, pitch=6, volume=3, pause=0.54),
            Seg("F I U India format, written from the case. Every claim cited to a number the system computed.", rate=-6, pitch=2, pause=0.61),
            Seg("Not one the model invented.", rate=-26, pitch=-7, volume=-2),
        ],
    ),
    Block(
        "12-close", "3:42", 17.0,
        "MONTAGE -- the filed report. Hold still, no cursor movement",
        [
            Seg("Alert... to filed report. What took half a day across four systems took a fraction of that.",
                rate=-4, pitch=5, volume=3, pause=0.61),
            Seg("Fewer false alarms. Faster investigations. And a report that holds up when someone asks how we knew.",
                rate=-8, pitch=4, volume=3, pause=0.94),
            Seg("Every rupee leaves a trail.", rate=-28, pitch=-5, volume=5),
        ],
    ),
]


#: Which cut `main()` renders; set from --cut.
BLOCKS: list[Block] = BLOCKS_FULL


# ── engines ──────────────────────────────────────────────────────────────────


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {proc.stderr.strip()[:400]}")


def synth_say(text: str, out_wav: Path, voice: str, rate: int) -> None:
    """macOS `say`. Renders AIFF, then converts — `say` can't write WAV directly."""
    aiff = out_wav.with_suffix(".aiff")
    _run(["say", "-v", voice, "-r", str(rate), "-o", str(aiff), text])
    _run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(aiff),
          "-ar", "44100", "-ac", "1", str(out_wav)])
    aiff.unlink(missing_ok=True)


def synth_edge(text: str, out_wav: Path, voice: str, rate_pct: int,
               pitch_hz: int = 0, volume_pct: int = 0) -> None:
    """Microsoft Edge read-aloud neural voices. Free, no API key, no account —
    the best-sounding option available here without a paid credential. Needs
    an internet connection (it is a hosted service, not a local model).

    Install once:  python3 -m venv .venv-tts && .venv-tts/bin/pip install edge-tts
    """
    exe = os.environ.get("EDGE_TTS_BIN") or shutil.which("edge-tts")
    if exe is None:
        local = REPO / ".venv-tts" / "bin" / "edge-tts"
        if local.exists():
            exe = str(local)
    if exe is None:
        raise RuntimeError(
            "edge-tts not found. Install it with:\n"
            "  python3 -m venv .venv-tts && .venv-tts/bin/pip install edge-tts"
        )
    mp3 = out_wav.with_suffix(".mp3")
    # `--rate` wants an explicit sign, e.g. -8% / +5%.
    cmd = [exe, "--voice", voice,
           "--rate", f"{rate_pct:+d}%",
           "--pitch", f"{pitch_hz:+d}Hz",
           "--volume", f"{volume_pct:+d}%",
           "--text", text, "--write-media", str(mp3)]
    # A full render is ~35 requests in quick succession and the service throttles
    # intermittently — a dropped websocket mid-run would otherwise lose the whole
    # take. Retry with backoff rather than failing the render.
    last: Exception | None = None
    for attempt in range(5):
        try:
            _run(cmd)
            break
        except RuntimeError as exc:
            last = exc
            time.sleep(1.5 * (attempt + 1))
    else:
        raise RuntimeError(f"edge-tts failed after 5 attempts: {last}")
    _run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3),
          "-ar", "44100", "-ac", "1", str(out_wav)])
    mp3.unlink(missing_ok=True)


def synth_openai(text: str, out_wav: Path, voice: str) -> None:
    from openai import OpenAI  # noqa: PLC0415 — optional dependency

    client = OpenAI()
    with client.audio.speech.with_streaming_response.create(
        model="gpt-4o-mini-tts",
        voice=voice,
        input=text,
        instructions=DELIVERY_INSTRUCTIONS,
        response_format="wav",
    ) as response:
        response.stream_to_file(out_wav)


def synth_elevenlabs(text: str, out_wav: Path, voice_id: str) -> None:
    import json      # noqa: PLC0415
    import urllib.request  # noqa: PLC0415

    key = os.environ["ELEVENLABS_API_KEY"]
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=pcm_44100",
        method="POST",
        headers={"xi-api-key": key, "Content-Type": "application/json"},
        data=json.dumps({
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {"stability": 0.45, "similarity_boost": 0.75, "style": 0.25},
        }).encode(),
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        pcm = resp.read()
    raw = out_wav.with_suffix(".pcm")
    raw.write_bytes(pcm)
    _run(["ffmpeg", "-y", "-loglevel", "error", "-f", "s16le", "-ar", "44100",
          "-ac", "1", "-i", str(raw), str(out_wav)])
    raw.unlink(missing_ok=True)


# ── assembly ─────────────────────────────────────────────────────────────────


def trim_edges(path: Path) -> None:
    """Strip the leading/trailing near-silence every TTS request wraps its audio
    in, in place.

    Each `Seg` is its own request, so concatenating them stacks one chunk's
    trailing pad against the next one's leading pad. That dead air between
    phrases is what reads as an abrupt stop-start rather than a person
    breathing: the words end, nothing happens, then a new phrase begins on an
    unrelated pitch. Trimming both ends lets `render_block` insert the exact
    gap it wants instead of the exact gap the model happened to leave."""
    tmp = path.with_suffix(".trim.wav")
    filt = (
        "silenceremove=start_periods=1:start_silence=0:start_threshold=-45dB:detection=peak,"
        "areverse,"
        "silenceremove=start_periods=1:start_silence=0:start_threshold=-45dB:detection=peak,"
        "areverse"
    )
    _run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(path),
          "-af", filt, "-ar", "44100", "-ac", "1", "-c:a", "pcm_s16le", str(tmp)])
    # A segment that trims to nothing means the threshold ate real speech --
    # keep the original rather than silently dropping a line.
    if tmp.exists() and tmp.stat().st_size > 2000:
        tmp.replace(path)
    else:
        tmp.unlink(missing_ok=True)


def wav_duration(path: Path) -> float:
    with wave.open(str(path)) as w:
        return w.getnframes() / float(w.getframerate())


def silence(seconds: float, out_wav: Path) -> None:
    _run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
          "-i", f"anullsrc=r=44100:cl=mono", "-t", f"{seconds:.3f}", str(out_wav)])


def concat(parts: list[Path], out_wav: Path, tmp: Path) -> None:
    listing = tmp / f"concat_{out_wav.stem}.txt"
    listing.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts))
    _run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
          "-i", str(listing), "-c", "copy", str(out_wav)])
    listing.unlink(missing_ok=True)


def render_block(block: Block, args: argparse.Namespace, tmp: Path) -> Path:
    """Render each segment in its own TTS request at its own rate/pitch/volume,
    then splice only the hard pauses. Per-segment prosody is what gives the read
    a high and a low; a single global rate is what made the first pass sound
    like a machine reading a list."""
    parts: list[Path] = []
    for i, sg in enumerate(block.parts):
        seg = tmp / f"{block.key}_seg{i}.wav"
        if args.engine == "edge":
            synth_edge(sg.text, seg, args.voice,
                       args.edge_rate + sg.rate, sg.pitch, sg.volume)
        elif args.engine == "say":
            # `say` has no pitch/volume control; approximate with rate only.
            synth_say(sg.text, seg, args.voice, args.rate + sg.rate)
        elif args.engine == "openai":
            synth_openai(sg.text, seg, args.voice)
        else:
            synth_elevenlabs(sg.text, seg, args.voice)
        trim_edges(seg)
        parts.append(seg)
        # Every join gets a real, deliberate gap. `--seg-gap` is the breath
        # between phrases of the same thought; `pause` adds the dramatic
        # silences on top. Without this the trimmed chunks butt together and
        # the read gabbles.
        gap = args.seg_gap + sg.pause
        if i < len(block.parts) - 1 or sg.pause > 0:
            if gap > 0.01:
                sil = tmp / f"{block.key}_sil{i}.wav"
                silence(gap, sil)
                parts.append(sil)

    out = OUT_DIR / f"{block.key}.wav"
    concat(parts, out, tmp)
    for p in parts:
        p.unlink(missing_ok=True)

    # Pad the block out to its exact target length. This is what makes the track
    # safe to cut video against: every block then STARTS at the timecode printed
    # in `docs/DEMO_VOICEOVER.md`, no matter which engine rendered it or how fast
    # that engine talks. Without it, swapping the scratch `say` track for a
    # neural one shifts every later cut point and desyncs the whole video.
    # A block that OVERRUNS its target can't be padded — it is reported instead.
    spoken = wav_duration(out)
    _spoken_len[block.key] = spoken
    if not args.no_pad:
        if spoken < block.target_s:
            pad = tmp / f"{block.key}_pad.wav"
            silence(block.target_s - spoken, pad)
            padded = tmp / f"{block.key}_padded.wav"
            concat([out, pad], padded, tmp)
            shutil.move(str(padded), str(out))
            pad.unlink(missing_ok=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--engine", choices=("edge", "say", "openai", "elevenlabs"), default="edge")
    ap.add_argument("--edge-rate", type=int, default=36,
                    help="edge only: BASELINE speech rate offset in percent; each segment's own rate delta is applied on top")
    ap.add_argument("--voice", default=None,
                    help="edge: en-IN-PrabhatNeural/en-IN-NeerjaNeural/en-US-AndrewMultilingualNeural | "
                         "say: Samantha/Daniel/Rishi | openai: onyx/alloy/sage | elevenlabs: voice id")
    ap.add_argument("--rate", type=int, default=155, help="say only: words per minute")
    ap.add_argument("--list-voices", action="store_true", help="list macOS English voices and exit")
    ap.add_argument("--dry-run", action="store_true", help="print the timing budget, synthesize nothing")
    ap.add_argument("--cut", choices=("full", "story", "v2"), default="full",
                    help="full: every built surface named (12 beats, dense). "
                         "story: the original 10-beat cut, more room to breathe. "
                         "v2: the investor cut (docs/DEMO_VOICEOVER_V2.md), 12 beats / 239s")
    ap.add_argument("--seg-gap", type=float, default=0.16,
                    help="baseline silence inserted between segments, seconds. "
                         "Segments are silence-trimmed first, so this is the "
                         "ONLY gap between phrases; `pause` stacks on top.")
    ap.add_argument("--out-dir", default=None,
                    help="output directory (default: data/voiceover, or "
                         "data/voiceover-v2 when --cut v2). Set explicitly to "
                         "avoid overwriting an existing rendered take.")
    ap.add_argument("--no-pad", action="store_true",
                    help="don't pad blocks to their target length (breaks timecode alignment)")
    args = ap.parse_args()

    if args.list_voices:
        if args.engine == "edge":
            exe = (os.environ.get("EDGE_TTS_BIN") or shutil.which("edge-tts")
                   or str(REPO / ".venv-tts" / "bin" / "edge-tts"))
            subprocess.run(f"{exe} --list-voices | grep -E 'en-(IN|US|GB)'", shell=True)
        else:
            subprocess.run("say -v '?' | grep -E 'en_(US|GB|IN|AU)'", shell=True)
        return 0

    global BLOCKS, OUT_DIR
    BLOCKS = {"full": BLOCKS_FULL, "story": BLOCKS_STORY, "v2": BLOCKS_V2}[args.cut]

    # A v2 render defaults to its OWN directory: data/voiceover holds the
    # verified V1 take, and re-rendering over it would destroy the only audio
    # that matches a checked script.
    if args.out_dir:
        # Must be absolute: `concat()` writes each part's path into an
        # ffmpeg listing file, and ffmpeg resolves relative entries against
        # the LISTING's directory, not the cwd -- a relative --out-dir
        # doubles the prefix and every render fails to open its own parts.
        OUT_DIR = Path(args.out_dir).resolve()
    elif args.cut == "v2":
        OUT_DIR = REPO / "data" / "voiceover-v2"

    total_words = sum(b.words for b in BLOCKS)
    total_target = sum(b.target_s for b in BLOCKS)
    if args.dry_run:
        print(f"{'block':22} {'start':>6} {'target':>7} {'pause':>6} {'words':>6} {'wpm':>5}  flag")
        for b in BLOCKS:
            flag = "GABBLE" if b.required_wpm > 170 else ("slow" if b.required_wpm < 115 else "")
            print(f"{b.key:22} {b.start:>6} {b.target_s:6.1f}s {b.pause_s:5.1f}s "
                  f"{b.words:6d} {b.required_wpm:5.0f}  {flag}")
        total_pause = sum(b.pause_s for b in BLOCKS)
        print(f"\n{'TOTAL':22} {'':>6} {total_target:6.1f}s {total_pause:5.1f}s "
              f"{total_words:6d} {total_words / (total_target - total_pause) * 60:5.0f}")
        return 0

    if args.voice is None:
        args.voice = {"edge": "en-IN-PrabhatNeural", "say": "Samantha", "openai": "onyx",
                      "elevenlabs": os.environ.get("ELEVENLABS_VOICE_ID", "")}[args.engine]
    if not shutil.which("ffmpeg"):
        print("error: ffmpeg not found on PATH", file=sys.stderr)
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # Clear block WAVs left by a previous render of the OTHER cut — the two cuts
    # use different block keys, so stale files would otherwise sit alongside the
    # current ones and get picked up by mistake in the edit.
    keep = {f"{b.key}.wav" for b in BLOCKS} | {"voiceover-full.wav", "voiceover-full.mp3"}
    for old_wav in OUT_DIR.glob("*.wav"):
        if old_wav.name not in keep:
            old_wav.unlink()
    tmp = OUT_DIR / ".tmp"
    tmp.mkdir(exist_ok=True)

    print(f"engine={args.engine} voice={args.voice}\n")
    print(f"{'block':22} {'start':>6} {'target':>7} {'spoken':>7} {'headroom':>9}")
    rendered: list[Path] = []
    total_actual = 0.0
    overruns: list[str] = []
    for b in BLOCKS:
        path = render_block(b, args, tmp)
        actual = wav_duration(path)
        total_actual += actual
        # After padding, `actual` == target; the useful number is how much
        # silence is left at the end of the block (or how far it overran).
        headroom = b.target_s - (actual if args.no_pad else _spoken_len[b.key])
        flag = ""
        if headroom < 0:
            flag = "  OVERRUN"
            overruns.append(b.key)
        elif headroom > 3.0:
            flag = "  (lots of dead air)"
        print(f"{b.key:22} {b.start:>6} {b.target_s:6.1f}s "
              f"{_spoken_len[b.key]:6.1f}s {headroom:+8.1f}s{flag}")
        rendered.append(path)

    full = OUT_DIR / "voiceover-full.wav"
    concat(rendered, full, tmp)
    shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{'TOTAL':22} {'':>6} {total_target:6.1f}s "
          f"{sum(_spoken_len.values()):6.1f}s")
    print(f"\nper-block wavs: {OUT_DIR}")
    print(f"full track:     {full}  ({total_actual:.1f}s)")
    if overruns:
        print(f"\nOVERRUN — these blocks are longer than their slot and will push "
              f"every later cue late:\n  {', '.join(overruns)}\n"
              f"  Fix by trimming their words or raising --rate, not by ignoring it.")
    else:
        print("\nEvery block fits its slot; each one starts at the timecode in "
              "docs/DEMO_VOICEOVER.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
