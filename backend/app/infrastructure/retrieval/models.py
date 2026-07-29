from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from app.core.security import CredentialDecryptionError, EncryptedSecret, decrypt_secret
from app.infrastructure.model_providers.embedding import ConfiguredDocumentEmbedder
from app.modules.knowledge_bases.domain import BuildConfigRevision
from app.modules.models.adapters import (
    ModelProviderAdapterResolver,
    ModelProviderError,
    RerankRequest,
    TextGenerationRequest,
)
from app.modules.models.domain import ModelType, SelectableModel, provider_credential_aad
from app.modules.models.service import ModelSelectionService
from app.modules.retrieval.fusion import RetrievalCandidate
from app.modules.retrieval.reranking import RerankScore
from pydantic import SecretStr
from sqlalchemy.orm import Session, sessionmaker


@dataclass(frozen=True)
class BoundQueryEmbedder:
    embedder: ConfiguredDocumentEmbedder
    build_revision: BuildConfigRevision

    def embed_query(self, query: str) -> tuple[float, ...]:
        dimension = self.build_revision.embedding_model_snapshot.get("embeddingDimension")
        if isinstance(dimension, bool) or not isinstance(dimension, int) or dimension <= 0:
            raise ModelProviderError("MODEL_SNAPSHOT_STALE", retryable=False)
        return self.embedder.embed_query(
            query,
            model_id=self.build_revision.config.embedding_model_id,
            model_snapshot=self.build_revision.embedding_model_snapshot,
            params=self.build_revision.config.embedding_params,
            expected_dimension=dimension,
        )


class ConfiguredTextGenerator:
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

    def generate(
        self,
        model_id: UUID,
        prompt: str,
        *,
        max_tokens: int,
        temperature: float,
    ) -> str:
        selected = self._select(model_id, ModelType.LLM)
        adapter = self._adapters.require(selected.provider.provider_type, ModelType.LLM)
        result = adapter.generate_text(
            TextGenerationRequest(
                base_url=selected.provider.base_url,
                credential=self._credential(selected),
                model_name=selected.model.model_name,
                prompt=prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                params=selected.model.default_params,
            )
        )
        if not result.text.strip():
            raise ModelProviderError("MODEL_RESPONSE_INVALID", retryable=False)
        return result.text

    def rerank(
        self,
        model_id: UUID,
        query: str,
        documents: tuple[str, ...],
        *,
        params: Mapping[str, object],
    ) -> tuple[tuple[int, ...], tuple[float, ...]]:
        selected = self._select(model_id, ModelType.RERANK)
        adapter = self._adapters.require(selected.provider.provider_type, ModelType.RERANK)
        result = adapter.rerank(
            RerankRequest(
                base_url=selected.provider.base_url,
                credential=self._credential(selected),
                model_name=selected.model.model_name,
                query=query,
                documents=documents,
                params={**selected.model.default_params, **params},
            )
        )
        return result.indices, result.scores

    def _select(self, model_id: UUID, model_type: ModelType) -> SelectableModel:
        with self._session_factory() as session:
            return self._selection.require_selectable(session, model_id, model_type)

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


@dataclass(frozen=True)
class ConfiguredRewriteModel:
    generator: ConfiguredTextGenerator
    model_id: UUID

    def generate(self, prompt: str, *, max_tokens: int, temperature: float) -> str:
        return self.generator.generate(
            self.model_id,
            prompt,
            max_tokens=max_tokens,
            temperature=temperature,
        )


@dataclass(frozen=True)
class ModelRerankAdapter:
    generator: ConfiguredTextGenerator

    def rerank(
        self,
        query: str,
        candidates: tuple[RetrievalCandidate, ...],
        *,
        model_id: UUID | None,
        params: Mapping[str, object],
    ) -> tuple[RerankScore, ...]:
        if model_id is None:
            raise ModelProviderError("MODEL_NOT_FOUND", retryable=False)
        indices, scores = self.generator.rerank(
            model_id,
            query,
            tuple(candidate.document for candidate in candidates),
            params=params,
        )
        if len(indices) != len(scores):
            raise ModelProviderError("MODEL_RESPONSE_INVALID", retryable=False)
        values: list[RerankScore] = []
        for index, score in zip(indices, scores, strict=True):
            if index < 0 or index >= len(candidates):
                raise ModelProviderError("MODEL_RESPONSE_INVALID", retryable=False)
            values.append(RerankScore(candidates[index].chunk_id, score))
        return tuple(values)


@dataclass(frozen=True)
class LlmRerankAdapter:
    generator: ConfiguredTextGenerator

    def rerank(
        self,
        query: str,
        candidates: tuple[RetrievalCandidate, ...],
        *,
        model_id: UUID | None,
        params: Mapping[str, object],
    ) -> tuple[RerankScore, ...]:
        if model_id is None:
            raise ModelProviderError("MODEL_NOT_FOUND", retryable=False)
        prompt = _llm_rerank_prompt(query, candidates)
        raw = self.generator.generate(model_id, prompt, max_tokens=1024, temperature=0.0)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ModelProviderError("MODEL_RESPONSE_INVALID", retryable=False) from error
        if not isinstance(payload, list):
            raise ModelProviderError("MODEL_RESPONSE_INVALID", retryable=False)
        values: list[RerankScore] = []
        for item in payload:
            if not isinstance(item, dict):
                raise ModelProviderError("MODEL_RESPONSE_INVALID", retryable=False)
            identifier = item.get("id")
            score = item.get("score")
            if (
                not isinstance(identifier, str)
                or isinstance(score, bool)
                or not isinstance(score, int | float)
            ):
                raise ModelProviderError("MODEL_RESPONSE_INVALID", retryable=False)
            try:
                values.append(RerankScore(UUID(identifier), float(score)))
            except ValueError as error:
                raise ModelProviderError("MODEL_RESPONSE_INVALID", retryable=False) from error
        return tuple(values)


def _llm_rerank_prompt(query: str, candidates: tuple[RetrievalCandidate, ...]) -> str:
    items = [
        {"id": str(candidate.chunk_id), "text": candidate.document} for candidate in candidates
    ]
    return (
        "Rank the candidate documents for the query. Return only a JSON array. Each item "
        'must be {"id": "candidate UUID", "score": number from 0 to 1}. Include every '
        "candidate ID exactly once and do not rewrite document text.\n"
        f"Query: {query}\nCandidates: {json.dumps(items, ensure_ascii=False)}"
    )
