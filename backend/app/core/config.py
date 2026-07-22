import base64
import binascii
from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,
        case_sensitive=False,
        extra="forbid",
        frozen=True,
    )

    app_env: Literal["development", "test", "production"]
    app_version: str = "0.1.0"
    api_base_url: str = "http://127.0.0.1:8001"
    frontend_origin: str = "http://127.0.0.1:5173"

    database_url: str
    redis_url: str
    chroma_host: str = "127.0.0.1"
    chroma_port: int = Field(default=8000, ge=1, le=65535)
    storage_root: Path

    jwt_signing_key: SecretStr
    credential_encryption_key: SecretStr
    initial_admin_username: str = "admin"
    initial_admin_password: SecretStr
    access_token_expire_minutes: int = Field(default=10080, ge=1)

    parsing_worker_concurrency: int = Field(default=2, ge=1)
    indexing_worker_concurrency: int = Field(default=2, ge=1)
    chat_worker_concurrency: int = Field(default=4, ge=1)
    mineru_poll_timeout_seconds: int = Field(default=1800, ge=1)

    chat_trace_retention_days: int = Field(default=30, ge=1)
    conversation_retention_days: int = Field(default=30, ge=1)
    operation_retention_days: int = Field(default=90, ge=1)
    audit_retention_days: int = Field(default=180, ge=1)
    temp_attachment_retention_hours: int = Field(default=24, ge=1)

    allow_local_provider_http: bool = False
    allow_private_callbacks: bool = False
    enable_production_openapi: bool = False

    @field_validator("storage_root")
    @classmethod
    def resolve_storage_root(cls, value: Path) -> Path:
        return value.expanduser().resolve()

    @model_validator(mode="after")
    def validate_secrets(self) -> Self:
        jwt_key = self.jwt_signing_key_bytes
        credential_key = self.credential_encryption_key_bytes

        if self.app_env == "production" and len(jwt_key) < 32:
            raise ValueError("JWT signing key must contain at least 32 bytes in production")
        if jwt_key == credential_key:
            raise ValueError("JWT signing key and credential encryption key must be different")
        if self.app_env == "production":
            self._validate_initial_password()
        return self

    @property
    def jwt_signing_key_bytes(self) -> bytes:
        return self.jwt_signing_key.get_secret_value().encode("utf-8")

    @property
    def credential_encryption_key_bytes(self) -> bytes:
        encoded = self.credential_encryption_key.get_secret_value()
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as error:
            raise ValueError("credential encryption key must be valid Base64 encoding") from error
        if len(decoded) != 32:
            raise ValueError("credential encryption key must decode to exactly 32 bytes")
        return decoded

    def _validate_initial_password(self) -> None:
        password = self.initial_admin_password.get_secret_value()
        weak_values = {"admin123", "change-me", "password", "password123", "12345678"}
        categories = (
            any(character.isupper() for character in password),
            any(character.islower() for character in password),
            any(character.isdigit() for character in password),
            any(not character.isalnum() for character in password),
        )
        invalid = (
            not 12 <= len(password) <= 128
            or sum(categories) < 3
            or password.casefold() == self.initial_admin_username.casefold()
            or password.casefold() in weak_values
        )
        if invalid:
            raise ValueError("initial administrator password does not meet the security policy")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
