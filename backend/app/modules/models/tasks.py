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
    ProviderConnectionRequest,
)
from app.modules.models.domain import ModelProvider, provider_credential_aad
from app.modules.tasks.worker import NonRetryableTaskError, RetryableTaskError

MODEL_PROVIDER_TEST_TASK = "model_provider_test"
MODEL_PROVIDER_DISCOVERY_TASK = "model_provider_discovery"


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
        try:
            plaintext = decrypt_secret(
                EncryptedSecret(
                    ciphertext=provider.credential_ciphertext,
                    nonce=provider.credential_nonce,
                    key_version=provider.credential_key_version,
                ),
                self._encryption_key,
                associated_data=provider_credential_aad(provider.id),
            )
            return SecretStr(plaintext.decode("utf-8"))
        except (CredentialDecryptionError, UnicodeDecodeError) as error:
            raise NonRetryableTaskError("MODEL_AUTH_FAILED") from error


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


def _raise_task_error(error: ModelProviderError) -> NoReturn:
    if error.retryable:
        raise RetryableTaskError(error.code) from error
    raise NonRetryableTaskError(error.code) from error
