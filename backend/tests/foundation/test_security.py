"""
`foundation/security.py`: password hash/verify round trip and JWT
encode/decode round trip, tamper/expiry rejection.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from db.enums import UserRole
from foundation.config import Settings
from foundation.security import (
    TokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)

_SETTINGS = Settings(jwt_secret="test-secret", jwt_algorithm="HS256", jwt_expiry_minutes=60)


def test_hash_and_verify_password_round_trip() -> None:
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert verify_password("correct horse battery staple", hashed) is True


def test_verify_password_rejects_wrong_password() -> None:
    hashed = hash_password("correct horse battery staple")
    assert verify_password("wrong password", hashed) is False


def test_create_and_decode_access_token_round_trip() -> None:
    token = create_access_token(user_id="U1", role=UserRole.INVESTIGATOR, settings=_SETTINGS)
    payload = decode_access_token(token, settings=_SETTINGS)
    assert payload.sub == "U1"
    assert payload.role == UserRole.INVESTIGATOR
    assert payload.exp > payload.iat


def test_decode_access_token_rejects_tampered_token() -> None:
    # Flip a character in the middle of the token, not the last one: the
    # final base64url character of a 32-byte HS256 signature carries 2
    # discarded padding bits, so mutating only that character leaves the
    # decoded signature bytes unchanged for ~1 in 16 tokens (verified
    # empirically: flipping the last char failed to raise in ~6% of 500
    # trials) — a flaky test that intermittently didn't test anything. A
    # mid-token flip lands on a byte-aligned position and reliably changes
    # the decoded bytes (verified: 0/1000 false negatives).
    token = create_access_token(user_id="U1", role=UserRole.INVESTIGATOR, settings=_SETTINGS)
    mid = len(token) // 2
    tampered = token[:mid] + ("A" if token[mid] != "A" else "B") + token[mid + 1 :]
    with pytest.raises(TokenError):
        decode_access_token(tampered, settings=_SETTINGS)


def test_decode_access_token_rejects_expired_token() -> None:
    issued_at = datetime.now(UTC) - timedelta(hours=2)
    expired_settings = Settings(
        jwt_secret="test-secret", jwt_algorithm="HS256", jwt_expiry_minutes=1
    )
    token = create_access_token(
        user_id="U1", role=UserRole.INVESTIGATOR, settings=expired_settings, now=issued_at
    )
    with pytest.raises(TokenError):
        decode_access_token(token, settings=expired_settings)


def test_decode_access_token_rejects_wrong_secret() -> None:
    token = create_access_token(user_id="U1", role=UserRole.INVESTIGATOR, settings=_SETTINGS)
    other = Settings(jwt_secret="different-secret", jwt_algorithm="HS256")
    with pytest.raises(TokenError):
        decode_access_token(token, settings=other)


def test_decode_access_token_rejects_invalid_role_claim() -> None:
    # A token whose `role` claim isn't a real `UserRole` value (e.g. hand-
    # crafted/forged, or from a future/rolled-back schema) must be rejected
    # as a `TokenError`, not raise a bare `ValueError` from `UserRole(...)`
    # that callers wouldn't be catching.
    from jose import jwt as _jwt

    claims = {"sub": "U1", "role": "NOT_A_REAL_ROLE", "iat": 0, "exp": 9999999999}
    token = _jwt.encode(claims, _SETTINGS.jwt_secret, algorithm=_SETTINGS.jwt_algorithm)
    with pytest.raises(TokenError):
        decode_access_token(token, settings=_SETTINGS)
