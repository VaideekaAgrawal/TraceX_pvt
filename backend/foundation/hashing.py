"""
HMAC helper (ROADMAP Phase 8) -- the fix for `investigation.
relationship_discovery`'s previously-unsalted `hashlib.sha256(value)` hash
of low-entropy PII (PAN, income bracket, branch city). An unsalted hash of a
low-entropy value is brute-forceable if the DB ever leaks (10-character
alphanumeric PAN space is small enough to rainbow-table); keying the hash
with an application secret (`Settings.pii_hmac_secret`) makes that
infeasible without also compromising the secret.

Deliberately generic (not relationship-discovery-specific) so any future
PII-hashing need in this codebase has one place to call instead of a second
ad-hoc `hashlib.sha256(...)`.
"""
from __future__ import annotations

import hashlib
import hmac


def hmac_sha256_hex(value: str, *, secret: str) -> str:
    """HMAC-SHA256 of `value` keyed by `secret`, hex-encoded. Raises
    `ValueError` if `secret` is empty -- an HMAC with an empty key degrades
    toward the exact unsalted-hash weakness this function exists to fix, so
    silently allowing it would defeat the point."""
    if not secret:
        raise ValueError("hmac_sha256_hex requires a non-empty secret")
    return hmac.new(secret.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()
