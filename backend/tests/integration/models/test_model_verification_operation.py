from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import pytest
from app.bootstrap.application import create_app
from app.core.config import Settings
from app.infrastructure.database.models.models import (
    ModelConfigModel,
    ModelProviderModel,
    ModelVerificationModel,
)
from app.infrastructure.database.models.tasks import OperationModel, TaskOutboxModel
from app.infrastructure.database.repositories.models import SqlAlchemyModelVerificationTaskStore
from app.infrastructure.database.repositories.tasks import SqlAlchemyOperationExecutionStore
from app.infrastructure.database.session import create_session_factory
from app.infrastructure.model_providers.registry import ModelProviderAdapterRegistry
from app.modules.models.adapters import (
    DiscoveredModel,
    DiscoverModelsRequest,
    ModelVerificationRequest,
    ProviderConnectionRequest,
    ProviderConnectionResult,
    ProviderDescriptor,
    VerificationResult,
)
from app.modules.models.domain import ModelType
from app.modules.models.tasks import MODEL_VERIFICATION_TASK, ModelVerificationHandler
from app.modules.tasks.ports import OperationExecutionStore
from app.modules.tasks.worker import execute_operation
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
def verification_client(
    tmp_path: Path,
    migrated_database_url: str,
    database_engine: Engine,
) -> Iterator[tuple[TestClient, Engine, Settings]]:
    settings = make_settings(tmp_path, migrated_database_url)
    with database_engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE audit_logs, model_verifications, task_outbox, operations, "
                "model_providers, administrators CASCADE"
            )
        )
    redis_client = Redis.from_url("redis://127.0.0.1:6379/15")
    redis_client.flushdb()
    redis_client.close()

    with TestClient(create_app(settings)) as client:
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
        yield client, database_engine, settings


def csrf(client: TestClient, idempotency_key: str | None = None) -> dict[str, str]:
    headers = {"X-CSRF-Token": client.cookies.get("rag_csrf") or ""}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return headers


def create_model(client: TestClient) -> tuple[UUID, UUID]:
    provider = client.post(
        "/api/v1/model-providers",
        headers=csrf(client),
        json={
            "providerType": "openai",
            "displayName": "Verification Provider",
            "baseUrl": "https://8.8.8.8/v1",
            "credential": "sk-verification-secret-1234",
        },
    ).json()
    model = client.post(
        "/api/v1/models",
        headers=csrf(client),
        json={
            "providerId": provider["id"],
            "modelName": "gpt-verify-v1",
            "displayName": "GPT Verify",
            "modelType": "llm",
            "defaultParams": {},
        },
    ).json()
    return UUID(model["id"]), UUID(provider["id"])


class SuccessfulAdapter:
    descriptor = ProviderDescriptor(
        provider_type="openai",
        supported_model_types=frozenset({ModelType.LLM, ModelType.EMBEDDING, ModelType.VISION}),
        discovery_path="models",
        llm_path="chat/completions",
        embedding_path="embeddings",
        rerank_path=None,
        vision_path="chat/completions",
    )

    def __init__(self, on_verify=None) -> None:  # type: ignore[no-untyped-def]
        self.on_verify = on_verify
        self.calls = 0

    def test_provider(self, request: ProviderConnectionRequest) -> ProviderConnectionResult:
        raise AssertionError("not used")

    def discover_models(self, request: DiscoverModelsRequest) -> tuple[DiscoveredModel, ...]:
        raise AssertionError("not used")

    def verify_llm(self, request: ModelVerificationRequest) -> VerificationResult:
        self.calls += 1
        if self.on_verify is not None:
            self.on_verify()
        return VerificationResult(
            output_text="OK",
            provider_request_id="req-verification-001",
            usage_input_tokens=8,
            usage_output_tokens=1,
        )

    def verify_embedding(self, request: ModelVerificationRequest) -> VerificationResult:
        raise AssertionError("not used")

    def verify_rerank(self, request: ModelVerificationRequest) -> VerificationResult:
        raise AssertionError("not used")

    def verify_vision(self, request: ModelVerificationRequest) -> VerificationResult:
        raise AssertionError("not used")


@dataclass
class WorkerDependencies:
    operations: OperationExecutionStore


def handler(
    engine: Engine,
    settings: Settings,
    adapter: SuccessfulAdapter,
) -> ModelVerificationHandler:
    registry = ModelProviderAdapterRegistry()
    registry.register(adapter)
    return ModelVerificationHandler(
        SqlAlchemyModelVerificationTaskStore(create_session_factory(engine)),
        registry,
        settings.credential_encryption_key_bytes,
    )


def test_verify_operation_is_revision_idempotent_and_duplicate_delivery_has_one_history(
    verification_client: tuple[TestClient, Engine, Settings],
) -> None:
    client, engine, settings = verification_client
    model_id, provider_id = create_model(client)

    first = client.post(
        f"/api/v1/models/{model_id}:verify",
        headers=csrf(client, "model-verify-command-0001"),
        json={"expectedRevision": 1},
    )
    repeated = client.post(
        f"/api/v1/models/{model_id}:verify",
        headers=csrf(client, "model-verify-command-0002"),
        json={"expectedRevision": 1},
    )

    assert first.status_code == repeated.status_code == 202
    assert first.json()["operationId"] == repeated.json()["operationId"]
    operation_id = UUID(first.json()["operationId"])
    with engine.connect() as connection:
        outbox = connection.execute(
            select(TaskOutboxModel.event_type, TaskOutboxModel.payload).where(
                TaskOutboxModel.operation_id == operation_id
            )
        ).one()
    assert outbox.event_type == "model.verification.requested"
    assert outbox.payload == {
        "modelId": str(model_id),
        "modelRevision": 1,
        "providerRevision": 1,
        "credentialRevision": 1,
    }
    assert (
        client.app.state.dependencies.task_dispatch_registry.resolve(
            "model.verification.requested", "1"
        ).celery_task_name
        == "app.tasks.maintenance.verify_model"
    )

    adapter = SuccessfulAdapter()
    operations = SqlAlchemyOperationExecutionStore(create_session_factory(engine))
    dependencies = WorkerDependencies(operations)
    verification_handler = handler(engine, settings, adapter)
    execute_operation(operation_id, MODEL_VERIFICATION_TASK, verification_handler, dependencies)
    execute_operation(operation_id, MODEL_VERIFICATION_TASK, verification_handler, dependencies)

    with engine.connect() as connection:
        history_count = connection.scalar(select(func.count()).select_from(ModelVerificationModel))
        model_row = connection.execute(
            select(
                ModelConfigModel.verification_status,
                ModelConfigModel.embedding_dimension,
            ).where(ModelConfigModel.id == model_id)
        ).one()
        operation = connection.execute(
            select(OperationModel.status, OperationModel.result_summary).where(
                OperationModel.id == operation_id
            )
        ).one()
        summary = connection.scalar(
            select(ModelVerificationModel.response_summary).where(
                ModelVerificationModel.operation_id == operation_id
            )
        )
    assert adapter.calls == 1
    assert history_count == 1
    assert model_row.verification_status == "passed"
    assert model_row.embedding_dimension is None
    assert operation.status == "succeeded"
    assert operation.result_summary["stale"] is False
    assert set(summary) == {
        "modelType",
        "outputPresent",
        "embeddingDimension",
        "candidateCount",
        "usageInputTokens",
        "usageOutputTokens",
        "providerUsageReported",
    }
    assert "OK" not in str(summary)
    assert str(provider_id) not in str(summary)


def test_revision_change_during_verification_preserves_history_but_marks_model_stale(
    verification_client: tuple[TestClient, Engine, Settings],
) -> None:
    client, engine, settings = verification_client
    model_id, provider_id = create_model(client)
    requested = client.post(
        f"/api/v1/models/{model_id}:verify",
        headers=csrf(client, "model-verify-command-race-0001"),
        json={"expectedRevision": 1},
    )
    operation_id = UUID(requested.json()["operationId"])

    def rotate_provider_revision() -> None:
        with engine.begin() as connection:
            connection.execute(
                update(ModelProviderModel)
                .where(ModelProviderModel.id == provider_id)
                .values(revision=2, credential_revision=2)
            )

    adapter = SuccessfulAdapter(on_verify=rotate_provider_revision)
    execute_operation(
        operation_id,
        MODEL_VERIFICATION_TASK,
        handler(engine, settings, adapter),
        WorkerDependencies(SqlAlchemyOperationExecutionStore(create_session_factory(engine))),
    )

    with engine.connect() as connection:
        history = connection.execute(
            select(
                ModelVerificationModel.tested_provider_revision,
                ModelVerificationModel.tested_credential_revision,
                ModelVerificationModel.status,
            ).where(ModelVerificationModel.operation_id == operation_id)
        ).one()
        model_status = connection.scalar(
            select(ModelConfigModel.verification_status).where(ModelConfigModel.id == model_id)
        )
        result_summary = connection.scalar(
            select(OperationModel.result_summary).where(OperationModel.id == operation_id)
        )
    assert history == (1, 1, "succeeded")
    assert model_status == "stale"
    assert result_summary["stale"] is True
