from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.modules.knowledge_bases.errors import InvalidKnowledgeBaseTransitionError


@dataclass(frozen=True)
class BuildConfig:
    embedding_model_id: UUID
    embedding_params: dict[str, object]
    vector_store_code: str
    vector_store_version: str
    vector_index_code: str
    vector_index_version: str
    vector_index_params: dict[str, object]
    keyword_store_code: str
    keyword_store_version: str
    index_structure: str
    index_structure_params: dict[str, object]
    chunk_strategy_code: str
    chunk_strategy_version: str
    chunk_params: dict[str, object]


@dataclass(frozen=True)
class VectorConfig:
    top_k: int
    score_threshold: float

    def as_capability_params(self) -> dict[str, object]:
        return {"topK": self.top_k, "scoreThreshold": self.score_threshold}


@dataclass(frozen=True)
class KeywordConfig:
    top_k: int
    score_threshold: float

    def as_capability_params(self) -> dict[str, object]:
        return {"topK": self.top_k, "scoreThreshold": self.score_threshold}


@dataclass(frozen=True)
class FusionConfig:
    strategy: str
    rrf_k: int | None
    vector_weight: float | None
    keyword_weight: float | None
    final_score_threshold: float

    def as_capability_params(self) -> dict[str, object]:
        if self.strategy == "rrf":
            return {"rrfK": self.rrf_k}
        return {
            "vectorWeight": self.vector_weight,
            "keywordWeight": self.keyword_weight,
        }


@dataclass(frozen=True)
class QueryRewriteConfig:
    code: str
    model_id: UUID | None
    params: dict[str, object]


@dataclass(frozen=True)
class RerankConfig:
    code: str
    model_id: UUID | None
    params: dict[str, object]


@dataclass(frozen=True)
class RetrievalConfig:
    retrieval_type: str
    vector: VectorConfig
    keyword: KeywordConfig
    fusion: FusionConfig
    query_rewrite: QueryRewriteConfig
    rerank: RerankConfig
    context_window: int
    final_top_k: int


@dataclass(frozen=True)
class SourceSelectionSnapshot:
    parsed_source_version_id: UUID
    status: str
    feature_flags: dict[str, bool]


@dataclass(frozen=True)
class ModelSelectionSnapshot:
    id: UUID
    model_type: str
    enabled: bool
    verification_status: str
    embedding_dimension: int | None


def canonical_config_hash(value: object) -> str:
    canonical = json.dumps(
        _canonical_value(value),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def _canonical_value(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return _canonical_value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _canonical_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, StrEnum):
        return value.value
    return value


class GenerationStatus(StrEnum):
    QUEUED = "queued"
    BUILDING = "building"
    VALIDATING = "validating"
    SUCCEEDED = "succeeded"
    PARTIAL_READY = "partial_ready"
    PARTIAL_FAILED = "partial_failed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DISCARDED = "discarded"


class GenerationEvent(StrEnum):
    WORKER_CLAIM = "worker_claim"
    CANCEL = "cancel"
    ALL_ITEMS_TERMINAL = "all_items_terminal"
    VALIDATION_FULL_SUCCESS = "validation_full_success"
    VALIDATION_PARTIAL = "validation_partial"
    VALIDATION_NO_SUCCESS = "validation_no_success"
    RETRY_FAILED_ITEMS = "retry_failed_items"
    DISCARD = "discard"


@dataclass(frozen=True)
class IndexGeneration:
    id: UUID
    knowledge_base_id: UUID
    generation_number: int
    status: GenerationStatus
    completeness: str | None
    is_frozen: bool
    activated_at: datetime | None


def transition_generation(
    generation: IndexGeneration,
    event: GenerationEvent,
    *,
    has_active_generation: bool,
    activated_at: datetime | None = None,
) -> IndexGeneration:
    if generation.is_frozen:
        raise InvalidKnowledgeBaseTransitionError
    transition = (generation.status, event)
    if transition == (GenerationStatus.QUEUED, GenerationEvent.WORKER_CLAIM):
        return replace(generation, status=GenerationStatus.BUILDING)
    if transition == (GenerationStatus.QUEUED, GenerationEvent.CANCEL):
        return replace(generation, status=GenerationStatus.CANCELLED)
    if transition == (GenerationStatus.BUILDING, GenerationEvent.ALL_ITEMS_TERMINAL):
        return replace(generation, status=GenerationStatus.VALIDATING)
    if transition == (
        GenerationStatus.VALIDATING,
        GenerationEvent.VALIDATION_FULL_SUCCESS,
    ):
        if activated_at is None:
            raise InvalidKnowledgeBaseTransitionError
        return replace(
            generation,
            status=GenerationStatus.SUCCEEDED,
            completeness="full",
            is_frozen=True,
            activated_at=activated_at,
        )
    if transition == (GenerationStatus.VALIDATING, GenerationEvent.VALIDATION_PARTIAL):
        if has_active_generation:
            return replace(generation, status=GenerationStatus.PARTIAL_FAILED)
        if activated_at is None:
            raise InvalidKnowledgeBaseTransitionError
        return replace(
            generation,
            status=GenerationStatus.PARTIAL_READY,
            completeness="partial",
            is_frozen=True,
            activated_at=activated_at,
        )
    if transition == (
        GenerationStatus.VALIDATING,
        GenerationEvent.VALIDATION_NO_SUCCESS,
    ):
        return replace(generation, status=GenerationStatus.FAILED)
    if transition == (
        GenerationStatus.PARTIAL_FAILED,
        GenerationEvent.RETRY_FAILED_ITEMS,
    ):
        return replace(generation, status=GenerationStatus.BUILDING)
    if generation.status in {GenerationStatus.FAILED, GenerationStatus.PARTIAL_FAILED} and (
        event is GenerationEvent.DISCARD
    ):
        return replace(generation, status=GenerationStatus.DISCARDED)
    raise InvalidKnowledgeBaseTransitionError


class ItemStatus(StrEnum):
    QUEUED = "queued"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    KEYWORD_INDEXING = "keyword_indexing"
    VECTOR_INDEXING = "vector_indexing"
    VALIDATING = "validating"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ItemEvent(StrEnum):
    START_CHUNKING = "start_chunking"
    START_EMBEDDING = "start_embedding"
    START_KEYWORD_INDEXING = "start_keyword_indexing"
    START_VECTOR_INDEXING = "start_vector_indexing"
    START_VALIDATING = "start_validating"
    SUCCEED = "succeed"
    FAIL = "fail"
    RETRY = "retry"


ITEM_TRANSITIONS = {
    (ItemStatus.QUEUED, ItemEvent.START_CHUNKING): ItemStatus.CHUNKING,
    (ItemStatus.CHUNKING, ItemEvent.START_EMBEDDING): ItemStatus.EMBEDDING,
    (ItemStatus.EMBEDDING, ItemEvent.START_KEYWORD_INDEXING): ItemStatus.KEYWORD_INDEXING,
    (
        ItemStatus.KEYWORD_INDEXING,
        ItemEvent.START_VECTOR_INDEXING,
    ): ItemStatus.VECTOR_INDEXING,
    (ItemStatus.VECTOR_INDEXING, ItemEvent.START_VALIDATING): ItemStatus.VALIDATING,
    (ItemStatus.VALIDATING, ItemEvent.SUCCEED): ItemStatus.SUCCEEDED,
    (ItemStatus.FAILED, ItemEvent.RETRY): ItemStatus.CHUNKING,
}


def transition_generation_item(
    current: ItemStatus,
    event: ItemEvent,
    *,
    generation_frozen: bool,
) -> ItemStatus:
    if generation_frozen:
        raise InvalidKnowledgeBaseTransitionError
    if event is ItemEvent.FAIL and current not in {ItemStatus.SUCCEEDED, ItemStatus.FAILED}:
        return ItemStatus.FAILED
    try:
        return ITEM_TRANSITIONS[(current, event)]
    except KeyError as error:
        raise InvalidKnowledgeBaseTransitionError from error


RUNNING_GENERATION_STATUSES = frozenset(
    {
        GenerationStatus.QUEUED.value,
        GenerationStatus.BUILDING.value,
        GenerationStatus.VALIDATING.value,
    }
)


def derive_display_status(
    enabled: bool,
    active_completeness: str | None,
    latest_build_status: str | None,
    has_pending_build_config: bool,
) -> str:
    if not enabled:
        return "disabled"
    if latest_build_status in RUNNING_GENERATION_STATUSES:
        return "rebuilding" if active_completeness is not None else "building"
    if active_completeness is None:
        return "unavailable"
    if has_pending_build_config:
        return "config_changed"
    if active_completeness == "partial":
        return "partial_ready"
    return "ready"


def derive_allowed_actions(
    *,
    enabled: bool,
    active_completeness: str | None,
    latest_build_status: str | None,
    has_pending_build_config: bool,
    bot_reference_count: int,
) -> tuple[str, ...]:
    running = latest_build_status in RUNNING_GENERATION_STATUSES
    actions = ["edit_metadata", "disable" if enabled else "enable"]
    if active_completeness is not None and enabled:
        actions.append("retrieval_test")
    if has_pending_build_config and not running:
        actions.extend(("build", "discard_pending_build_config"))
    if latest_build_status in {
        GenerationStatus.FAILED.value,
        GenerationStatus.PARTIAL_FAILED.value,
    }:
        actions.append("retry_failed_items")
    if not running and bot_reference_count == 0:
        actions.append("delete")
    return tuple(actions)
