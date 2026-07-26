from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from app.modules.chunking.domain import ChunkDraft, SourceBlock
from app.modules.chunking.index_structures import (
    ChunkIndexStructure,
    ParentChildIndexStructure,
)
from app.modules.chunking.normalization import normalize_blocks
from app.modules.chunking.strategies import (
    ChunkingContext,
    EmbeddingPort,
    HeadingChunkStrategy,
    PageChunkStrategy,
    ParagraphChunkStrategy,
    SemanticChunkStrategy,
    TokenChunkStrategy,
)
from app.modules.chunking.token_counter import Cl100kTokenCounter
from app.modules.knowledge_bases.domain import BuildConfig
from app.modules.knowledge_bases.tasks import (
    GenerationBuildItem,
    GenerationBuildSnapshot,
    GenerationItemBuildError,
)
from app.modules.models.adapters import ModelProviderError
from app.modules.retrieval.vector_store import VectorRecord, VectorStoreAdapter


class GenerationItemStore(Protocol):
    def start_chunking(self, item_id: UUID) -> str: ...

    def load_source_blocks(self, parsed_source_version_id: UUID) -> tuple[SourceBlock, ...]: ...

    def save_chunks(
        self,
        item_id: UUID,
        generation_id: UUID,
        chunks: tuple[ChunkDraft, ...],
        indexable_chunk_ids: tuple[UUID, ...],
        warnings: tuple[str, ...],
    ) -> None: ...

    def load_indexable_chunks(self, item_id: UUID) -> tuple[ChunkDraft, ...]: ...

    def checkpoint_embedding(self, item_id: UUID, vector_count: int) -> None: ...

    def checkpoint_keyword(self, item_id: UUID) -> None: ...

    def checkpoint_vector(self, item_id: UUID) -> None: ...

    def complete_validation(self, item_id: UUID) -> None: ...


class DocumentEmbedder(Protocol):
    def embed_documents(
        self,
        *,
        model_id: UUID,
        model_snapshot: dict[str, object],
        params: dict[str, object],
        texts: Sequence[str],
        expected_dimension: int,
    ) -> tuple[tuple[float, ...], ...]: ...


class _SemanticEmbeddingPort(EmbeddingPort):
    def __init__(
        self,
        embedder: DocumentEmbedder,
        snapshot: GenerationBuildSnapshot,
    ) -> None:
        self._embedder = embedder
        self._snapshot = snapshot

    def embed_documents(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        return self._embedder.embed_documents(
            model_id=self._snapshot.build_config.embedding_model_id,
            model_snapshot=self._snapshot.embedding_model_snapshot,
            params=self._snapshot.build_config.embedding_params,
            texts=texts,
            expected_dimension=self._snapshot.embedding_dimension,
        )


class DefaultGenerationItemExecutor:
    def __init__(
        self,
        store: GenerationItemStore,
        embedder: DocumentEmbedder,
        vectors: VectorStoreAdapter,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._vectors = vectors

    def run(self, snapshot: GenerationBuildSnapshot, item: GenerationBuildItem) -> None:
        try:
            status = self._store.start_chunking(item.id)
            if status == "chunking":
                status = self._chunk(snapshot, item)
            if status == "embedding":
                status = self._embed(snapshot, item)
            if status == "keyword_indexing":
                self._store.checkpoint_keyword(item.id)
                status = "vector_indexing"
            if status == "vector_indexing":
                self._store.checkpoint_vector(item.id)
                status = "validating"
            if status == "validating":
                self._store.complete_validation(item.id)
        except GenerationItemBuildError:
            raise
        except ModelProviderError as error:
            self._cleanup_vectors(snapshot, item)
            raise GenerationItemBuildError(error.code, retryable=error.retryable) from error
        except (ValueError, LookupError) as error:
            self._cleanup_vectors(snapshot, item)
            raise GenerationItemBuildError(
                "GENERATION_ITEM_INPUT_INVALID", retryable=False
            ) from error
        except (OSError, RuntimeError) as error:
            self._cleanup_vectors(snapshot, item)
            raise GenerationItemBuildError(
                "GENERATION_ITEM_BUILD_FAILED", retryable=True
            ) from error

    def _chunk(self, snapshot: GenerationBuildSnapshot, item: GenerationBuildItem) -> str:
        config = snapshot.build_config
        blocks = self._store.load_source_blocks(item.parsed_source_version_id)
        units = normalize_blocks(blocks)
        if not units:
            raise GenerationItemBuildError("GENERATION_SOURCE_EMPTY", retryable=False)
        context = ChunkingContext(
            generation_id=snapshot.generation_id,
            parsed_source_version_id=item.parsed_source_version_id,
            algorithm_version=(
                f"{config.chunk_strategy_code}:{config.chunk_strategy_version}:"
                f"{config.index_structure}:{config.vector_index_version}"
            ),
            counter=Cl100kTokenCounter(),
        )
        strategy = _build_strategy(config, self._embedder, snapshot)
        chunked = strategy.chunk(context, units)
        structured = _build_structure(config).assemble(context, chunked.chunks)
        if not structured.indexable_chunks:
            raise GenerationItemBuildError("GENERATION_SOURCE_EMPTY", retryable=False)
        self._store.save_chunks(
            item.id,
            snapshot.generation_id,
            structured.all_chunks,
            tuple(chunk.id for chunk in structured.indexable_chunks),
            chunked.warnings,
        )
        return "embedding"

    def _embed(self, snapshot: GenerationBuildSnapshot, item: GenerationBuildItem) -> str:
        chunks = self._store.load_indexable_chunks(item.id)
        vectors = self._embedder.embed_documents(
            model_id=snapshot.build_config.embedding_model_id,
            model_snapshot=snapshot.embedding_model_snapshot,
            params=snapshot.build_config.embedding_params,
            texts=tuple(chunk.text for chunk in chunks),
            expected_dimension=snapshot.embedding_dimension,
        )
        if len(vectors) != len(chunks):
            raise GenerationItemBuildError("MODEL_RESPONSE_INVALID", retryable=False)
        self._vectors.upsert(
            snapshot.collection_name,
            tuple(
                VectorRecord(
                    chunk_id=chunk.id,
                    parsed_source_version_id=chunk.parsed_source_version_id,
                    chunk_kind=chunk.chunk_kind,
                    parent_chunk_id=chunk.parent_chunk_id,
                    document=chunk.text,
                    embedding=vector,
                )
                for chunk, vector in zip(chunks, vectors, strict=True)
            ),
        )
        self._store.checkpoint_embedding(item.id, len(vectors))
        return "keyword_indexing"

    def _cleanup_vectors(
        self, snapshot: GenerationBuildSnapshot, item: GenerationBuildItem
    ) -> None:
        try:
            chunks = self._store.load_indexable_chunks(item.id)
            self._vectors.delete_records(
                snapshot.collection_name, tuple(chunk.id for chunk in chunks)
            )
        except (OSError, RuntimeError, ValueError):
            return


def _build_strategy(
    config: BuildConfig,
    embedder: DocumentEmbedder,
    snapshot: GenerationBuildSnapshot,
) -> (
    TokenChunkStrategy
    | ParagraphChunkStrategy
    | HeadingChunkStrategy
    | PageChunkStrategy
    | SemanticChunkStrategy
):
    params = config.chunk_params
    if config.chunk_strategy_code == "token":
        return TokenChunkStrategy(_int(params, "chunkSize"), _int(params, "chunkOverlap"))
    if config.chunk_strategy_code == "paragraph":
        return ParagraphChunkStrategy(
            _int(params, "maxChunkSize"),
            _int(params, "minChunkSize"),
            _int(params, "overlapParagraphs"),
        )
    if config.chunk_strategy_code == "heading":
        return HeadingChunkStrategy(
            _int(params, "maxHeadingLevel"),
            _int(params, "maxChunkSize"),
            _bool(params, "includeHeadingPath"),
        )
    if config.chunk_strategy_code == "page":
        return PageChunkStrategy(_int(params, "maxChunkSize"), _int(params, "chunkOverlap"))
    if config.chunk_strategy_code == "semantic":
        return SemanticChunkStrategy(
            _int(params, "minChunkSize"),
            _int(params, "maxChunkSize"),
            _float(params, "similarityThreshold"),
            _int(params, "sentenceWindow"),
            _SemanticEmbeddingPort(embedder, snapshot),
        )
    raise LookupError("chunk strategy is not implemented")


def _build_structure(config: BuildConfig) -> ChunkIndexStructure | ParentChildIndexStructure:
    if config.index_structure == "chunk":
        return ChunkIndexStructure()
    if config.index_structure == "parent_child":
        params = config.index_structure_params
        return ParentChildIndexStructure(
            _int(params, "parentChunkSize"),
            _int(params, "childChunkSize"),
            _int(params, "childChunkOverlap"),
        )
    raise LookupError("index structure is not implemented")


def _int(params: dict[str, object], name: str) -> int:
    value = params.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def _float(params: dict[str, object], name: str) -> float:
    value = params.get(name)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{name} must be numeric")
    return float(value)


def _bool(params: dict[str, object], name: str) -> bool:
    value = params.get(name)
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean")
    return value
