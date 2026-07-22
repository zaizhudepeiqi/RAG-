from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from app.bootstrap.application import create_app
from app.core.config import Settings
from app.infrastructure.database.models.models import ModelDiscoveredCandidateModel
from app.infrastructure.database.models.tasks import (
    AdminApiIdempotencyRecordModel,
    OperationModel,
    TaskOutboxModel,
)
from app.infrastructure.database.repositories.models import SqlAlchemyProviderTaskStore
from app.infrastructure.database.session import create_session_factory
from app.modules.models.adapters import DiscoveredModel
from app.modules.models.tasks import MODEL_PROVIDER_DISCOVERY_TASK
from redis import Redis
from sqlalchemy import Engine, func, select, text, update
from starlette.testclient import TestClient

pytestmark = pytest.mark.integration

INITIAL_CREDENTIAL = "Initial-Admin-Password-01!"
CURRENT_CREDENTIAL = "Current-Admin-Password-02!"


def make_settings(tmp_path: Path, database_url: str) -> Settings:
    return Settings(
        app_env="test",
        database_url=database_url,
        redis_url="redis://127.0.0.1:6379/15",
        storage_root=tmp_path / "storage",
        jwt_signing_key="j" * 48,
        credential_encryption_key="Y2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2M=",
        initial_admin_password=INITIAL_CREDENTIAL,
    )


@pytest.fixture
def operations_client(
    tmp_path: Path,
    migrated_database_url: str,
    database_engine: Engine,
) -> Iterator[tuple[TestClient, Engine]]:
    with database_engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE audit_logs, api_idempotency_records, task_outbox, operations, "
                "model_providers, administrators CASCADE"
            )
        )
    redis_client = Redis.from_url("redis://127.0.0.1:6379/15")
    redis_client.flushdb()
    redis_client.close()

    with TestClient(create_app(make_settings(tmp_path, migrated_database_url))) as client:
        logged_in = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": INITIAL_CREDENTIAL},
        )
        changed = client.post(
            "/api/v1/auth/change-password",
            headers={"X-CSRF-Token": logged_in.json()["csrfToken"]},
            json={
                "oldPassword": INITIAL_CREDENTIAL,
                "newPassword": CURRENT_CREDENTIAL,
                "confirmPassword": CURRENT_CREDENTIAL,
            },
        )
        assert changed.status_code == 200
        yield client, database_engine


def create_provider(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/api/v1/model-providers",
        headers={"X-CSRF-Token": client.cookies.get("rag_csrf") or ""},
        json={
            "providerType": "openai",
            "displayName": "Operation Provider",
            "baseUrl": "https://8.8.8.8/v1",
            "credential": "operation-test-credential-1234",
        },
    )
    assert response.status_code == 201
    return response.json()


def operation_headers(client: TestClient, key: str) -> dict[str, str]:
    return {
        "X-CSRF-Token": client.cookies.get("rag_csrf") or "",
        "Idempotency-Key": key,
    }


def test_test_and_discovery_create_operation_outbox_and_idempotency_atomically(
    operations_client: tuple[TestClient, Engine],
) -> None:
    client, engine = operations_client
    provider = create_provider(client)
    provider_id = provider["id"]

    tested = client.post(
        f"/api/v1/model-providers/{provider_id}:test",
        headers=operation_headers(client, "provider-test-command-0001"),
        json={"expectedRevision": 1},
    )
    repeated = client.post(
        f"/api/v1/model-providers/{provider_id}:test",
        headers=operation_headers(client, "provider-test-command-0001"),
        json={"expectedRevision": 1},
    )
    reused = client.post(
        f"/api/v1/model-providers/{provider_id}:test",
        headers=operation_headers(client, "provider-test-command-0001"),
        json={"expectedRevision": 2},
    )
    discovered = client.post(
        f"/api/v1/model-providers/{provider_id}:discover-models",
        headers=operation_headers(client, "provider-discovery-command-0001"),
        json={"expectedRevision": 1},
    )

    assert tested.status_code == repeated.status_code == discovered.status_code == 202
    assert tested.json()["operationId"] == repeated.json()["operationId"]
    assert tested.json()["targetType"] == "model_provider"
    assert tested.json()["targetId"] == provider_id
    assert reused.status_code == 409
    assert reused.json()["code"] == "IDEMPOTENCY_KEY_REUSED"

    with engine.connect() as connection:
        operation_count = connection.scalar(select(func.count()).select_from(OperationModel))
        outbox = connection.execute(
            select(
                TaskOutboxModel.event_type,
                TaskOutboxModel.schema_version,
                TaskOutboxModel.payload,
            ).order_by(TaskOutboxModel.event_type)
        ).all()
        idempotency_count = connection.scalar(
            select(func.count()).select_from(AdminApiIdempotencyRecordModel)
        )
    assert operation_count == 2
    assert idempotency_count == 2
    assert [(item.event_type, item.schema_version) for item in outbox] == [
        ("model.provider.discovery.requested", "1"),
        ("model.provider.test.requested", "1"),
    ]
    assert all(
        item.payload == {"providerId": provider_id, "providerRevision": 1} for item in outbox
    )
    assert not any(
        forbidden in str([item.payload for item in outbox]).lower()
        for forbidden in ("credential", "token", "ciphertext", "nonce")
    )


def test_dispatch_registry_contains_provider_maintenance_tasks(
    operations_client: tuple[TestClient, Engine],
) -> None:
    client, _engine = operations_client
    registry = client.app.state.dependencies.task_dispatch_registry

    test_definition = registry.resolve("model.provider.test.requested", "1")
    discovery_definition = registry.resolve("model.provider.discovery.requested", "1")

    assert test_definition.celery_task_name == "app.tasks.maintenance.test_model_provider"
    assert discovery_definition.celery_task_name == (
        "app.tasks.maintenance.discover_provider_models"
    )
    assert test_definition.queue == discovery_definition.queue == "maintenance"


def test_discovered_models_returns_latest_safe_candidates_with_filters(
    operations_client: tuple[TestClient, Engine],
) -> None:
    client, engine = operations_client
    provider = create_provider(client)
    provider_id = UUID(str(provider["id"]))
    requested = client.post(
        f"/api/v1/model-providers/{provider_id}:discover-models",
        headers=operation_headers(client, "provider-discovery-command-0002"),
        json={"expectedRevision": 1},
    )
    operation_id = UUID(requested.json()["operationId"])
    model_id = uuid4()
    with engine.begin() as connection:
        connection.execute(
            update(OperationModel)
            .where(OperationModel.id == operation_id)
            .values(status="succeeded", finished_at=func.now(), result_summary={"count": 1})
        )
        connection.execute(
            text(
                """
                INSERT INTO model_discovered_candidates (
                    id, provider_id, discovery_operation_id, model_name,
                    suggested_types, provider_status, raw_metadata_summary
                ) VALUES (
                    :id, :provider_id, :operation_id, 'embedding-model-v1',
                    '["embedding"]'::jsonb, 'available',
                    '{"ownedBy": "provider", "rawPayload": "must-not-escape"}'::jsonb
                )
                """
            ),
            {"id": uuid4(), "provider_id": provider_id, "operation_id": operation_id},
        )
        connection.execute(
            text(
                """
                INSERT INTO model_configs (
                    id, provider_id, model_name, display_name, model_type, capability_version
                ) VALUES (
                    :id, :provider_id, 'embedding-model-v1', 'Embedding Model', 'embedding', '1'
                )
                """
            ),
            {"id": model_id, "provider_id": provider_id},
        )

    response = client.get(
        f"/api/v1/model-providers/{provider_id}/discovered-models",
        params={"modelType": "embedding", "status": "available"},
    )

    assert response.status_code == 200
    assert response.json() == [
        {
            "providerModelName": "embedding-model-v1",
            "suggestedDisplayName": "embedding-model-v1",
            "supportedModelTypes": ["embedding"],
            "alreadyConfiguredModelIds": [str(model_id)],
            "discoveryMetadata": {"ownedBy": "provider"},
        }
    ]
    assert "rawPayload" not in response.text
    assert "must-not-escape" not in response.text


def test_duplicate_discovery_persistence_upserts_one_candidate(
    operations_client: tuple[TestClient, Engine],
) -> None:
    client, engine = operations_client
    provider = create_provider(client)
    requested = client.post(
        f"/api/v1/model-providers/{provider['id']}:discover-models",
        headers=operation_headers(client, "provider-discovery-command-0003"),
        json={"expectedRevision": 1},
    )
    operation_id = UUID(requested.json()["operationId"])
    store = SqlAlchemyProviderTaskStore(create_session_factory(engine))
    snapshot = store.load(operation_id, MODEL_PROVIDER_DISCOVERY_TASK)
    assert snapshot is not None
    candidates = (
        DiscoveredModel(
            model_name="provider-model-v1",
            suggested_types=(),
            provider_status="available",
            metadata_summary={"ownedBy": "provider"},
        ),
    )

    assert store.save_discovered_candidates(snapshot, candidates, datetime.now(UTC)) is False
    assert store.save_discovered_candidates(snapshot, candidates, datetime.now(UTC)) is False

    with engine.connect() as connection:
        count = connection.scalar(
            select(func.count())
            .select_from(ModelDiscoveredCandidateModel)
            .where(ModelDiscoveredCandidateModel.discovery_operation_id == operation_id)
        )
    assert count == 1
