"""Unit tests for password hashing + JWT helpers."""

import pytest

from src.utils.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


@pytest.mark.unit
class TestPasswordHashing:
    def test_hash_then_verify_succeeds(self) -> None:
        hashed = hash_password("hunter2")
        assert verify_password("hunter2", hashed) is True

    def test_verify_wrong_password_returns_false(self) -> None:
        hashed = hash_password("hunter2")
        assert verify_password("wrong-password", hashed) is False

    def test_hash_is_not_plaintext(self) -> None:
        hashed = hash_password("hunter2")
        assert hashed != "hunter2"
        assert hashed.startswith("$2b$")

    def test_verify_returns_false_for_malformed_hash(self) -> None:
        assert verify_password("anything", "not-a-bcrypt-hash") is False

    def test_password_over_72_bytes_raises(self) -> None:
        with pytest.raises(ValueError):
            hash_password("a" * 73)

    def test_verify_password_over_72_bytes_returns_false(self) -> None:
        hashed = hash_password("short-pw")
        assert verify_password("a" * 73, hashed) is False


@pytest.mark.unit
class TestJWT:
    def test_access_token_roundtrip(self) -> None:
        token = create_access_token(subject="user-1", role="investor")
        payload = decode_token(token)
        assert payload["sub"] == "user-1"
        assert payload["role"] == "investor"
        assert payload["type"] == "access"

    def test_refresh_token_roundtrip(self) -> None:
        token = create_refresh_token(subject="user-1")
        payload = decode_token(token)
        assert payload["sub"] == "user-1"
        assert payload["type"] == "refresh"

    def test_decode_invalid_token_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            decode_token("not.a.valid.jwt")
