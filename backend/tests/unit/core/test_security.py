from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from app.core.security import (
    AdminTokenClaims,
    CredentialDecryptionError,
    InvalidAdminTokenError,
    PasswordPolicyError,
    csrf_matches,
    decode_admin_token,
    decrypt_secret,
    encrypt_secret,
    generate_csrf_token,
    hash_password,
    issue_admin_token,
    validate_admin_password,
    verify_password,
)
from cryptography.exceptions import InvalidTag

SIGNING_KEY = b"unit-test-signing-key-that-is-not-a-secret-and-has-64-byte-length!!"
ENCRYPTION_KEY = b"a" * 32


def token_payload(
    *,
    now: datetime,
    token_type: str | None = None,
    auth_version: object = 1,
) -> dict[str, object]:
    return {
        "sub": str(uuid4()),
        "jti": str(uuid4()),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "tokenType": token_type or "admin",
        "ver": auth_version,
    }


def test_password_hash_uses_argon2id_and_never_contains_plaintext() -> None:
    plaintext = "Correct-Horse-42"

    password_hash = hash_password(plaintext)

    assert password_hash.startswith("$argon2id$")
    assert plaintext not in password_hash
    assert verify_password(password_hash, plaintext) is True
    assert verify_password(password_hash, "wrong-password") is False
    assert verify_password("not-an-argon-hash", plaintext) is False


@pytest.mark.parametrize(
    ("username", "password"),
    [
        ("admin", "Short-1"),
        ("admin", "A" * 129 + "1!"),
        ("admin", "onlylowercase-and-symbol"),
        ("Same-User-42!", "same-user-42!"),
        ("admin", "password123"),
    ],
)
def test_password_policy_requires_12_to_128_chars_and_three_categories(
    username: str,
    password: str,
) -> None:
    with pytest.raises(PasswordPolicyError):
        validate_admin_password(username=username, password=password)


def test_password_policy_accepts_non_ascii_as_the_fourth_category() -> None:
    validate_admin_password(username="admin", password="enterprise-知识库-42")


def test_admin_token_round_trip_preserves_fixed_claims() -> None:
    now = datetime(2026, 7, 14, 8, 0, tzinfo=UTC)
    claims = AdminTokenClaims(
        administrator_id=uuid4(),
        auth_version=3,
        jti=uuid4(),
        issued_at=now,
        expires_at=now + timedelta(minutes=30),
    )

    token = issue_admin_token(claims, SIGNING_KEY)

    assert decode_admin_token(token, SIGNING_KEY, now) == claims


def test_admin_token_rejects_wrong_algorithm_token_type_and_auth_version() -> None:
    now = datetime(2026, 7, 14, 8, 0, tzinfo=UTC)
    invalid_tokens = [
        jwt.encode(token_payload(now=now), SIGNING_KEY, algorithm="HS384"),
        jwt.encode(token_payload(now=now, token_type="channel"), SIGNING_KEY, algorithm="HS256"),
        jwt.encode(token_payload(now=now, auth_version=0), SIGNING_KEY, algorithm="HS256"),
    ]

    for token in invalid_tokens:
        with pytest.raises(InvalidAdminTokenError):
            decode_admin_token(token, SIGNING_KEY, now)


def test_admin_token_rejects_expired_token() -> None:
    issued_at = datetime(2026, 7, 14, 8, 0, tzinfo=UTC)
    token = jwt.encode(
        token_payload(now=issued_at),
        SIGNING_KEY,
        algorithm="HS256",
    )

    with pytest.raises(InvalidAdminTokenError):
        decode_admin_token(token, SIGNING_KEY, issued_at + timedelta(minutes=5))


def test_csrf_comparison_is_constant_time_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    compared: list[tuple[str, str]] = []

    def compare_digest(left: str, right: str) -> bool:
        compared.append((left, right))
        return left == right

    monkeypatch.setattr("app.core.security.secrets.compare_digest", compare_digest)

    assert csrf_matches("csrf-token", "csrf-token") is True
    assert compared == [("csrf-token", "csrf-token")]
    assert csrf_matches(None, "csrf-token") is False


def test_generated_csrf_token_has_256_bits_of_urlsafe_entropy() -> None:
    first = generate_csrf_token()
    second = generate_csrf_token()

    assert len(first) >= 43
    assert first != second


def test_aes_gcm_rejects_wrong_associated_data() -> None:
    encrypted = encrypt_secret(
        b"test-secret",
        ENCRYPTION_KEY,
        associated_data=b"provider:one",
        key_version="v1",
    )

    with pytest.raises(CredentialDecryptionError) as error:
        decrypt_secret(
            encrypted,
            ENCRYPTION_KEY,
            associated_data=b"provider:two",
        )

    assert str(error.value) == "credential decryption failed"
    assert isinstance(error.value.__cause__, InvalidTag)


def test_encryption_never_reuses_nonce() -> None:
    first = encrypt_secret(
        b"test-secret",
        ENCRYPTION_KEY,
        associated_data=b"provider:one",
        key_version="v1",
    )
    second = encrypt_secret(
        b"test-secret",
        ENCRYPTION_KEY,
        associated_data=b"provider:one",
        key_version="v1",
    )

    assert len(first.nonce) == 12
    assert first.nonce != second.nonce
    assert first.ciphertext != second.ciphertext
    assert decrypt_secret(first, ENCRYPTION_KEY, associated_data=b"provider:one") == b"test-secret"


def test_aes_256_gcm_requires_exactly_32_byte_key() -> None:
    with pytest.raises(ValueError, match="exactly 32 bytes"):
        encrypt_secret(
            b"test-secret",
            b"short-key",
            associated_data=b"provider:one",
            key_version="v1",
        )
