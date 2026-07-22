from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import IntegrityError


def insert_provider(
    connection: Connection,
    *,
    provider_id: UUID | None = None,
    display_name: str = "Primary OpenAI",
    credential_revision: int = 1,
    revision: int = 1,
) -> UUID:
    provider_id = provider_id or uuid4()
    connection.execute(
        text(
            """
            INSERT INTO model_providers (
                id, provider_type, display_name, base_url, supported_model_types,
                credential_ciphertext, credential_nonce, credential_key_version,
                credential_prefix, credential_revision, revision
            )
            VALUES (
                :id, 'openai', :display_name, 'https://api.openai.com/v1',
                '["llm", "embedding", "vision"]'::jsonb,
                :ciphertext, :nonce, 'v1', 'sk-test', :credential_revision,
                :revision
            )
            """
        ),
        {
            "id": provider_id,
            "display_name": display_name,
            "ciphertext": b"ciphertext",
            "nonce": b"123456789012",
            "credential_revision": credential_revision,
            "revision": revision,
        },
    )
    return provider_id


def insert_model(
    connection: Connection,
    *,
    provider_id: UUID,
    model_id: UUID | None = None,
    model_name: str = "text-embedding-3-small",
    model_type: str = "embedding",
    verification_status: str = "untested",
    embedding_dimension: int | None = 1536,
    revision: int = 1,
) -> UUID:
    model_id = model_id or uuid4()
    connection.execute(
        text(
            """
            INSERT INTO model_configs (
                id, provider_id, model_name, display_name, model_type,
                verification_status, embedding_dimension, capability_version
                , revision
            )
            VALUES (
                :id, :provider_id, :model_name, :model_name, :model_type,
                :verification_status, :embedding_dimension, '1', :revision
            )
            """
        ),
        {
            "id": model_id,
            "provider_id": provider_id,
            "model_name": model_name,
            "model_type": model_type,
            "verification_status": verification_status,
            "embedding_dimension": embedding_dimension,
            "revision": revision,
        },
    )
    return model_id


@pytest.mark.integration
def test_model_provider_display_name_is_unique_case_insensitively(
    database_engine: Engine,
) -> None:
    with pytest.raises(IntegrityError):
        with database_engine.begin() as connection:
            insert_provider(connection, display_name="Enterprise Models")
            insert_provider(connection, display_name="enterprise models")


@pytest.mark.integration
def test_model_identity_is_unique_within_provider(database_engine: Engine) -> None:
    with pytest.raises(IntegrityError):
        with database_engine.begin() as connection:
            provider_id = insert_provider(connection)
            insert_model(connection, provider_id=provider_id)
            insert_model(connection, provider_id=provider_id)


@pytest.mark.integration
@pytest.mark.parametrize(
    ("model_type", "verification_status"),
    [("audio", "untested"), ("llm", "unknown")],
)
def test_model_rejects_unknown_type_or_verification_status(
    database_engine: Engine,
    model_type: str,
    verification_status: str,
) -> None:
    with pytest.raises(IntegrityError):
        with database_engine.begin() as connection:
            provider_id = insert_provider(connection)
            insert_model(
                connection,
                provider_id=provider_id,
                model_type=model_type,
                verification_status=verification_status,
                embedding_dimension=None,
            )


@pytest.mark.integration
def test_provider_rejects_nonpositive_credential_revision(database_engine: Engine) -> None:
    with pytest.raises(IntegrityError):
        with database_engine.begin() as connection:
            insert_provider(connection, credential_revision=0)


@pytest.mark.integration
def test_provider_and_model_reject_nonpositive_revision(database_engine: Engine) -> None:
    with pytest.raises(IntegrityError):
        with database_engine.begin() as connection:
            insert_provider(connection, revision=0)

    with pytest.raises(IntegrityError):
        with database_engine.begin() as connection:
            provider_id = insert_provider(connection)
            insert_model(connection, provider_id=provider_id, revision=0)


@pytest.mark.integration
def test_model_rejects_nonpositive_embedding_dimension(database_engine: Engine) -> None:
    with pytest.raises(IntegrityError):
        with database_engine.begin() as connection:
            provider_id = insert_provider(connection)
            insert_model(connection, provider_id=provider_id, embedding_dimension=0)


@pytest.mark.integration
def test_verification_rejects_negative_latency(database_engine: Engine) -> None:
    with pytest.raises(IntegrityError):
        with database_engine.begin() as connection:
            provider_id = insert_provider(connection)
            model_id = insert_model(connection, provider_id=provider_id)
            operation_id = uuid4()
            connection.execute(
                text(
                    """
                    INSERT INTO operations (
                        id, task_type, target_type, target_id,
                        business_idempotency_key, expires_at
                    )
                    VALUES (
                        :id, 'model_verification', 'model', :model_id,
                        :business_key, :expires_at
                    )
                    """
                ),
                {
                    "id": operation_id,
                    "model_id": model_id,
                    "business_key": uuid4().hex * 2,
                    "expires_at": datetime.now(UTC) + timedelta(days=90),
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO model_verifications (
                        id, model_id, operation_id, tested_model_revision,
                        tested_provider_revision, tested_credential_revision,
                        status, latency_ms, tested_at
                    )
                    VALUES (
                        :id, :model_id, :operation_id, 1, 1, 1,
                        'failed', -1, now()
                    )
                    """
                ),
                {"id": uuid4(), "model_id": model_id, "operation_id": operation_id},
            )


@pytest.mark.integration
def test_mineru_settings_reject_poll_timeout_outside_range(database_engine: Engine) -> None:
    with pytest.raises(IntegrityError):
        with database_engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO mineru_settings (
                        id, base_url, default_parse_config, poll_timeout_seconds
                    )
                    VALUES (
                        :id, 'https://mineru.net', '{}'::jsonb, 299
                    )
                    """
                ),
                {"id": uuid4()},
            )


@pytest.mark.integration
def test_mineru_settings_rejects_nonpositive_revision(database_engine: Engine) -> None:
    with pytest.raises(IntegrityError):
        with database_engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO mineru_settings (
                        id, base_url, default_parse_config,
                        poll_timeout_seconds, revision
                    )
                    VALUES (
                        :id, 'https://mineru.net', '{}'::jsonb, 1800, 0
                    )
                    """
                ),
                {"id": uuid4()},
            )
