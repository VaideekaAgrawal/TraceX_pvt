"""`foundation.hashing.hmac_sha256_hex` (ROADMAP Phase 8)."""
from __future__ import annotations

import pytest

from foundation.hashing import hmac_sha256_hex


def test_same_input_and_secret_produce_same_output() -> None:
    a = hmac_sha256_hex("ABC1234Z", secret="secret-1")
    b = hmac_sha256_hex("ABC1234Z", secret="secret-1")
    assert a == b


def test_different_secret_produces_different_output() -> None:
    a = hmac_sha256_hex("ABC1234Z", secret="secret-1")
    b = hmac_sha256_hex("ABC1234Z", secret="secret-2")
    assert a != b


def test_different_value_produces_different_output() -> None:
    a = hmac_sha256_hex("ABC1234Z", secret="secret-1")
    b = hmac_sha256_hex("XYZ9999A", secret="secret-1")
    assert a != b


def test_empty_secret_raises_value_error() -> None:
    with pytest.raises(ValueError, match="non-empty secret"):
        hmac_sha256_hex("ABC1234Z", secret="")


def test_output_is_hex_sha256_length() -> None:
    result = hmac_sha256_hex("value", secret="secret")
    assert len(result) == 64
    int(result, 16)  # raises ValueError if not valid hex
