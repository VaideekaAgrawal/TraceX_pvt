"""
Demo identifier safety — ROADMAP Phase 8, committed decision 11.

Every synthetic identifier this project generates must be **structurally
impossible** as a real one, not merely unlikely. The distinction is the whole
point: "unlikely to collide" is a probability, and a probability is not a defence
you can offer a bank when a generated value turns out to be a real customer's tax
identifier.

Two of the four generators were defective (Session 13's audit):

- `_synthetic_pan` emitted the **exact** real PAN layout — and PAN carries **no
  checksum**, so any string of that shape is a syntactically valid PAN. Nothing
  but luck stood between a demo value and a real person's.
- `_synthetic_phone` emitted a real, dialable Indian mobile format.

Both now lead with a character the real format forbids. This is also what makes
the PII egress gate's format detector safe to run fail-closed
(`orchestration/redaction.py`): demo data cannot trip it.
"""
from __future__ import annotations

import random
import re

from demo_data.kyc_customers import (
    _synthetic_aadhaar,
    _synthetic_email,
    _synthetic_pan,
    _synthetic_phone,
)

#: The real formats. A generated value matching any of these is a defect.
REAL_PAN = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
REAL_AADHAAR = re.compile(r"^[2-9][0-9]{11}$")  # real Aadhaar never starts 0 or 1
REAL_INDIAN_MOBILE = re.compile(r"^[6-9][0-9]{9}$")  # real mobiles start 6-9

_SAMPLE = range(500)


def test_no_generated_pan_is_a_syntactically_valid_pan() -> None:
    # PAN has NO checksum. Format validity is the only bar, so matching the format
    # IS colliding with the space of real PANs. Shipping these from an AML
    # compliance product is indefensible in exactly the room this is pitched to.
    rng = random.Random(1234)
    offenders = [p for i in _SAMPLE if REAL_PAN.match(p := _synthetic_pan(rng, i))]
    assert not offenders, f"generated syntactically-valid PANs: {offenders[:3]}"


def test_no_generated_phone_is_a_dialable_indian_mobile() -> None:
    offenders = [p for i in _SAMPLE if REAL_INDIAN_MOBILE.match(p := _synthetic_phone(i))]
    assert not offenders, f"generated real-format mobile numbers: {offenders[:3]}"


def test_no_generated_aadhaar_is_a_structurally_valid_aadhaar() -> None:
    # Already safe before Phase 8 (leading `1`); asserted so it stays that way.
    offenders = [a for i in _SAMPLE if REAL_AADHAAR.match(a := _synthetic_aadhaar(i))]
    assert not offenders, f"generated real-format Aadhaars: {offenders[:3]}"


def test_emails_use_a_tld_that_can_never_resolve() -> None:
    # `.invalid` is IANA-reserved. Already safe; asserted so it stays that way.
    assert all(_synthetic_email(i).endswith(".invalid") for i in _SAMPLE)


def test_identifier_lengths_are_preserved_for_the_ui() -> None:
    # Being structurally impossible must not mean being visibly wrong: the demo is
    # a pitch asset (decision 11), and a PAN field showing 9 characters would read
    # as a bug on stage. The Relationship Explorer matches on EQUALITY, so the
    # format itself is functionally irrelevant to every feature consuming these.
    rng = random.Random(1234)
    assert len(_synthetic_pan(rng, 1)) == 10
    assert len(_synthetic_phone(1)) == 10
    assert len(_synthetic_aadhaar(1)) == 12
