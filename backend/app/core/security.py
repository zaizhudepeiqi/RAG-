import os
import secrets
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import jwt
from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ADMIN_CLAIM_KIND = "admin"
JWT_ALGORITHM = "HS256"
WEAK_PASSWORDS = frozenset(
    {
        "12345678",
        "admin123",
        "change-me",
        "password",
        "password123",
    }
)

_password_hasher = PasswordHasher(type=Type.ID)


class PasswordPolicyError(ValueError):
    pass


class InvalidAdminTokenError(ValueError):
    pass


class CredentialDecryptionError(ValueError):
    pass


@dataclass(frozen=True)
class AdminTokenClaims:
    administrator_id: UUID
    auth_version: int
    jti: UUID
    issued_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class EncryptedSecret:
    ciphertext: bytes
    nonce: bytes
    key_version: str


def validate_admin_password(*, username: str, password: str) -> None:
    categories = (
        any(character.isupper() for character in password),
        any(character.islower() for character in password),
        any(character.isdigit() for character in password),
        any(not character.isascii() or not character.isalnum() for character in password),
    )
    invalid = (
        not 12 <= len(password) <= 128
        or sum(categories) < 3
        or password.casefold() == username.casefold()
        or password.casefold() in WEAK_PASSWORDS
    )
    if invalid:
        raise PasswordPolicyError("password does not meet the administrator security policy")


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password_hash: str, candidate: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, candidate)
    except (InvalidHashError, VerificationError):
        return False


def issue_admin_token(claims: AdminTokenClaims, signing_key: bytes) -> str:
    _validate_claim_times(claims.issued_at, claims.expires_at)
    if claims.auth_version < 1:
        raise ValueError("auth_version must be positive")

    payload = {
        "sub": str(claims.administrator_id),
        "jti": str(claims.jti),
        "iat": int(claims.issued_at.timestamp()),
        "exp": int(claims.expires_at.timestamp()),
        "tokenType": ADMIN_CLAIM_KIND,
        "ver": claims.auth_version,
    }
    return jwt.encode(payload, signing_key, algorithm=JWT_ALGORITHM)


def decode_admin_token(token: str, signing_key: bytes, now: datetime) -> AdminTokenClaims:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")

    try:
        payload = jwt.decode(
            token,
            signing_key,
            algorithms=[JWT_ALGORITHM],
            options={
                "require": ["sub", "jti", "iat", "exp", "tokenType", "ver"],
                "verify_exp": False,
                "verify_iat": False,
            },
        )
        auth_version = payload["ver"]
        issued_at_value = payload["iat"]
        expires_at_value = payload["exp"]
        if payload["tokenType"] != ADMIN_CLAIM_KIND:
            raise ValueError("unexpected token type")
        if isinstance(auth_version, bool) or not isinstance(auth_version, int) or auth_version < 1:
            raise ValueError("invalid auth version")
        if not _is_numeric_date(issued_at_value) or not _is_numeric_date(expires_at_value):
            raise ValueError("invalid token timestamp")

        issued_at = datetime.fromtimestamp(issued_at_value, tz=now.tzinfo)
        expires_at = datetime.fromtimestamp(expires_at_value, tz=now.tzinfo)
        _validate_claim_times(issued_at, expires_at)
        if issued_at > now or now >= expires_at:
            raise ValueError("token is outside its validity period")

        return AdminTokenClaims(
            administrator_id=UUID(payload["sub"]),
            auth_version=auth_version,
            jti=UUID(payload["jti"]),
            issued_at=issued_at,
            expires_at=expires_at,
        )
    except (jwt.PyJWTError, KeyError, TypeError, ValueError, OverflowError) as error:
        raise InvalidAdminTokenError("invalid admin token") from error


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def csrf_matches(cookie_value: str | None, header_value: str | None) -> bool:
    if not cookie_value or not header_value:
        return False
    return secrets.compare_digest(cookie_value, header_value)


def encrypt_secret(
    plaintext: bytes,
    key: bytes,
    *,
    associated_data: bytes,
    key_version: str,
) -> EncryptedSecret:
    _validate_encryption_key(key)
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, associated_data)
    return EncryptedSecret(ciphertext=ciphertext, nonce=nonce, key_version=key_version)


def decrypt_secret(
    value: EncryptedSecret,
    key: bytes,
    *,
    associated_data: bytes,
) -> bytes:
    try:
        _validate_encryption_key(key)
        if len(value.nonce) != 12:
            raise ValueError("invalid nonce length")
        return AESGCM(key).decrypt(value.nonce, value.ciphertext, associated_data)
    except Exception as error:
        raise CredentialDecryptionError("credential decryption failed") from error


def _validate_encryption_key(key: bytes) -> None:
    if len(key) != 32:
        raise ValueError("AES-256-GCM key must be exactly 32 bytes")


def _validate_claim_times(issued_at: datetime, expires_at: datetime) -> None:
    if (
        issued_at.tzinfo is None
        or issued_at.utcoffset() is None
        or expires_at.tzinfo is None
        or expires_at.utcoffset() is None
    ):
        raise ValueError("token timestamps must be timezone-aware")
    if expires_at <= issued_at:
        raise ValueError("token expiration must be after issue time")


def _is_numeric_date(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float))
