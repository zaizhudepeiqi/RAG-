from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.infrastructure.database.repositories.models import SqlAlchemyModelProviderRepository
from app.infrastructure.database.session import create_session_factory, transaction
from app.modules.models.domain import ModelProvider, ModelType, VerificationStatus
from app.modules.models.repository import ModelProviderListQuery
from sqlalchemy import Engine, text


@pytest.fixture(autouse=True)
def empty_model_tables(database_engine: Engine) -> None:
    with database_engine.begin() as connection:
        connection.execute(text("TRUNCATE model_providers CASCADE"))


def provider(display_name: str = "Primary OpenAI") -> ModelProvider:
    now = datetime.now(UTC)
    return ModelProvider(
        id=uuid4(),
        provider_type="openai",
        display_name=display_name,
        base_url="https://8.8.8.8/v1",
        supported_model_types=(ModelType.LLM, ModelType.EMBEDDING, ModelType.VISION),
        credential_ciphertext=b"encrypted-secret",
        credential_nonce=b"123456789012",
        credential_key_version="v1",
        credential_prefix="sk-p...1234",
        credential_revision=1,
        enabled=True,
        revision=1,
        created_at=now,
        updated_at=now,
        deleted_at=None,
        model_count=0,
    )


@pytest.mark.integration
def test_repository_maps_provider_and_lists_with_model_count(database_engine: Engine) -> None:
    repository = SqlAlchemyModelProviderRepository()
    session_factory = create_session_factory(database_engine)
    stored = provider()

    with transaction(session_factory) as session:
        repository.add(session, stored)
    with database_engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO model_configs (
                    id, provider_id, model_name, display_name, model_type, capability_version
                ) VALUES (:id, :provider_id, 'gpt-test', 'GPT Test', 'llm', '1')
                """
            ),
            {"id": uuid4(), "provider_id": stored.id},
        )
    with transaction(session_factory) as session:
        loaded = repository.get(session, stored.id)
        page = repository.list(
            session,
            ModelProviderListQuery(
                search="primary",
                enabled=True,
                page=1,
                page_size=20,
                sort="display_name",
            ),
        )

    assert loaded is not None
    assert loaded.id == stored.id
    assert loaded.supported_model_types == stored.supported_model_types
    assert loaded.model_count == 1
    assert page.items == [loaded]
    assert page.total == 1
    assert page.page == 1
    assert page.page_size == 20


@pytest.mark.integration
def test_repository_locks_updates_and_stales_provider_models(database_engine: Engine) -> None:
    repository = SqlAlchemyModelProviderRepository()
    session_factory = create_session_factory(database_engine)
    stored = provider()
    with transaction(session_factory) as session:
        repository.add(session, stored)
    with database_engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO model_configs (
                    id, provider_id, model_name, display_name, model_type,
                    verification_status, capability_version
                ) VALUES (:id, :provider_id, 'gpt-test', 'GPT Test', 'llm', 'passed', '1')
                """
            ),
            {"id": uuid4(), "provider_id": stored.id},
        )

    now = datetime.now(UTC)
    with transaction(session_factory) as session:
        locked = repository.get(session, stored.id, for_update=True)
        assert locked is not None
        locked.credential_ciphertext = b"rotated-secret"
        locked.credential_nonce = b"abcdefghijkl"
        locked.credential_prefix = "sk-r...9876"
        locked.credential_revision = 2
        locked.revision = 2
        locked.updated_at = now
        repository.save(session, locked)
        repository.mark_models_stale(session, stored.id)

    with database_engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT credential_revision, revision FROM model_providers WHERE id = :provider_id
                """
            ),
            {"provider_id": stored.id},
        ).one()
        status = connection.scalar(
            text("SELECT verification_status FROM model_configs WHERE provider_id = :provider_id"),
            {"provider_id": stored.id},
        )
    assert row.credential_revision == 2
    assert row.revision == 2
    assert status == VerificationStatus.STALE.value
