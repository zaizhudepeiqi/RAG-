from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from app.modules.knowledge_bases.domain import BuildConfig
from app.modules.retrieval.vector_store import VectorStoreAdapter
from app.modules.tasks.worker import NonRetryableTaskError

KNOWLEDGE_BASE_BUILD_TASK = "knowledge_base_build"
TERMINAL_GENERATION_STATUSES = frozenset(
    {"succeeded", "partial_ready", "partial_failed", "failed", "cancelled", "discarded"}
)


@dataclass(frozen=True)
class GenerationBuildSnapshot:
    operation_id: UUID
    generation_id: UUID
    knowledge_base_id: UUID
    status: str
    collection_name: str
    active_generation_id: UUID | None
    build_config: BuildConfig
    embedding_model_snapshot: dict[str, object]
    embedding_dimension: int


@dataclass(frozen=True)
class GenerationBuildItem:
    id: UUID
    parsed_source_version_id: UUID
    status: str
    stage_progress: dict[str, object]
    source_copy_from_item_id: UUID | None


@dataclass(frozen=True)
class GenerationValidationSummary:
    source_count: int
    successful_source_count: int
    failed_source_count: int
    chunk_count: int
    vector_count: int
    report: dict[str, object]


@dataclass(frozen=True)
class GenerationFinalization:
    status: str
    activated: bool
    conflict: bool = False


class GenerationBuildStore(Protocol):
    def load(self, operation_id: UUID) -> GenerationBuildSnapshot | None: ...

    def claim(self, generation_id: UUID, started_at: datetime) -> bool: ...

    def list_items(self, generation_id: UUID) -> tuple[GenerationBuildItem, ...]: ...

    def fail_item(
        self,
        item_id: UUID,
        *,
        error_code: str,
        retryable: bool,
        finished_at: datetime,
    ) -> None: ...

    def prepare_validation(
        self, generation_id: UUID, started_at: datetime
    ) -> GenerationValidationSummary: ...

    def fail_validation(
        self,
        generation_id: UUID,
        *,
        error_code: str,
        finished_at: datetime,
    ) -> None: ...

    def finalize(
        self,
        snapshot: GenerationBuildSnapshot,
        summary: GenerationValidationSummary,
        finished_at: datetime,
    ) -> GenerationFinalization: ...


class GenerationItemExecutor(Protocol):
    def run(self, snapshot: GenerationBuildSnapshot, item: GenerationBuildItem) -> None: ...


class GenerationItemBuildError(Exception):
    def __init__(self, code: str, *, retryable: bool) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


class GenerationBuildHandler:
    def __init__(
        self,
        store: GenerationBuildStore,
        items: GenerationItemExecutor,
        vectors: VectorStoreAdapter,
    ) -> None:
        self._store = store
        self._items = items
        self._vectors = vectors

    def run(self, operation_id: UUID) -> dict[str, object]:
        snapshot = self._store.load(operation_id)
        if snapshot is None:
            raise NonRetryableTaskError("GENERATION_NOT_FOUND")
        if snapshot.status in TERMINAL_GENERATION_STATUSES:
            return {
                "knowledgeBaseId": str(snapshot.knowledge_base_id),
                "generationId": str(snapshot.generation_id),
                "status": snapshot.status,
                "duplicate": True,
            }
        if not self._store.claim(snapshot.generation_id, datetime.now(UTC)):
            refreshed = self._store.load(operation_id)
            if refreshed is None:
                raise NonRetryableTaskError("GENERATION_NOT_FOUND")
            return {
                "knowledgeBaseId": str(refreshed.knowledge_base_id),
                "generationId": str(refreshed.generation_id),
                "status": refreshed.status,
                "duplicate": True,
            }

        self._vectors.ensure_collection(snapshot.collection_name)
        for item in self._store.list_items(snapshot.generation_id):
            if item.status in {"succeeded", "failed"}:
                continue
            try:
                self._items.run(snapshot, item)
            except GenerationItemBuildError as error:
                self._store.fail_item(
                    item.id,
                    error_code=error.code,
                    retryable=error.retryable,
                    finished_at=datetime.now(UTC),
                )

        now = datetime.now(UTC)
        summary = self._store.prepare_validation(snapshot.generation_id, now)
        if summary.successful_source_count:
            try:
                self._vectors.validate_collection(
                    snapshot.collection_name,
                    expected_count=summary.vector_count,
                    expected_dimension=snapshot.embedding_dimension,
                )
            except (OSError, RuntimeError, ValueError) as error:
                self._store.fail_validation(
                    snapshot.generation_id,
                    error_code="GENERATION_VECTOR_VALIDATION_FAILED",
                    finished_at=now,
                )
                raise NonRetryableTaskError("GENERATION_VECTOR_VALIDATION_FAILED") from error

        final = self._store.finalize(snapshot, summary, now)
        if final.conflict:
            raise NonRetryableTaskError("GENERATION_ACTIVATION_CONFLICT")
        result = {
            "knowledgeBaseId": str(snapshot.knowledge_base_id),
            "generationId": str(snapshot.generation_id),
            "status": final.status,
            "activated": final.activated,
            "sourceCount": summary.source_count,
            "successfulSourceCount": summary.successful_source_count,
            "failedSourceCount": summary.failed_source_count,
            "chunkCount": summary.chunk_count,
            "vectorCount": summary.vector_count,
        }
        if summary.successful_source_count == 0:
            raise NonRetryableTaskError("GENERATION_NO_SUCCESSFUL_SOURCE")
        return result
