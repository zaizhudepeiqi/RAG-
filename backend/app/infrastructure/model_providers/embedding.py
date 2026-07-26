from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy.orm import Session, sessionmaker

from app.core.security import CredentialDecryptionError, EncryptedSecret, decrypt_secret
from app.infrastructure.database.session import transaction
from app.modules.models.adapters import (
    EmbeddingRequest,
    ModelProviderAdapterResolver,
    ModelProviderError,
)
from app.modules.models.domain import ModelType, SelectableModel, provider_credential_aad
from app.modules.models.embeddings import validate_embedding_result
from app.modules.models.service import ModelSelectionService

EMBEDDING_BATCH_SIZE = 128


class ConfiguredDocumentEmbedder:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        selection: ModelSelectionService,
        adapters: ModelProviderAdapterResolver,
        encryption_key: bytes,
    ) -> None:
        self._session_factory = session_factory
        self._selection = selection
        self._adapters = adapters
        self._encryption_key = encryption_key

    def embed_documents(
        self,
        *,
        model_id: UUID,
        model_snapshot: dict[str, object],
        params: dict[str, object],
        texts: Sequence[str],
        expected_dimension: int,
    ) -> tuple[tuple[float, ...], ...]:
        if not texts:
            return ()
        selected = self._select(model_id, model_snapshot)
        adapter = self._adapters.require(selected.provider.provider_type, ModelType.EMBEDDING)
        credential = self._credential(selected)
        merged_params = {**selected.model.default_params, **params}
        vectors: list[tuple[float, ...]] = []
        for start in range(0, len(texts), EMBEDDING_BATCH_SIZE):
            batch = tuple(texts[start : start + EMBEDDING_BATCH_SIZE])
            result = adapter.embed(
                EmbeddingRequest(
                    base_url=selected.provider.base_url,
                    credential=credential,
                    model_name=selected.model.model_name,
                    texts=batch,
                    purpose="document",
                    params=merged_params,
                )
            )
            vectors.extend(
                validate_embedding_result(
                    result,
                    expected_count=len(batch),
                    expected_dimension=expected_dimension,
                )
            )
        return tuple(vectors)

    def embed_query(
        self,
        query: str,
        *,
        model_id: UUID,
        model_snapshot: dict[str, object],
        params: dict[str, object],
        expected_dimension: int,
    ) -> tuple[float, ...]:
        selected = self._select(model_id, model_snapshot)
        adapter = self._adapters.require(selected.provider.provider_type, ModelType.EMBEDDING)
        result = adapter.embed(
            EmbeddingRequest(
                base_url=selected.provider.base_url,
                credential=self._credential(selected),
                model_name=selected.model.model_name,
                texts=(query,),
                purpose="query",
                params={**selected.model.default_params, **params},
            )
        )
        vectors = validate_embedding_result(
            result,
            expected_count=1,
            expected_dimension=expected_dimension,
        )
        return vectors[0]

    def _select(self, model_id: UUID, model_snapshot: dict[str, object]) -> SelectableModel:
        with transaction(self._session_factory) as session:
            selected = self._selection.require_selectable(session, model_id, ModelType.EMBEDDING)
        expected = {
            "modelId": str(selected.model.id),
            "modelName": selected.model.model_name,
            "modelRevision": selected.model.revision,
            "providerId": str(selected.provider.id),
            "providerType": selected.provider.provider_type,
            "providerRevision": selected.provider.revision,
            "credentialRevision": selected.provider.credential_revision,
            "embeddingDimension": selected.model.embedding_dimension,
        }
        if any(model_snapshot.get(key) != value for key, value in expected.items()):
            raise ModelProviderError("MODEL_SNAPSHOT_STALE", retryable=False)
        return selected

    def _credential(self, selected: SelectableModel) -> SecretStr:
        provider = selected.provider
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
            raise ModelProviderError("MODEL_AUTH_FAILED", retryable=False) from error
