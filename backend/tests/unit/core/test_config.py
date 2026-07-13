import base64
from pathlib import Path

import pytest
from app.core.config import Settings
from pydantic import ValidationError


def settings_values(tmp_path: Path) -> dict[str, object]:
    return {
        "app_env": "test",
        "database_url": "postgresql+psycopg://test:test@127.0.0.1:5432/rag_test",
        "redis_url": "redis://127.0.0.1:6379/15",
        "storage_root": tmp_path / "storage",
        "jwt_signing_key": "j" * 32,
        "credential_encryption_key": base64.b64encode(b"c" * 32).decode(),
        "initial_admin_username": "admin",
        "initial_admin_password": "Initial-Admin-Password-01!",
    }


def test_settings_decode_keys_and_resolve_storage_without_creating_it(tmp_path: Path) -> None:
    settings = Settings(**settings_values(tmp_path))

    assert settings.jwt_signing_key_bytes == b"j" * 32
    assert settings.credential_encryption_key_bytes == b"c" * 32
    assert settings.storage_root == (tmp_path / "storage").resolve()
    assert not settings.storage_root.exists()


def test_production_rejects_weak_initial_password(tmp_path: Path) -> None:
    values = settings_values(tmp_path)
    values.update(app_env="production", initial_admin_password="admin123")

    with pytest.raises(ValidationError, match="initial administrator password"):
        Settings(**values)


@pytest.mark.parametrize(
    "encoded_key",
    ["not-base64", base64.b64encode(b"short").decode()],
)
def test_settings_reject_invalid_credential_encryption_key(
    tmp_path: Path, encoded_key: str
) -> None:
    values = settings_values(tmp_path)
    values["credential_encryption_key"] = encoded_key

    with pytest.raises(ValidationError, match="credential encryption key"):
        Settings(**values)


def test_settings_reject_key_reuse(tmp_path: Path) -> None:
    values = settings_values(tmp_path)
    values["credential_encryption_key"] = base64.b64encode(b"j" * 32).decode()

    with pytest.raises(ValidationError, match="must be different"):
        Settings(**values)


def test_secret_values_are_masked_in_repr(tmp_path: Path) -> None:
    settings = Settings(**settings_values(tmp_path))
    rendered = repr(settings)

    assert "j" * 32 not in rendered
    assert base64.b64encode(b"c" * 32).decode() not in rendered
