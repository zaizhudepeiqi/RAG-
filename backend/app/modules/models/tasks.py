from dataclasses import dataclass
from datetime import UTC, datetime
from typing import NoReturn, Protocol
from uuid import UUID

from pydantic import SecretStr

from app.core.security import (
    CredentialDecryptionError,
    EncryptedSecret,
    decrypt_secret,
)
from app.modules.models.adapters import (
    DiscoveredModel,
    DiscoverModelsRequest,
    ModelProviderAdapterResolver,
    ModelProviderError,
    ModelVerificationRequest,
    ProviderConnectionRequest,
)
from app.modules.models.domain import ModelConfig, ModelProvider, ModelType, provider_credential_aad
from app.modules.models.verification import (
    ValidatedVerification,
    VerificationValidationError,
    validate_verification_result,
)
from app.modules.tasks.worker import NonRetryableTaskError, RetryableTaskError

MODEL_PROVIDER_TEST_TASK = "model_provider_test"
MODEL_PROVIDER_DISCOVERY_TASK = "model_provider_discovery"
MODEL_VERIFICATION_TASK = "model_verification"


@dataclass(frozen=True)
class ProviderTaskSnapshot:
    operation_id: UUID
    provider: ModelProvider


class ProviderTaskStore(Protocol):
    def load(
        self,
        operation_id: UUID,
        expected_task_type: str,
    ) -> ProviderTaskSnapshot | None: ...

    def provider_revision_matches(self, provider_id: UUID, revision: int) -> bool: ...

    def save_discovered_candidates(
        self,
        snapshot: ProviderTaskSnapshot,
        candidates: tuple[DiscoveredModel, ...],
        discovered_at: datetime,
    ) -> bool: ...


@dataclass(frozen=True)
class ModelVerificationTaskSnapshot:
    operation_id: UUID
    model: ModelConfig
    provider: ModelProvider


class ModelVerificationTaskStore(Protocol):
    def load(self, operation_id: UUID) -> ModelVerificationTaskSnapshot | None: ...

    def save_succeeded(
        self,
        snapshot: ModelVerificationTaskSnapshot,
        validated: ValidatedVerification,
        provider_request_id: str | None,
        latency_ms: int | None,
        tested_at: datetime,
    ) -> bool: ...

    def save_failed(
        self,
        snapshot: ModelVerificationTaskSnapshot,
        *,
        status: str,
        error_code: str,
        tested_at: datetime,
    ) -> bool: ...


class ProviderTestHandler:
    def __init__(
        self,
        store: ProviderTaskStore,
        adapters: ModelProviderAdapterResolver,
        encryption_key: bytes,
    ) -> None:
        self._store = store
        self._adapters = adapters
        self._encryption_key = encryption_key

    def run(self, operation_id: UUID) -> dict[str, object]:
        snapshot = self._required_snapshot(operation_id, MODEL_PROVIDER_TEST_TASK)
        adapter = self._adapters.get(snapshot.provider.provider_type)
        try:
            result = adapter.test_provider(request=self._connection_request(snapshot.provider))
        except ModelProviderError as error:
            _raise_task_error(error)
        return {
            "providerId": str(snapshot.provider.id),
            "modelCount": result.model_count,
            "latencyMs": result.latency_ms,
            "providerRequestId": result.provider_request_id,
            "stale": not self._store.provider_revision_matches(
                snapshot.provider.id,
                snapshot.provider.revision,
            ),
        }

    def _required_snapshot(
        self,
        operation_id: UUID,
        expected_task_type: str,
    ) -> ProviderTaskSnapshot:
        snapshot = self._store.load(operation_id, expected_task_type)
        if snapshot is None:
            raise NonRetryableTaskError("MODEL_PROVIDER_NOT_FOUND")
        return snapshot

    def _connection_request(self, provider: ModelProvider) -> ProviderConnectionRequest:
        return ProviderConnectionRequest(
            base_url=provider.base_url,
            credential=self._credential(provider),
        )

    def _credential(self, provider: ModelProvider) -> SecretStr:
        return _decrypt_provider_credential(provider, self._encryption_key)


class ProviderDiscoveryHandler(ProviderTestHandler):
    def run(self, operation_id: UUID) -> dict[str, object]:
        snapshot = self._required_snapshot(operation_id, MODEL_PROVIDER_DISCOVERY_TASK)
        adapter = self._adapters.get(snapshot.provider.provider_type)
        try:
            candidates = adapter.discover_models(
                DiscoverModelsRequest(
                    base_url=snapshot.provider.base_url,
                    credential=self._credential(snapshot.provider),
                )
            )
        except ModelProviderError as error:
            _raise_task_error(error)
        stale = self._store.save_discovered_candidates(
            snapshot,
            candidates,
            datetime.now(UTC),
        )
        return {
            "providerId": str(snapshot.provider.id),
            "candidateCount": len(candidates),
            "stale": stale,
        }


class ModelVerificationHandler:
    def __init__(
        self,
        store: ModelVerificationTaskStore,
        adapters: ModelProviderAdapterResolver,
        encryption_key: bytes,
    ) -> None:
        self._store = store
        self._adapters = adapters
        self._encryption_key = encryption_key

    def run(self, operation_id: UUID) -> dict[str, object]:
        snapshot = self._store.load(operation_id)
        if snapshot is None:
            raise NonRetryableTaskError("MODEL_NOT_FOUND")
        adapter = self._adapters.require(
            snapshot.provider.provider_type,
            snapshot.model.model_type,
        )
        request = ModelVerificationRequest(
            base_url=snapshot.provider.base_url,
            credential=_decrypt_provider_credential(
                snapshot.provider,
                self._encryption_key,
            ),
            model_name=snapshot.model.model_name,
            model_type=snapshot.model.model_type,
            default_params=snapshot.model.default_params,
        )
        tested_at = datetime.now(UTC)
        try:
            result = {
                ModelType.LLM: adapter.verify_llm,
                ModelType.EMBEDDING: adapter.verify_embedding,
                ModelType.RERANK: adapter.verify_rerank,
                ModelType.VISION: adapter.verify_vision,
            }[snapshot.model.model_type](request)
            validated = validate_verification_result(
                snapshot.model.model_type,
                result,
                existing_embedding_dimension=snapshot.model.embedding_dimension,
            )
        except ModelProviderError as error:
            self._store.save_failed(
                snapshot,
                status="timeout" if error.code == "MODEL_TIMEOUT" else "failed",
                error_code=error.code,
                tested_at=tested_at,
            )
            _raise_task_error(error)
        except VerificationValidationError as error:
            self._store.save_failed(
                snapshot,
                status="failed",
                error_code=error.code,
                tested_at=tested_at,
            )
            raise NonRetryableTaskError(error.code) from error
        stale = self._store.save_succeeded(
            snapshot,
            validated,
            result.provider_request_id,
            result.latency_ms,
            tested_at,
        )
        return {
            **validated.response_summary,
            "providerRequestId": result.provider_request_id,
            "stale": stale,
        }


def _raise_task_error(error: ModelProviderError) -> NoReturn:
    if error.retryable:
        raise RetryableTaskError(error.code) from error
    raise NonRetryableTaskError(error.code) from error


def _decrypt_provider_credential(provider: ModelProvider, encryption_key: bytes) -> SecretStr:
    try:
        plaintext = decrypt_secret(
            EncryptedSecret(
                ciphertext=provider.credential_ciphertext,
                nonce=provider.credential_nonce,
                key_version=provider.credential_key_version,
            ),
            encryption_key,
            associated_data=provider_credential_aad(provider.id),
        )
        return SecretStr(plaintext.decode("utf-8"))
    except (CredentialDecryptionError, UnicodeDecodeError) as error:
        raise NonRetryableTaskError("MODEL_AUTH_FAILED") from error
