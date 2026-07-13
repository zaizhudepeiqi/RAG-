from pathlib import Path

import pytest
from app.bootstrap.dependencies import build_application_dependencies
from app.core.config import Settings
from app.core.security import verify_password
from sqlalchemy import Engine, text


def make_settings(tmp_path: Path, database_url: str, *, initial_password: str) -> Settings:
    return Settings(
        app_env="test",
        database_url=database_url,
        redis_url="redis://127.0.0.1:6379/15",
        storage_root=tmp_path / "storage",
        jwt_signing_key="j" * 48,
        credential_encryption_key="Y2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2M=",
        initial_admin_username="admin",
        initial_admin_password=initial_password,
    )


@pytest.fixture(autouse=True)
def empty_auth_tables(database_engine: Engine) -> None:
    with database_engine.begin() as connection:
        connection.execute(
            text("TRUNCATE audit_logs, api_idempotency_records, administrators CASCADE")
        )


@pytest.mark.integration
def test_bootstrap_creates_one_admin_only_when_table_is_empty(
    tmp_path: Path,
    migrated_database_url: str,
    database_engine: Engine,
) -> None:
    dependencies = build_application_dependencies(
        make_settings(
            tmp_path,
            migrated_database_url,
            initial_password="Initial-Admin-Password-01!",
        )
    )
    try:
        created = dependencies.auth_service.bootstrap_administrator()

        with database_engine.connect() as connection:
            row = connection.execute(
                text("SELECT username, password_hash, first_login_required FROM administrators")
            ).one()
        assert created is True
        assert row.username == "admin"
        assert row.password_hash.startswith("$argon2id$")
        assert "Initial-Admin-Password-01!" not in row.password_hash
        assert row.first_login_required is True
    finally:
        dependencies.close()


@pytest.mark.integration
def test_second_bootstrap_never_overwrites_existing_password(
    tmp_path: Path,
    migrated_database_url: str,
    database_engine: Engine,
) -> None:
    first = build_application_dependencies(
        make_settings(
            tmp_path,
            migrated_database_url,
            initial_password="Initial-Admin-Password-01!",
        )
    )
    second = build_application_dependencies(
        make_settings(
            tmp_path,
            migrated_database_url,
            initial_password="Different-Admin-Password-02!",
        )
    )
    try:
        assert first.auth_service.bootstrap_administrator() is True
        assert second.auth_service.bootstrap_administrator() is False

        with database_engine.connect() as connection:
            hashes = connection.scalars(text("SELECT password_hash FROM administrators")).all()
        assert len(hashes) == 1
        assert verify_password(hashes[0], "Initial-Admin-Password-01!") is True
        assert verify_password(hashes[0], "Different-Admin-Password-02!") is False
    finally:
        first.close()
        second.close()
