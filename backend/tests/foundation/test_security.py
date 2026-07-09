"""
`foundation/security.py`: password hash/verify round trip and JWT
encode/decode round trip, tamper/expiry rejection.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

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
    token = create_access_token(user_id="U1", role="INVESTIGATOR", settings=_SETTINGS)
    payload = decode_access_token(token, settings=_SETTINGS)
    assert payload.sub == "U1"
    assert payload.role == "INVESTIGATOR"
    assert payload.exp > payload.iat


def test_decode_access_token_rejects_tampered_token() -> None:
    token = create_access_token(user_id="U1", role="INVESTIGATOR", settings=_SETTINGS)
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    with pytest.raises(TokenError):
        decode_access_token(tampered, settings=_SETTINGS)


def test_decode_access_token_rejects_expired_token() -> None:
    issued_at = datetime.now(UTC) - timedelta(hours=2)
    expired_settings = Settings(
        jwt_secret="test-secret", jwt_algorithm="HS256", jwt_expiry_minutes=1
    )
    token = create_access_token(
        user_id="U1", role="INVESTIGATOR", settings=expired_settings, now=issued_at
    )
    with pytest.raises(TokenError):
        decode_access_token(token, settings=expired_settings)


def test_decode_access_token_rejects_wrong_secret() -> None:
    token = create_access_token(user_id="U1", role="INVESTIGATOR", settings=_SETTINGS)
    other = Settings(jwt_secret="different-secret", jwt_algorithm="HS256")
    with pytest.raises(TokenError):
        decode_access_token(token, settings=other)
