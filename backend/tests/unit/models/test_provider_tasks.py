from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from app.core.security import encrypt_secret
from app.infrastructure.model_providers.registry import ModelProviderAdapterRegistry
from app.modules.models.adapters import (
    DiscoveredModel,
    DiscoverModelsRequest,
    ModelProviderError,
    ModelVerificationRequest,
    ProviderConnectionRequest,
    ProviderConnectionResult,
    ProviderDescriptor,
    VerificationResult,
)
from app.modules.models.domain import ModelProvider, ModelType, provider_credential_aad
from app.modules.models.tasks import (
    MODEL_PROVIDER_DISCOVERY_TASK,
    MODEL_PROVIDER_TEST_TASK,
    ProviderDiscoveryHandler,
    ProviderTaskSnapshot,
    ProviderTestHandler,
)
from app.modules.tasks.ports import ClaimKind, OperationClaim
from app.modules.tasks.worker import RetryableTaskError, execute_operation

KEY = b"k" * 32
CREDENTIAL = "provider-task-secret"


class FakeAdapter:
    descriptor = ProviderDescriptor(
        provider_type="test_provider",
        supported_model_types=frozenset(ModelType),
        discovery_path="models",
        llm_path="chat/completions",
        embedding_path="embeddings",
        rerank_path="rerank",
        vision_path="chat/completions",
    )

    def __init__(self, store: "FakeStore", *, error: ModelProviderError | None = None) -> None:
        self.store = store
        self.error = error
        self.test_calls = 0
        self.discovery_calls = 0

    def test_provider(self, request: ProviderConnectionRequest) -> ProviderConnectionResult:
        self.test_calls += 1
        assert request.credential.get_secret_value() == CREDENTIAL
        if self.error is not None:
            raise self.error
        return ProviderConnectionResult(
            model_count=2,
            latency_ms=12,
            provider_request_id="req-provider-test",
        )

    def discover_models(self, request: DiscoverModelsRequest) -> tuple[DiscoveredModel, ...]:
        self.discovery_calls += 1
        assert request.credential.get_secret_value() == CREDENTIAL
        self.store.current_revision += 1
        return (
            DiscoveredModel(
                model_name="provider-model-v1",
                suggested_types=(),
                provider_status="available",
                metadata_summary={"ownedBy": "provider"},
            ),
        )

    def verify_llm(self, request: ModelVerificationRequest) -> VerificationResult:
        raise AssertionError("not used")

    def verify_embedding(self, request: ModelVerificationRequest) -> VerificationResult:
        raise AssertionError("not used")

    def verify_rerank(self, request: ModelVerificationRequest) -> VerificationResult:
        raise AssertionError("not used")

    def verify_vision(self, request: ModelVerificationRequest) -> VerificationResult:
        raise AssertionError("not used")


class FakeStore:
    def __init__(self, snapshot: ProviderTaskSnapshot) -> None:
        self.snapshot = snapshot
        self.current_revision = snapshot.provider.revision
        self.saved_candidates: tuple[DiscoveredModel, ...] = ()

    def load(self, operation_id: UUID, expected_task_type: str) -> ProviderTaskSnapshot:
        assert operation_id == self.snapshot.operation_id
        assert expected_task_type in {MODEL_PROVIDER_TEST_TASK, MODEL_PROVIDER_DISCOVERY_TASK}
        return self.snapshot

    def provider_revision_matches(self, provider_id: UUID, revision: int) -> bool:
        assert provider_id == self.snapshot.provider.id
        return self.current_revision == revision

    def save_discovered_candidates(
        self,
        snapshot: ProviderTaskSnapshot,
        candidates: tuple[DiscoveredModel, ...],
        discovered_at: datetime,
    ) -> bool:
        assert snapshot == self.snapshot
        assert discovered_at.tzinfo is not None
        self.saved_candidates = candidates
        return self.current_revision != snapshot.provider.revision


class Operations:
    def __init__(self) -> None:
        self.claimed = False
        self.completed: list[dict[str, object]] = []
        self.failed: list[tuple[str, bool]] = []

    def claim(self, operation_id: UUID, expected_task_type: str) -> OperationClaim:
        if self.claimed:
            return OperationClaim(ClaimKind.TERMINAL, operation_id)
        self.claimed = True
        return OperationClaim(ClaimKind.CLAIMED, operation_id)

    def complete(self, operation_id: UUID, result: dict[str, object]) -> None:
        self.completed.append(result)

    def fail(self, operation_id: UUID, code: str, *, retryable: bool) -> None:
        self.failed.append((code, retryable))


@dataclass
class WorkerDependencies:
    operations: Operations


def snapshot() -> ProviderTaskSnapshot:
    provider_id = uuid4()
    encrypted = encrypt_secret(
        CREDENTIAL.encode(),
        KEY,
        associated_data=provider_credential_aad(provider_id),
        key_version="v1",
    )
    now = datetime.now(UTC)
    return ProviderTaskSnapshot(
        operation_id=uuid4(),
        provider=ModelProvider(
            id=provider_id,
            provider_type="test_provider",
            display_name="Task Provider",
            base_url="https://8.8.8.8/v1",
            supported_model_types=tuple(ModelType),
            credential_ciphertext=encrypted.ciphertext,
            credential_nonce=encrypted.nonce,
            credential_key_version=encrypted.key_version,
            credential_prefix="prov...cret",
            credential_revision=1,
            enabled=True,
            revision=1,
            created_at=now,
            updated_at=now,
            deleted_at=None,
            model_count=0,
        ),
    )


def adapter_registry(adapter: FakeAdapter) -> ModelProviderAdapterRegistry:
    registry = ModelProviderAdapterRegistry()
    registry.register(adapter)
    return registry


def test_duplicate_provider_test_delivery_calls_adapter_once() -> None:
    task_snapshot = snapshot()
    store = FakeStore(task_snapshot)
    adapter = FakeAdapter(store)
    handler = ProviderTestHandler(store, adapter_registry(adapter), KEY)
    operations = Operations()
    dependencies = WorkerDependencies(operations)

    execute_operation(
        task_snapshot.operation_id,
        MODEL_PROVIDER_TEST_TASK,
        handler,
        dependencies,
    )
    execute_operation(
        task_snapshot.operation_id,
        MODEL_PROVIDER_TEST_TASK,
        handler,
        dependencies,
    )

    assert adapter.test_calls == 1
    assert operations.completed == [
        {
            "providerId": str(task_snapshot.provider.id),
            "modelCount": 2,
            "latencyMs": 12,
            "providerRequestId": "req-provider-test",
            "stale": False,
        }
    ]


def test_discovery_saves_one_candidate_and_marks_revision_race_stale() -> None:
    task_snapshot = snapshot()
    store = FakeStore(task_snapshot)
    adapter = FakeAdapter(store)
    handler = ProviderDiscoveryHandler(store, adapter_registry(adapter), KEY)
    operations = Operations()

    execute_operation(
        task_snapshot.operation_id,
        MODEL_PROVIDER_DISCOVERY_TASK,
        handler,
        WorkerDependencies(operations),
    )

    assert adapter.discovery_calls == 1
    assert [item.model_name for item in store.saved_candidates] == ["provider-model-v1"]
    assert operations.completed == [
        {
            "providerId": str(task_snapshot.provider.id),
            "candidateCount": 1,
            "stale": True,
        }
    ]


def test_retryable_adapter_error_becomes_retryable_task_error() -> None:
    task_snapshot = snapshot()
    store = FakeStore(task_snapshot)
    adapter = FakeAdapter(
        store,
        error=ModelProviderError("MODEL_RATE_LIMITED", retryable=True),
    )
    handler = ProviderTestHandler(store, adapter_registry(adapter), KEY)

    with pytest.raises(RetryableTaskError) as captured:
        handler.run(task_snapshot.operation_id)

    assert captured.value.code == "MODEL_RATE_LIMITED"
