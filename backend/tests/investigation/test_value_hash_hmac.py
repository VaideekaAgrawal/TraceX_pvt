"""
`Relationship.value_hash` HMAC tests — ROADMAP Phase 8, committed decision 9.
Resolves the item Session 11 deferred.

The property: a leaked `relationships` table must not be reversible back to the
PII it was derived from. A bare SHA256 does not give that, because the inputs are
low-entropy — a PAN is ten characters in a known layout, an Aadhaar twelve digits
— and an attacker can enumerate the space offline and match the digests. Keying
the hash with a secret that the database does not contain is what makes the
digests useless to whoever steals the table.
"""
from __future__ import annotations

import hashlib

import pytest

from investigation.relationship_discovery import _value_hash

PAN = "ABCPK9081L"


def test_hash_is_keyed_not_a_bare_sha256() -> None:
    # The regression that matters: if someone reverts to `hashlib.sha256(value)`,
    # this fails. That digest is what an attacker precomputes.
    bare_sha256 = hashlib.sha256(PAN.encode()).hexdigest()
    assert _value_hash(PAN, hmac_key="secret-key") != bare_sha256


def test_a_different_key_produces_a_different_hash() -> None:
    # This is the whole security property: the digest depends on a secret the
    # database does not hold, so the table alone cannot be brute-forced.
    a = _value_hash(PAN, hmac_key="key-one")
    b = _value_hash(PAN, hmac_key="key-two")
    assert a != b


def test_same_key_and_value_is_stable() -> None:
    # Equality-matching still has to work: two customers sharing a PAN must
    # produce the same hash, or the Relationship Explorer stops finding anything.
    assert _value_hash(PAN, hmac_key="k") == _value_hash(PAN, hmac_key="k")


def test_an_empty_key_is_refused_rather_than_silently_unkeyed() -> None:
    # Fail closed. Degrading to an unkeyed digest would reintroduce exactly the
    # bug this replaces, and it would be INVISIBLE in the data — a brute-forceable
    # hash looks identical to a safe one. A loud failure is the only way this can
    # be wrong and still be noticed.
    with pytest.raises(ValueError, match="pii_hmac_key is not set"):
        _value_hash(PAN, hmac_key="")
