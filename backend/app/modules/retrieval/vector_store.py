from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class VectorRecord:
    chunk_id: UUID
    parsed_source_version_id: UUID
    chunk_kind: str
    parent_chunk_id: UUID | None
    document: str
    embedding: tuple[float, ...]


@dataclass(frozen=True)
class VectorRecordCopy:
    source_chunk_id: UUID
    target_chunk_id: UUID
    target_parent_chunk_id: UUID | None


@dataclass(frozen=True)
class VectorHit:
    chunk_id: UUID
    parsed_source_version_id: UUID
    chunk_kind: str
    parent_chunk_id: UUID | None
    document: str
    raw_distance: float
    metric: str
    relevance_score: float
    score_transform_version: str


@dataclass(frozen=True)
class VectorCollectionValidation:
    collection_name: str
    metric: str
    record_count: int
    embedding_dimension: int | None


class VectorStoreAdapter(Protocol):
    def ensure_collection(self, name: str) -> None: ...

    def upsert(self, name: str, records: tuple[VectorRecord, ...]) -> None: ...

    def query(
        self, name: str, query_embedding: tuple[float, ...], *, top_k: int
    ) -> tuple[VectorHit, ...]: ...

    def copy_records(
        self, source_name: str, target_name: str, records: tuple[VectorRecordCopy, ...]
    ) -> int: ...

    def delete_records(self, name: str, chunk_ids: tuple[UUID, ...]) -> None: ...

    def validate_collection(
        self,
        name: str,
        *,
        expected_count: int,
        expected_dimension: int,
    ) -> VectorCollectionValidation: ...

    def delete_collection(self, name: str) -> None: ...
