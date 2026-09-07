#!/usr/bin/env python3
"""Build docs/TraceX_GFF26.pptx — the Global Fintech Festival '26 pitch deck.

Content source of truth: docs/GFF26_PPT_CONTENT.md. Edit that first, then this.

Deck constraints (from the event brief):
  * 16:9 (13.333in x 7.5in)
  * minimum font size 18pt anywhere on any slide  -> enforced by _pt()
  * 8 minutes total including the demo video
  * business audience: bank leadership, not engineers

Because the 18pt floor makes overflow easy and invisible until you open the file,
every text block estimates its own rendered height and each slide asserts that
its content fits inside its card. If you lengthen a string past its budget the
build fails loudly instead of shipping a broken slide.

Usage:
    python docs/build_gff26_deck.py [--video path/to/demo.mp4] [--out path.pptx]

Every quantitative claim traces to docs/METRICS.md. Don't add a number that
isn't in that ledger.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

# ---------------------------------------------------------------- design system

NAVY = RGBColor(0x12, 0x36, 0x5E)
NAVY2 = RGBColor(0x1B, 0x4B, 0x7E)
INK = RGBColor(0x0D, 0x1B, 0x2A)
RED = RGBColor(0xC8, 0x10, 0x2E)
TEAL = RGBColor(0x0E, 0x7C, 0x74)
AMBER = RGBColor(0x8A, 0x53, 0x14)
MUTED = RGBColor(0x59, 0x69, 0x7D)
FAINT = RGBColor(0x93, 0xA2, 0xB3)
LINE = RGBColor(0xD5, 0xDD, 0xE7)
CARD = RGBColor(0xF4, 0xF7, 0xFA)
BAND = RGBColor(0xEB, 0xF1, 0xF7)
PALE = RGBColor(0xA9, 0xC0, 0xDA)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

FONT = "Calibri"      # present in Office on both Windows and macOS
MIN_PT = 18           # the event brief's hard rule

W, H = 13.333, 7.5
ML = MR = 0.68
CW = W - ML - MR              # 11.973in of content width
TOP = 1.86                    # first content baseline, under the header rule
BOT = 6.88                    # last usable y before the footer

# Calibri metrics, calibrated against real Word line-fill (11pt/6.5in ~= 105ch).
_ADV = 0.42                   # average glyph advance, in em
_ADV_BOLD = 0.44
_LEAD = 1.22                  # baseline-to-baseline, in em


def _pt(size: int) -> Pt:
    assert size >= MIN_PT, f"{size}pt violates the {MIN_PT}pt floor"
    return Pt(size)


def nlines(s: str, w_in: float, size: int, bold: bool = False) -> int:
    cpl = max(1, int(w_in * 72 / ((_ADV_BOLD if bold else _ADV) * size)))
    return max(1, math.ceil(len(s) / cpl))


def need(name: str, bottom: float, limit: float) -> None:
    """Assert a content block fits its container."""
    assert bottom <= limit + 1e-6, (
        f"{name}: content reaches {bottom:.2f}in, container ends {limit:.2f}in "
        f"(over by {bottom - limit:.2f}in) — shorten the copy")


# ------------------------------------------------------------------- primitives

def new_deck() -> Presentation:
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(W), Inches(H)
    return prs


def blank(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(W), Inches(H))
    bg.fill.solid()
    bg.fill.fore_color.rgb = WHITE
    bg.line.fill.background()
    bg.shadow.inherit = False
    return s


def text(slide, x, y, w, body, *, size=MIN_PT, bold=False, color=INK,
         align=PP_ALIGN.LEFT, spacing=1.0, gap=0.0, italic=False, caps=False,
         h=None, limit=None, hang=0.0) -> float:
    """Place a text box; return the estimated bottom edge in inches.

    `hang` gives wrapped lines a hanging indent (for bullets). The width budget
    subtracts it from every line, so the estimate stays conservative.
    """
    lines = [body] if isinstance(body, str) else list(body)
    est = 0.0
    for i, ln in enumerate(lines):
        est += nlines(ln, w - hang, size, bold) * _LEAD * size * spacing / 72
        if i < len(lines) - 1:
            est += gap
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w),
                                   Inches(h if h else max(est, 0.2)))
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    for i, ln in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = spacing
        p.space_after = Pt(gap * 72)
        if hang:
            pPr = p._p.get_or_add_pPr()
            pPr.set("marL", str(int(hang * 914400)))
            pPr.set("indent", str(-int(hang * 914400)))
        r = p.add_run()
        r.text = ln.upper() if caps else ln
        r.font.name, r.font.size, r.font.bold, r.font.italic = FONT, _pt(size), bold, italic
        r.font.color.rgb = color
    if limit is not None:
        need(str(lines[0])[:30], y + est, limit)
    return y + est


def bullets(slide, x, y, w, items, *, size=18, color=INK, marker="•",
            spacing=1.02, gap=0.055, hang=0.0) -> float:
    """Bulleted list. Pass hang=0.30 when an item is long enough to wrap, so the
    second line aligns under the first rather than under the bullet."""
    return text(slide, x, y, w, [f"{marker}  {i}" for i in items], size=size,
                color=color, spacing=spacing, gap=gap, hang=hang)


def card(slide, x, y, w, h, *, fill=CARD, edge=None, radius=0.04):
    sh = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y),
                                Inches(w), Inches(h))
    sh.adjustments[0] = radius
    sh.fill.solid()
    sh.fill.fore_color.rgb = fill
    if edge is None:
        sh.line.fill.background()
    else:
        sh.line.color.rgb = edge
        sh.line.width = Pt(1)
    sh.shadow.inherit = False
    return sh


def bar(slide, x, y, w, h, color):
    sh = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y),
                                Inches(w), Inches(h))
    sh.fill.solid()
    sh.fill.fore_color.rgb = color
    sh.line.fill.background()
    sh.shadow.inherit = False
    return sh


def chevron(slide, x, y, w, h, num, label, fill):
    sh = slide.shapes.add_shape(MSO_SHAPE.CHEVRON, Inches(x), Inches(y),
                                Inches(w), Inches(h))
    sh.adjustments[0] = 0.26          # shallower notch, so 10-char labels fit
    assert nlines(label, w - 0.26 * h - 0.32, 18, True) == 1, \
        f"chevron label {label!r} wraps at {w:.2f}in"
    sh.fill.solid()
    sh.fill.fore_color.rgb = fill
    sh.line.fill.background()
    sh.shadow.inherit = False
    tf = sh.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Inches(0.16)
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    for i, (t, sz, col) in enumerate([(num, 18, PALE), (label, 18, WHITE)]):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = PP_ALIGN.CENTER
        r = p.add_run()
        r.text = t
        r.font.name, r.font.size, r.font.bold = FONT, _pt(sz), True
        r.font.color.rgb = col
    return sh


def stat(slide, x, y, w, h, value, label, *, value_size=30, fill=CARD,
         edge=None, value_color=NAVY):
    """Big number over a caption, vertically centred as a unit."""
    card(slide, x, y, w, h, fill=fill, edge=edge)
    lw = w - 0.36
    vh = _LEAD * value_size / 72
    lh = nlines(label, lw, 18) * _LEAD * 18 / 72
    top = y + (h - vh - 0.08 - lh) / 2
    text(slide, x + 0.18, top, lw, value, size=value_size, bold=True,
         color=value_color, align=PP_ALIGN.CENTER)
    bottom = text(slide, x + 0.18, top + vh + 0.08, lw, label, size=18,
                  color=MUTED, align=PP_ALIGN.CENTER)
    need(f"stat({value})", bottom, y + h)


def header(slide, eyebrow, title):
    text(slide, ML, 0.46, CW, eyebrow, size=18, bold=True, color=RED, caps=True)
    tb = text(slide, ML, 0.84, CW, title, size=32, bold=True, color=NAVY)
    need(f"title({title[:28]})", tb, 1.52)
    bar(slide, ML, 1.56, CW, 0.022, LINE)


def footer(slide, n):
    text(slide, ML, H - 0.48, 6.0, "TraceX  ·  Global Fintech Festival '26",
         size=18, color=FAINT)
    text(slide, W - MR - 1.4, H - 0.48, 1.4, str(n), size=18, bold=True,
         color=FAINT, align=PP_ALIGN.RIGHT)


def banner(slide, y, h, msg, *, fill=NAVY, color=WHITE, size=22):
    assert nlines(msg, CW - 0.5, size, True) == 1, f"banner wraps: {msg!r}"
    card(slide, ML, y, CW, h, fill=fill)
    tb = text(slide, ML, y + (h - _LEAD * size / 72) / 2, CW, msg, size=size,
              bold=True, color=color, align=PP_ALIGN.CENTER)
    need("banner", tb, y + h)


def notes(slide, script):
    slide.notes_slide.notes_text_frame.text = script


# ----------------------------------------------------------------------- slides

def s01_cover(prs):
    s = blank(prs)
    bar(s, 0, 0, W, 0.30, NAVY)
    bar(s, 0, 0.30, W, 0.075, RED)

    text(s, ML, 1.52, CW, "UNION BANK OF INDIA  ×  iDEA 2.0", size=20, bold=True,
         color=RED)
    text(s, ML, 2.06, CW, "TraceX", size=84, bold=True, color=NAVY)
    text(s, ML, 3.52, CW, "From suspicious signals to defensible decisions.",
         size=30, color=INK)
    bar(s, ML, 4.26, 2.2, 0.05, RED)
    text(s, ML, 4.58, CW * 0.78,
         "AI-powered AML detection & investigation intelligence", size=22,
         color=MUTED, limit=5.22)

    cw = CW * 0.66
    card(s, ML, 5.28, cw, 0.98, fill=BAND)
    tb = text(s, ML + 0.32, 5.48, cw - 0.64,
              "Every rupee leaves a trail. TraceX makes it impossible to hide.",
              size=20, bold=True, color=NAVY, italic=True)
    need("cover tagline", tb, 6.26)

    text(s, W - MR - 4.4, 5.30, 4.4,
         ["PSB Hackathon Winner", "Global Fintech Festival '26",
          "Vaideeka Agrawal  ·  Team syntax_error"],
         size=18, color=MUTED, align=PP_ALIGN.RIGHT, spacing=1.25)

    bar(s, 0, H - 0.20, W, 0.20, NAVY)
    notes(s, "0:15 — Good afternoon. I'm Vaideeka. This is TraceX: an AI investigation "
             "platform for anti-money-laundering, built for Union Bank of India, and one "
             "of the winning solutions from the PSB hackathon.")


def s02_problem(prs):
    s = blank(prs)
    header(s, "The problem", "The alerts aren't the problem. Clearing them is.")

    chips = [("₹54 Cr", "RBI penalties levied in FY25"),
             ("90–95%", "of AML alerts are false positives"),
             ("21 bn", "UPI transactions in one month, +29% YoY")]
    cw = (CW - 0.44) / 3
    for i, (v, l) in enumerate(chips):
        stat(s, ML + i * (cw + 0.22), TOP, cw, 1.62, v, l, value_size=30,
             fill=WHITE, edge=LINE)

    y2, bh = 3.66, 2.10
    bw = (CW - 0.34) / 2
    for i, (t, b, accent) in enumerate([
        ("THE DETECTION GAP",
         "A single transaction looks normal alone. Launderers structure below ₹10 "
         "lakh because row-by-row rules can't see across accounts.", RED),
        ("THE INVESTIGATION GAP",
         "Every alert still needs a human to assemble evidence by hand across four "
         "systems. The queue grows faster than the team.", NAVY),
    ]):
        x = ML + i * (bw + 0.34)
        card(s, x, y2, bw, bh)
        bar(s, x, y2, 0.075, bh, accent)
        text(s, x + 0.34, y2 + 0.26, bw - 0.62, t, size=20, bold=True, color=accent)
        tb = text(s, x + 0.34, y2 + 0.74, bw - 0.64, b, size=19, spacing=1.10)
        need(t, tb, y2 + bh - 0.10)

    banner(s, 5.96, 0.72,
           "Undetected.   Unresolved.   Unreported.   — and the penalty lands on the bank.")
    footer(s, 2)
    notes(s, "0:45 — Every bank here already monitors millions of transactions. That's not "
             "where it breaks; it breaks afterwards. Ninety to ninety-five percent of AML "
             "alerts are false positives, and every one still needs a human to assemble "
             "evidence by hand. Meanwhile the sophisticated money moves in the gap: "
             "structured below the threshold, split across accounts, layered through hops "
             "no row-by-row rule will connect. RBI issued fifty-four crore in penalties "
             "last year. That is not a detection failure. It's a resolution failure.")


def s03_loop(prs):
    s = blank(prs)
    header(s, "The idea", "What if AML could detect, investigate — and learn?")

    steps = [
        ("01", "DETECT", "Six typology detectors plus dual ML, reading the live transaction graph."),
        ("02", "PRIORITISE", "Ranked by risk, network context, and what past cases actually proved."),
        ("03", "INVESTIGATE", "Money flow, relationships and multi-hop activity on one screen."),
        ("04", "EXPLAIN", "Plain language — every claim cited to a fact the system computed."),
        ("05", "DECIDE", "Recommend: False Positive · Monitor · Escalate · Report."),
        ("06", "LEARN", "Every verdict re-ranks the queue and updates rule confidence."),
    ]
    cw = (CW - 0.52) / 3
    ch = 1.93
    for i, (num, t, b) in enumerate(steps):
        x = ML + (i % 3) * (cw + 0.26)
        y = TOP + (i // 3) * (ch + 0.24)
        card(s, x, y, cw, ch)
        card(s, x + 0.26, y + 0.24, 0.52, 0.44, fill=NAVY, radius=0.25)
        text(s, x + 0.26, y + 0.31, 0.52, num, size=18, bold=True, color=WHITE,
             align=PP_ALIGN.CENTER)
        text(s, x + 0.92, y + 0.30, cw - 1.10, t, size=21, bold=True, color=NAVY)
        tb = text(s, x + 0.26, y + 0.84, cw - 0.52, b, size=18, color=MUTED,
                  spacing=1.08)
        need(t, tb, y + ch - 0.10)

    banner(s, 6.16, 0.70,
           "Every investigation makes the next investigation smarter.",
           fill=BAND, color=NAVY, size=23)
    footer(s, 3)
    notes(s, "0:40 — TraceX closes the loop. It detects: six laundering typologies plus two "
             "ML models, reading the transaction graph rather than one row at a time. It "
             "prioritises, so your best investigator opens the case that matters most, not "
             "the one that arrived first. It investigates: money flow, relationships, "
             "customer profile, assembled before the analyst sits down. It explains that "
             "evidence in plain language. It recommends a decision. And then the part that "
             "compounds: every verdict goes back in as a learning signal.")


def s04_journey(prs):
    s = blank(prs)
    header(s, "The workflow", "One alert. One defensible decision.")

    labels = [("01", "DETECT"), ("02", "PRIORITISE"), ("03", "TRACE"),
              ("04", "UNDERSTAND"), ("05", "EXPLAIN"), ("06", "DECIDE"),
              ("07", "REPORT")]
    n, overlap = len(labels), 0.22
    cwid = (CW + overlap * (n - 1)) / n
    for i, (num, lab) in enumerate(labels):
        chevron(s, ML + i * (cwid - overlap), TOP, cwid, 1.00, num, lab,
                NAVY if i % 2 == 0 else NAVY2)

    y2, bh = 3.10, 2.44
    cards = [
        ("EVIDENCE, PRE-ASSEMBLED",
         "Profile, history, network and prior cases already on screen. No system-hopping."),
        ("EXPLANATION, NOT JUST A SCORE",
         "A written narrative of why this account is suspicious, every fact traceable."),
        ("REPORT, IN ONE CLICK",
         "An integrity-protected record in FIU-IND structure, generated — not re-keyed."),
    ]
    bw = (CW - 0.60) / 3
    for i, (t, b) in enumerate(cards):
        x = ML + i * (bw + 0.30)
        card(s, x, y2, bw, bh)
        bar(s, x + 0.30, y2 + 0.30, 0.9, 0.05, RED)
        text(s, x + 0.30, y2 + 0.56, bw - 0.60, t, size=20, bold=True, color=NAVY)
        tb = text(s, x + 0.30, y2 + 1.28, bw - 0.60, b, size=18, color=MUTED,
                  spacing=1.08)
        need(t, tb, y2 + bh - 0.08)

    banner(s, 5.72, 0.72,
           "A 15–30 minute triage — instead of a half-day evidence hunt.", size=23)
    footer(s, 4)
    notes(s, "0:35 — This is the whole journey, and the point is that it IS one journey. "
             "Today an investigator jumps between four systems to build one case. Here "
             "detection hands off to prioritisation, prioritisation to investigation, "
             "investigation to a written explanation, and that explanation to a report in "
             "FIU format, without re-keying anything. We designed the front line around a "
             "fifteen-to-thirty-minute triage decision. Let me show you.")


def s05_demo(prs, video):
    s = blank(prs)
    bar(s, 0, 0, W, H, NAVY)
    text(s, ML, 0.50, CW, "LIVE PRODUCT DEMO", size=18, bold=True,
         color=RGBColor(0xFF, 0x8A, 0x9C), caps=True)
    text(s, ML, 0.90, CW, "See it work. One alert, start to finish.", size=32,
         bold=True, color=WHITE)

    fx, fy, fw, fh = ML, 1.72, CW, 4.42
    if video and video.exists():
        s.shapes.add_movie(str(video), Inches(fx), Inches(fy), Inches(fw),
                           Inches(fh), mime_type="video/mp4")
    else:
        card(s, fx, fy, fw, fh, fill=RGBColor(0x0A, 0x22, 0x40),
             edge=RGBColor(0x2C, 0x59, 0x8C))
        text(s, fx, fy + 1.50, fw, "▶", size=54, bold=True,
             color=RGBColor(0xFF, 0x8A, 0x9C), align=PP_ALIGN.CENTER)
        text(s, fx, fy + 2.46, fw, "EMBED THE 2-MINUTE DEMO VIDEO HERE", size=22,
             bold=True, color=WHITE, align=PP_ALIGN.CENTER)
        text(s, fx + 1.6, fy + 3.00, fw - 3.2,
             "Insert → Video → This Device. Embed the file, never link it — the "
             "venue may have no internet.", size=18, color=PALE,
             align=PP_ALIGN.CENTER, spacing=1.10)

    text(s, ML, 6.34, CW,
         "Detect  ›  Prioritise  ›  Investigate  ›  Trace  ›  Explain  ›  "
         "Recommend  ›  Report  ›  Learn",
         size=19, bold=True, color=PALE, align=PP_ALIGN.CENTER, limit=6.86)
    text(s, W - MR - 1.4, H - 0.48, 1.4, "5", size=18, bold=True,
         color=RGBColor(0x5E, 0x7C, 0x9E), align=PP_ALIGN.RIGHT)
    notes(s, "2:00 — Before you hit play: 'Two minutes. One real alert, all the way to a "
             "filed report.' Say nothing over the video. When it ends, bridge with: 'What "
             "you just watched hinges on one idea.'\n\n"
             "PRE-FLIGHT: the video must be EMBEDDED in the .pptx, not linked. Keep the "
             "source .mp4 in the same folder as a fallback. Test audio on the venue machine, "
             "not your laptop.")


def s06_network(prs):
    s = blank(prs)
    header(s, "Why this is different", "A transaction is a row. Crime is a network.")

    bw, bh = (CW - 0.36) / 2, 3.60
    card(s, ML, TOP, bw, bh)
    text(s, ML + 0.34, TOP + 0.26, bw - 0.68, "TRADITIONAL VIEW", size=20,
         bold=True, color=MUTED)
    text(s, ML + 0.34, TOP + 0.80, bw - 0.68, "A → B → C → D", size=34,
         bold=True, color=MUTED, align=PP_ALIGN.CENTER)
    tb = bullets(s, ML + 0.34, TOP + 1.70, bw - 0.68,
                 ["Four transactions", "Four rows, four separate alerts",
                  "No context, no connection"], size=19, color=MUTED, marker="–")
    need("traditional", tb, TOP + bh - 0.10)

    rx = ML + bw + 0.36
    card(s, rx, TOP, bw, bh, fill=BAND, edge=NAVY)
    text(s, rx + 0.34, TOP + 0.26, bw - 0.68, "THE TRACEX VIEW", size=20,
         bold=True, color=RED)
    text(s, rx + 0.34, TOP + 0.80, bw - 0.68, "A → B → C → D → A",
         size=34, bold=True, color=NAVY, align=PP_ALIGN.CENTER)
    tb = bullets(s, rx + 0.34, TOP + 1.70, bw - 0.68, [
        "Layering — funds moving through multiple hops",
        "Circular flows — money returning to origin",
        "Mule networks — accounts as intermediaries",
        "Hidden links — shared PAN, zero transactions",
    ], size=18)
    need("tracex view", tb, TOP + bh - 0.10)

    banner(s, 5.70, 0.72,
           "The suspicious transaction is rarely the crime. "
           "The network is the evidence.")
    footer(s, 6)
    notes(s, "0:30 — A rules engine asks: did this transaction cross a threshold? TraceX "
             "asks: does this behaviour, in this network, form a suspicious pattern? Same "
             "four transactions on both sides. On the left, four rows and four separate "
             "alerts. On the right, one circular flow — money leaving an account and coming "
             "back. That's the case. And note the last line: customers connected by a shared "
             "PAN or employer with NO transactions between them. No transaction monitoring "
             "system will ever surface that, because there is no transaction to monitor.")


def s07_trust(prs):
    s = blank(prs)
    header(s, "Trusted AI", "AI that accelerates investigators — and never decides.")

    pillars = [
        ("GROUNDED", RED,
         "The AI can only state facts our system computed. A validator drops any "
         "sentence that doesn't cite one.", "No fact, no claim."),
        ("BLIND TO PII", NAVY,
         "Customer names never reach the model. Not de-identified — absent, behind "
         "a fail-closed gate.", "Enforced in code, not policy."),
        ("ACCOUNTABLE", TEAL,
         "Every investigator action and AI interaction writes to a tamper-evident "
         "audit chain.", "The AI recommends. A human decides."),
    ]
    bw, bh = (CW - 0.60) / 3, 3.42
    for i, (t, accent, body, kicker) in enumerate(pillars):
        x = ML + i * (bw + 0.30)
        card(s, x, TOP, bw, bh)
        bar(s, x, TOP, bw, 0.09, accent)
        text(s, x + 0.32, TOP + 0.34, bw - 0.64, t, size=22, bold=True, color=accent)
        tb = text(s, x + 0.32, TOP + 0.88, bw - 0.64, body, size=18, spacing=1.12)
        need(t, tb, TOP + 2.34)
        bar(s, x + 0.32, TOP + 2.44, bw - 0.64, 0.022, LINE)
        kb = text(s, x + 0.32, TOP + 2.64, bw - 0.64, kicker, size=19, bold=True,
                  color=NAVY)
        need(f"{t} kicker", kb, TOP + bh - 0.08)

    y2 = 5.40
    card(s, ML, y2, CW, 0.96, fill=BAND)
    text(s, ML + 0.34, y2 + 0.16, CW - 0.68, "WHAT THIS MEANS FOR THE BANK",
         size=18, bold=True, color=RED)
    tb = text(s, ML + 0.34, y2 + 0.52, CW - 0.68,
              "Higher throughput  ·  Standardised case files  ·  A trail that "
              "survives RBI inspection",
              size=19, bold=True, color=NAVY)
    need("trust strip", tb, y2 + 0.96)
    footer(s, 7)
    notes(s, "0:35 — This is what a compliance officer asks first, so let me answer before "
             "you ask. Our AI is not allowed to be creative. Every factual claim must cite a "
             "number our own code computed, and a separate validator checks that citation "
             "AFTER generation and deletes anything that doesn't resolve. We have watched "
             "that gate fire live: the model stated a figure that appeared in no cited fact, "
             "and it was rejected before a human saw it. Second, customer personal data "
             "never reaches the model at all — enforced in code, not promised in a policy. "
             "Third, everything is logged. The AI recommends. A human decides.")


def s08_security(prs):
    s = blank(prs)
    header(s, "Security, privacy & compliance",
           "Built for the regulator — not just for the demo.")

    quads = [
        ("DPDP ACT 2023 — BY DESIGN", RED, [
            "Runs inside your perimeter — you stay fiduciary",
            "Legal-obligation ground covers AML (PMLA 2002)",
            "The AI layer stores identifiers, never names",
            "PMLA's 5-year retention overrides erasure",
        ]),
        ("PMLA · RBI · FATF", NAVY, [
            "5-year retention: transactions, cases, STRs",
            "Detectors mapped to FATF Recs. 10 and 20",
            "Dormancy and structuring follow RBI guidance",
            "STR output follows FIU-IND structure",
        ]),
        ("ACCESS & DATA-LEAKAGE CONTROL", TEAL, [
            "Two roles, enforced server-side on every route",
            "Case-scoped visibility — never the whole ledger",
            "Identifiers tokenised with a separate key",
            "Self-host the model and nothing leaves your DC",
        ]),
        ("CYBER POSTURE", AMBER, [
            "SHA-256 audit chain across 693,102 rows",
            "Non-root, read-only containers, caps dropped",
            "Zero secrets in code — injected from your vault",
            "CI gate: 726 tests, 97.7% coverage, no bypass",
        ]),
    ]
    bw = (CW - 0.30) / 2
    bh = (BOT - TOP - 0.26) / 2
    for i, (t, accent, items) in enumerate(quads):
        x = ML + (i % 2) * (bw + 0.30)
        y = TOP + (i // 2) * (bh + 0.26)
        card(s, x, y, bw, bh)
        bar(s, x, y, 0.075, bh, accent)
        text(s, x + 0.30, y + 0.20, bw - 0.56, t, size=19, bold=True, color=accent)
        tb = bullets(s, x + 0.30, y + 0.64, bw - 0.58, items, size=18)
        need(t, tb, y + bh - 0.08)
    footer(s, 8)
    notes(s, "0:45 — SLOW DOWN HERE. This slide converts interest into a pilot.\n"
             "Four things your risk committee will ask. One, the DPDP Act: TraceX runs "
             "inside your perimeter as a processor; the bank keeps custody. AML processing "
             "sits under the Act's legal-obligation ground because PMLA requires it — and "
             "where erasure would collide with PMLA's five-year retention, the Act permits "
             "retention. Two, access: two roles enforced on the server, not in the "
             "interface. We tested it by calling the API directly, bypassing the UI — you "
             "get a real permission error. Three, leakage: every investigator, and the AI, "
             "sees only their own case's neighbourhood. Self-host the model and nothing "
             "leaves your data centre. Four, tamper evidence: our audit log is a "
             "cryptographic chain — edit one record and every record after it fails "
             "verification. Proven across six hundred and ninety-three thousand rows.")


def s09_scale(prs):
    s = blank(prs)
    header(s, "Scale & deployment", "100,000 transactions a day? That's three minutes.")

    chips = [("5.08 M", "real transactions ingested end-to-end, zero dropped"),
             ("~646/sec", "sustained on one node, audit-written per row"),
             ("~2.6 min", "to process a full 100,000-transaction day")]
    cw = (CW - 0.44) / 3
    for i, (v, l) in enumerate(chips):
        stat(s, ML + i * (cw + 0.22), TOP, cw, 1.50, v, l, value_size=30,
             fill=WHITE, edge=LINE)

    text(s, ML, 3.48, CW,
         "44,790 accounts from that run  ·  case queries under 100 ms  ·  "
         "cost flat as the ledger grows",
         size=18, bold=True, color=RED, align=PP_ALIGN.CENTER, limit=3.88)

    y2, bh = 3.92, 2.12
    rows = [
        ("COMPUTE", "Stateless API, 3 replicas minimum, auto-scaling to 20 on live "
                    "load, with zero-downtime rolling updates."),
        ("DATABASE", "SQLite for a pilot, PostgreSQL for production, behind one "
                     "storage interface. A config change, not a rewrite."),
        ("DEPLOYMENT", "Your Kubernetes, your OpenShift, or plain Docker on a server "
                       "in your own data centre. Air-gappable."),
    ]
    bw = (CW - 0.60) / 3
    for i, (t, b) in enumerate(rows):
        x = ML + i * (bw + 0.30)
        card(s, x, y2, bw, bh)
        text(s, x + 0.30, y2 + 0.24, bw - 0.60, t, size=20, bold=True, color=NAVY)
        tb = text(s, x + 0.30, y2 + 0.68, bw - 0.60, b, size=18, color=MUTED,
                  spacing=1.08)
        need(t, tb, y2 + bh - 0.08)

    ib, ih = 6.06, 0.82
    card(s, ML, ib, CW, ih, fill=NAVY)
    tb = text(s, ML + 0.30, ib + 0.14, CW - 0.60,
              "INSTALLATION:   provision node  ›  inject secrets from your vault  ›  "
              "point at your Postgres  ›  load a historical CSV export  ›  run "
              "detection  ›  go live",
              size=18, bold=True, color=WHITE, align=PP_ALIGN.CENTER, spacing=1.06)
    need("install strip", tb, ib + ih)
    footer(s, 9)
    notes(s, "0:45 — 'It works in a demo' is not a business case. We ingested five point "
             "zero eight million real transactions end to end — not sampled, not simulated "
             "— with zero rows dropped and a cryptographic audit record written for every "
             "one. That's about six hundred and fifty transactions a second on ONE node. So "
             "a hundred thousand transactions a day is roughly two and a half minutes of "
             "capacity, on one machine, before we scale out. Growing is deliberately "
             "boring: a stateless API that auto-scales; SQLite for a pilot and PostgreSQL "
             "in production behind one interface, so it's a config change; and it runs on "
             "your Kubernetes or a physical server in your own data centre. With a "
             "self-hosted model it can be fully air-gapped. And to install it, you need a "
             "CSV export. Not a core-banking integration.")


def s10_proof(prs):
    s = blank(prs)
    header(s, "Proof", "Measured, not claimed.")

    stats = [
        ("5,078,345", "real benchmark transactions processed, 0 skipped"),
        ("44,790", "suspicious accounts surfaced in one detection run"),
        ("726", "automated tests passing, at 97.7% coverage"),
        ("693,102", "audit records, chain integrity verified"),
        ("0.778", "AUC-ROC at a 0.48% base rate — real signal, hard problem"),
        ("< 100 ms", "case investigation query latency"),
    ]
    cw, ch = (CW - 0.56) / 3, 1.86
    for i, (v, l) in enumerate(stats):
        stat(s, ML + (i % 3) * (cw + 0.28), TOP + (i // 3) * (ch + 0.24), cw, ch,
             v, l, value_size=34)

    banner(s, 6.16, 0.70,
           "Every number here came from a run we can reproduce in front of you.")
    footer(s, 10)
    notes(s, "0:30 — Every number here is measured, not modelled. Five million real "
             "transactions through the real pipeline. Forty-four thousand suspicious "
             "accounts from one run. Seven hundred and twenty-six automated tests. Six "
             "hundred and ninety-three thousand audit records with the chain verified end "
             "to end. We can reproduce every one of these in front of you.\n\n"
             "IF CHALLENGED ON ML PRECISION: 'That's the honest number on a genuinely hard "
             "problem — under half a percent of accounts in the benchmark are actually "
             "positive. AUC-ROC of 0.778 is where the signal shows at that base rate, and "
             "it's exactly why ML is one signal in an ensemble with the typology rules and "
             "graph structure, never the sole decision-maker.'")


def s11_business(prs):
    s = blank(prs)
    header(s, "Business model", "A three-week pilot, not a three-year procurement.")

    steps = [
        ("WEEK 1", "PROVE", "Detection run on your own historical exports. CSV in, alerts out."),
        ("WEEK 2", "CALIBRATE", "Your compliance team tunes thresholds on your typologies."),
        ("WEEK 3", "RUN", "Two real investigators, real cases, an evaluation you own."),
        ("THEN", "DEPLOY", "Private cloud in your account, or on-premise. Data never leaves."),
    ]
    cw, ch = (CW - 0.72) / 4, 2.56
    for i, (wk, t, b) in enumerate(steps):
        x = ML + i * (cw + 0.24)
        card(s, x, TOP, cw, ch)
        bar(s, x, TOP, cw, 0.09, RED if i < 3 else NAVY)
        text(s, x + 0.28, TOP + 0.30, cw - 0.56, wk, size=18, bold=True,
             color=RED if i < 3 else NAVY)
        text(s, x + 0.28, TOP + 0.66, cw - 0.56, t, size=22, bold=True, color=NAVY)
        tb = text(s, x + 0.28, TOP + 1.12, cw - 0.56, b, size=18, color=MUTED,
                  spacing=1.08)
        need(wk, tb, TOP + ch - 0.08)

    y2, bh = 4.50, 1.78
    bw = (CW - 0.30) / 2
    for i, (t, items) in enumerate([
        ("COMMERCIAL MODEL", [
            "Pilot — 3 weeks, no core-banking integration",
            "Private-cloud licence — you keep data custody",
            "On-premise for hard data-residency mandates"]),
        ("THE MARKET", [
            "309 addressable Indian institutions",
            "₹114.5 Cr serviceable annual revenue in India",
            "Global AML software: $3.2 bn → $9.1 bn by 2034"]),
    ]):
        x = ML + i * (bw + 0.30)
        card(s, x, y2, bw, bh, fill=BAND)
        text(s, x + 0.30, y2 + 0.20, bw - 0.60, t, size=18, bold=True, color=RED)
        tb = bullets(s, x + 0.30, y2 + 0.60, bw - 0.60, items, size=18)
        need(t, tb, y2 + bh - 0.08)

    banner(s, 6.36, 0.52,
           "We complement your AML stack. We don't ask you to replace it.")
    footer(s, 11)
    notes(s, "0:35 — The commercial path is deliberately small at the start. Three weeks. "
             "Week one we run detection against your own historical exports; all we need is "
             "a CSV. Week two your compliance team calibrates it on your typologies, not "
             "ours. Week three, two real investigators work real cases and you write the "
             "evaluation. Then it deploys in your private cloud or on your own premises, "
             "and your data never leaves your custody. We're not asking anyone to rip out "
             "an existing AML system — we sit downstream of whatever you already run. "
             "That's a three-week decision, not a three-year procurement.")


def s12_close(prs):
    s = blank(prs)
    bar(s, 0, 0, W, H, NAVY)
    bar(s, 0, 0, W, 0.09, RED)

    text(s, ML, 1.36, CW,
         ["Detection finds the signal.", "Investigation finds the story.",
          "Feedback makes the system smarter."],
         size=26, color=PALE, spacing=1.28, limit=3.14)
    text(s, ML, 3.20, CW, "TraceX", size=72, bold=True, color=WHITE)
    text(s, ML, 4.56, CW, "Investigate better.  Decide faster.  Learn continuously.",
         size=26, color=WHITE, limit=5.22)

    cw = 7.30
    card(s, ML, 5.30, cw, 1.00, fill=RED)
    tb = text(s, ML + 0.32, 5.48, cw - 0.64,
              "THE ASK:  a three-week pilot on Union Bank's own historical data.",
              size=21, bold=True, color=WHITE, spacing=1.06)
    need("ask", tb, 6.30)

    text(s, W - MR - 4.4, 5.34, 4.4,
         ["Union Bank of India × iDEA 2.0", "PSB Hackathon Winner",
          "Global Fintech Festival '26"],
         size=18, color=RGBColor(0x8F, 0xA8, 0xC4), align=PP_ALIGN.RIGHT,
         spacing=1.25)
    notes(s, "0:15 — Detection finds the signal. Investigation finds the story. And feedback "
             "makes the whole system smarter every time someone uses it. TraceX turns a "
             "flood of alerts into a trail no launderer can hide from. Our ask is simple: "
             "three weeks, on your own historical data. Thank you.\n\n"
             "Then STOP. Hold eye contact. Silence reads as confidence; trailing off does not.")


# --------------------------------------------------------------------- appendix

def a1_architecture(prs):
    s = blank(prs)
    header(s, "Appendix A1 — not presented", "Five layers. One audited database.")
    layers = [
        ("INVESTIGATOR WORKSPACE",
         "Triage view, case-scoped graph explorer, deep investigation, STR generation", NAVY),
        ("API GATEWAY",
         "Authentication and role-based access enforced on every route module — not most, every one",
         NAVY2),
        ("SERVICES",
         "Detection (6 typologies + dual ML) · Investigation (case lifecycle) · AI Orchestration",
         RGBColor(0x24, 0x5E, 0x93)),
        ("PLATFORM",
         "Event log, health probes, audit chain, model governance, PII egress gate",
         RGBColor(0x36, 0x74, 0xAB)),
        ("DATA",
         "One audited store — SQLite for pilot, PostgreSQL for production, one repository interface",
         RGBColor(0x4C, 0x8C, 0xC3)),
    ]
    y, lh = TOP, 0.80
    for t, b, c in layers:
        card(s, ML, y, CW, lh, fill=c)
        text(s, ML + 0.34, y + 0.10, 5.0, t, size=20, bold=True, color=WHITE)
        tb = text(s, ML + 0.34, y + 0.46, CW - 0.68, b, size=18,
                  color=RGBColor(0xD3, 0xE2, 0xF0))
        need(t, tb, y + lh)
        y += lh + 0.10
    card(s, ML, y + 0.06, CW, 0.52, fill=BAND)
    text(s, ML, y + 0.16, CW,
         "The AI layer is the only one that leaves the boundary — through a "
         "fail-closed PII gate.", size=19, bold=True, color=NAVY,
         align=PP_ALIGN.CENTER, limit=y + 0.58)
    notes(s, "BACKUP ONLY. Pull up if asked 'walk me through how it's actually built.'")


def a2_detection(prs):
    s = blank(prs)
    header(s, "Appendix A2 — not presented", "Six typologies. Two models. One graph.")
    types = [
        ("LAYERING", "Multi-hop chains that break the trail"),
        ("ROUND-TRIPPING", "Circular flows returning funds to origin"),
        ("STRUCTURING", "Transactions kept below the ₹10L threshold"),
        ("DORMANCY", "Long-dormant accounts suddenly reactivated"),
        ("PROFILE MISMATCH", "Behaviour inconsistent with declared income"),
        ("MULE NETWORKS", "Fan-out / fan-in intermediary patterns"),
    ]
    cw, ch = (CW - 0.52) / 3, 1.28
    for i, (t, b) in enumerate(types):
        x = ML + (i % 3) * (cw + 0.26)
        y = TOP + (i // 3) * (ch + 0.14)
        card(s, x, y, cw, ch)
        text(s, x + 0.26, y + 0.16, cw - 0.52, t, size=19, bold=True, color=RED)
        tb = text(s, x + 0.26, y + 0.54, cw - 0.52, b, size=18, color=MUTED,
                  spacing=1.04)
        need(t, tb, y + ch - 0.04)

    y2, bh = 4.74, 1.62
    bw = (CW - 0.30) / 2
    for i, (t, items) in enumerate([
        ("WHY TWO ML MODELS", [
            "Isolation Forest — unsupervised from day one",
            "XGBoost — sharper once real verdicts exist"]),
        ("ENSEMBLED, NEVER SOLO", [
            "Flagged when rules, graph and ML converge",
            "No single model's blind spot sinks the score"]),
    ]):
        x = ML + i * (bw + 0.30)
        card(s, x, y2, bw, bh, fill=BAND)
        text(s, x + 0.30, y2 + 0.20, bw - 0.60, t, size=19, bold=True, color=NAVY)
        tb = bullets(s, x + 0.30, y2 + 0.62, bw - 0.60, items, size=18)
        need(t, tb, y2 + bh - 0.08)
    notes(s, "BACKUP ONLY. Pull up if asked 'what exactly does it detect, and how.'")


def a3_regulatory(prs):
    s = blank(prs)
    header(s, "Appendix A3 — not presented", "Every obligation, mapped to a control.")
    cols = [(ML + 0.24, 3.00), (ML + 3.46, 3.00), (ML + 6.76, 5.20)]
    rows = [
        ("REGULATION", "OBLIGATION", "HOW TRACEX MEETS IT"),
        ("DPDP 2023 §7 / §17", "Legal ground for AML",
         "No consent flow; purpose limits in code"),
        ("DPDP 2023 §8(5)", "Security safeguards",
         "Tokenisation, RBAC, hardened containers, audit"),
        ("DPDP 2023 §8(7)", "Erasure vs. legal retention",
         "PMLA's 5-year mandate governs retention"),
        ("DPDP 2023 §8(6)", "Breach notification duty",
         "Audit chain shows what was accessed, by whom"),
        ("PMLA 2002 §12", "5-year record retention",
         "Transactions, cases, STRs and audit log"),
        ("RBI KYC Master Direction", "KYC and dormant accounts",
         "Dormancy detector; 5-year retention"),
        ("FATF Recs. 10 & 20", "CDD and STR reporting",
         "Six detectors; FIU-IND report structure"),
    ]
    y, rh = TOP, 0.53
    for i, cells in enumerate(rows):
        head = i == 0
        card(s, ML, y, CW, rh, fill=NAVY if head else (CARD if i % 2 else WHITE))
        for (cx, cwid), cell in zip(cols, cells):
            assert nlines(cell, cwid, 18, head) == 1, f"A3 cell wraps: {cell!r}"
            tb = text(s, cx, y + 0.12, cwid, cell, size=18, bold=head,
                      color=WHITE if head else (NAVY if cell is cells[0] else INK))
            need(cell[:24], tb, y + rh)
        y += rh + 0.05
    text(s, ML, y + 0.06, CW,
         "Prototype pending formal compliance sign-off — the STR schema and these "
         "mappings need officer review.", size=18, italic=True, color=MUTED,
         limit=BOT)
    notes(s, "BACKUP ONLY. Pull up if asked 'show me the compliance mapping.' Say the "
             "caveat line out loud rather than being caught on it.")


def a4_economics(prs):
    s = blank(prs)
    header(s, "Appendix A4 — not presented",
           "Economics, market — and what isn't finished.")
    bw, bh = (CW - 0.30) / 2, 2.30
    for i, (t, items) in enumerate([
        ("UNIT ECONOMICS", [
            "Variable cost is almost entirely AI inference",
            "~$0.07–$0.10 per recommendation call, measured",
            "₹1.2 Cr contract, ~2,000 cases/mo ≈ 96% margin",
            "Self-hosting the model zeroes inference cost"]),
        ("MARKET BUILD-UP", [
            "Bottom-up: 309 Indian institutions, 3 tiers",
            "₹114.5 Cr serviceable annual revenue in India",
            "India RegTech ~$606 M in 2025, ~16% a year",
            "Precedent: Clari5 → Perfios, Feb 2025"]),
    ]):
        x = ML + i * (bw + 0.30)
        card(s, x, TOP, bw, bh)
        text(s, x + 0.30, TOP + 0.22, bw - 0.60, t, size=20, bold=True, color=RED)
        tb = bullets(s, x + 0.30, TOP + 0.66, bw - 0.60, items, size=18)
        need(t, tb, TOP + bh - 0.08)

    y2, gh = 4.40, 2.44
    card(s, ML, y2, CW, gh, fill=BAND)
    text(s, ML + 0.30, y2 + 0.20, CW - 0.60,
         "WHAT IS GENUINELY NOT FINISHED — say this before you're asked", size=19,
         bold=True, color=NAVY)
    tb = bullets(s, ML + 0.30, y2 + 0.64, CW - 0.60, [
        "The retention-purge job and legal-hold flagging are designed and documented, "
        "but not built — nothing auto-deletes yet",
        "PostgreSQL and Neo4j exist as adapter boundaries in code; the implementations "
        "are the funded next step",
        "External security review and compliance sign-off on the STR format are "
        "required before real accounts",
    ], size=18, hang=0.30)
    need("gaps", tb, y2 + gh - 0.08)
    notes(s, "BACKUP ONLY. Pull up if asked about margins, market size, or 'what's not "
             "done.' The bottom panel is deliberate: volunteering the gaps buys more "
             "credibility than defending them does.")


# ---------------------------------------------------------------------- assembly

def build(out: Path, video: Path | None) -> Path:
    prs = new_deck()
    s01_cover(prs)
    s02_problem(prs)
    s03_loop(prs)
    s04_journey(prs)
    s05_demo(prs, video)
    s06_network(prs)
    s07_trust(prs)
    s08_security(prs)
    s09_scale(prs)
    s10_proof(prs)
    s11_business(prs)
    s12_close(prs)
    a1_architecture(prs)
    a2_detection(prs)
    a3_regulatory(prs)
    a4_economics(prs)
    out.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(out))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--video", type=Path, default=None,
                    help="demo .mp4 to embed into slide 5")
    ap.add_argument("--out", type=Path,
                    default=Path(__file__).parent / "TraceX_GFF26.pptx")
    args = ap.parse_args()
    print(f"wrote {build(args.out, args.video)}")
    if not args.video:
        print("note: slide 5 holds a placeholder frame — rerun with "
              "--video path/to/demo.mp4, or embed it by hand in PowerPoint.")


if __name__ == "__main__":
    main()
