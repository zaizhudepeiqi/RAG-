from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Protocol, cast
from uuid import UUID

import chromadb
import httpx
from chromadb.api import ClientAPI
from chromadb.api.models.Collection import Collection
from chromadb.api.types import Metadata
from chromadb.errors import NotFoundError

from app.modules.retrieval.vector_store import (
    VectorCollectionValidation,
    VectorHit,
    VectorRecord,
)

METRIC = "cosine"
SCORE_TRANSFORM_VERSION = "cosine_distance_v1"
COLLECTION_SCHEMA_VERSION = "1"
METADATA_KEYS = frozenset(
    {"parsed_source_version_id", "chunk_kind", "parent_chunk_id", "schema_version"}
)


class ChromaClientFactory(Protocol):
    def __call__(self, *, host: str, port: int) -> ClientAPI: ...


class ChromaAdapter:
    def __init__(self, host: str, port: int) -> None:
        self._url = f"http://{host}:{port}/api/v2/heartbeat"

    def heartbeat(self) -> None:
        with httpx.Client(timeout=2.0, trust_env=False) as client:
            response = client.get(self._url)
            response.raise_for_status()


class ChromaVectorStoreAdapter:
    def __init__(
        self,
        host: str,
        port: int,
        *,
        client: ClientAPI | None = None,
        client_factory: ChromaClientFactory = chromadb.HttpClient,
    ) -> None:
        self._host = host
        self._port = port
        self._client_instance = client
        self._client_factory = client_factory

    def ensure_collection(self, name: str) -> None:
        collection = self._client().get_or_create_collection(
            name=name,
            metadata={
                "hnsw:space": METRIC,
                "rag:metric": METRIC,
                "rag:schema_version": COLLECTION_SCHEMA_VERSION,
            },
            embedding_function=None,
        )
        self._validate_collection_metadata(collection)

    def upsert(self, name: str, records: tuple[VectorRecord, ...]) -> None:
        if not records:
            return
        dimension = _validate_records(records)
        collection = self._collection(name)
        existing_dimension = self._collection_dimension(collection)
        if existing_dimension is not None and existing_dimension != dimension:
            raise ValueError("embedding dimension does not match collection")
        embeddings: list[Sequence[float] | Sequence[int]] = [
            list(record.embedding) for record in records
        ]
        collection.upsert(
            ids=[str(record.chunk_id) for record in records],
            embeddings=embeddings,
            documents=[record.document for record in records],
            metadatas=[_record_metadata(record) for record in records],
        )

    def query(
        self, name: str, query_embedding: tuple[float, ...], *, top_k: int
    ) -> tuple[VectorHit, ...]:
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        _validate_embedding(query_embedding)
        collection = self._collection(name)
        query_embeddings: list[Sequence[float] | Sequence[int]] = [list(query_embedding)]
        result = collection.query(
            query_embeddings=query_embeddings,
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )
        ids = _first_result_list(result.get("ids"), "ids")
        documents = _first_result_list(result.get("documents"), "documents")
        metadatas = _first_result_list(result.get("metadatas"), "metadatas")
        distances = _first_result_list(result.get("distances"), "distances")
        if not (len(ids) == len(documents) == len(metadatas) == len(distances)):
            raise ValueError("Chroma query response arrays have different lengths")
        hits = tuple(
            _vector_hit(chunk_id, document, metadata, distance)
            for chunk_id, document, metadata, distance in zip(
                ids, documents, metadatas, distances, strict=True
            )
        )
        return tuple(sorted(hits, key=lambda hit: (-hit.relevance_score, str(hit.chunk_id))))

    def copy_records(self, source_name: str, target_name: str, chunk_ids: tuple[UUID, ...]) -> int:
        if not chunk_ids:
            return 0
        source = self._collection(source_name)
        target = self._collection(target_name)
        result = source.get(
            ids=[str(chunk_id) for chunk_id in chunk_ids],
            include=["embeddings", "documents", "metadatas"],
        )
        ids = _flat_list(result.get("ids"), "ids")
        embeddings = _flat_list(result.get("embeddings"), "embeddings")
        documents = _flat_list(result.get("documents"), "documents")
        metadatas = _flat_list(result.get("metadatas"), "metadatas")
        if len(ids) != len(chunk_ids):
            raise ValueError("source collection does not contain every requested chunk")
        if not (len(ids) == len(embeddings) == len(documents) == len(metadatas)):
            raise ValueError("Chroma get response arrays have different lengths")
        copied_embeddings: list[Sequence[float] | Sequence[int]] = [
            _embedding(item) for item in embeddings
        ]
        copied_metadatas: list[Metadata] = [_copy_metadata(item) for item in metadatas]
        target.upsert(
            ids=[_string(item, "chunk id") for item in ids],
            embeddings=copied_embeddings,
            documents=[_string(item, "document") for item in documents],
            metadatas=copied_metadatas,
        )
        return len(ids)

    def validate_collection(
        self,
        name: str,
        *,
        expected_count: int,
        expected_dimension: int,
    ) -> VectorCollectionValidation:
        if expected_count < 0 or expected_dimension <= 0:
            raise ValueError("expected count must be non-negative and dimension positive")
        collection = self._collection(name)
        self._validate_collection_metadata(collection)
        actual_count = collection.count()
        if actual_count != expected_count:
            raise ValueError("collection record count does not match generation")
        dimension = self._collection_dimension(collection)
        if dimension is not None and dimension != expected_dimension:
            raise ValueError("collection embedding dimension does not match model")
        return VectorCollectionValidation(name, METRIC, actual_count, dimension)

    def delete_collection(self, name: str) -> None:
        try:
            self._client().delete_collection(name)
        except NotFoundError:
            return

    def _collection(self, name: str) -> Collection:
        collection = self._client().get_collection(name=name, embedding_function=None)
        self._validate_collection_metadata(collection)
        return collection

    def _client(self) -> ClientAPI:
        if self._client_instance is None:
            self._client_instance = self._client_factory(host=self._host, port=self._port)
        return self._client_instance

    @staticmethod
    def _validate_collection_metadata(collection: Collection) -> None:
        metadata = collection.metadata or {}
        if metadata.get("hnsw:space") != METRIC or metadata.get("rag:metric") != METRIC:
            raise ValueError("Chroma collection is not locked to cosine")
        if metadata.get("rag:schema_version") != COLLECTION_SCHEMA_VERSION:
            raise ValueError("Chroma collection schema version is incompatible")

    @staticmethod
    def _collection_dimension(collection: Collection) -> int | None:
        if collection.count() == 0:
            return None
        result = collection.get(limit=1, include=["embeddings"])
        embeddings = _flat_list(result.get("embeddings"), "embeddings")
        if len(embeddings) != 1:
            raise ValueError("Chroma collection sample is invalid")
        return len(_embedding(embeddings[0]))


def cosine_distance_to_relevance(distance: float) -> float:
    if not math.isfinite(distance):
        raise ValueError("cosine distance must be finite")
    return max(0.0, min(1.0, 1.0 - distance / 2.0))


def _validate_records(records: tuple[VectorRecord, ...]) -> int:
    ids = {record.chunk_id for record in records}
    if len(ids) != len(records):
        raise ValueError("vector record chunk ids must be unique")
    dimension = len(records[0].embedding)
    if dimension == 0 or any(len(record.embedding) != dimension for record in records):
        raise ValueError("vector records must have the same non-zero dimension")
    for record in records:
        if not record.document.strip():
            raise ValueError("vector record document cannot be empty")
        _validate_embedding(record.embedding)
        if record.chunk_kind not in {"chunk", "child"}:
            raise ValueError("only indexable chunk kinds can be written to Chroma")
    return dimension


def _validate_embedding(embedding: Sequence[float]) -> None:
    if not embedding or any(not math.isfinite(value) for value in embedding):
        raise ValueError("embedding must contain finite values")


def _record_metadata(record: VectorRecord) -> dict[str, str]:
    metadata = {
        "parsed_source_version_id": str(record.parsed_source_version_id),
        "chunk_kind": record.chunk_kind,
        "parent_chunk_id": str(record.parent_chunk_id) if record.parent_chunk_id else "",
        "schema_version": COLLECTION_SCHEMA_VERSION,
    }
    if set(metadata) != METADATA_KEYS:
        raise AssertionError("Chroma metadata whitelist drift")
    return metadata


def _vector_hit(
    chunk_id: object, document: object, metadata: object, distance: object
) -> VectorHit:
    normalized_metadata = _metadata(metadata)
    if set(normalized_metadata) != METADATA_KEYS:
        raise ValueError("Chroma metadata violates the contract whitelist")
    raw_distance = _number(distance, "distance")
    parent_value = _string(normalized_metadata["parent_chunk_id"], "parent chunk id")
    return VectorHit(
        chunk_id=UUID(_string(chunk_id, "chunk id")),
        parsed_source_version_id=UUID(
            _string(normalized_metadata["parsed_source_version_id"], "parsed source version id")
        ),
        chunk_kind=_string(normalized_metadata["chunk_kind"], "chunk kind"),
        parent_chunk_id=UUID(parent_value) if parent_value else None,
        document=_string(document, "document"),
        raw_distance=raw_distance,
        metric=METRIC,
        relevance_score=cosine_distance_to_relevance(raw_distance),
        score_transform_version=SCORE_TRANSFORM_VERSION,
    )


def _first_result_list(value: object, field: str) -> list[object]:
    outer = _flat_list(value, field)
    if len(outer) != 1:
        raise ValueError(f"Chroma {field} response must contain one query")
    return _flat_list(outer[0], field)


def _flat_list(value: object, field: str) -> list[object]:
    if value is None:
        return []
    to_list = getattr(value, "tolist", None)
    if callable(to_list):
        value = to_list()
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise ValueError(f"Chroma {field} response must be a sequence")
    return list(cast(Sequence[object], value))


def _metadata(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("Chroma metadata response must be an object")
    return {str(key): item for key, item in value.items()}


def _copy_metadata(value: object) -> Metadata:
    metadata = _metadata(value)
    values_are_strings = all(isinstance(item, str) for item in metadata.values())
    if set(metadata) != METADATA_KEYS or not values_are_strings:
        raise ValueError("Chroma metadata violates the contract whitelist")
    return {key: cast(str, item) for key, item in metadata.items()}


def _embedding(value: object) -> list[float]:
    items = _flat_list(value, "embedding")
    return [_number(item, "embedding value") for item in items]


def _string(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"Chroma {field} must be a string")
    return value


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"Chroma {field} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"Chroma {field} must be finite")
    return normalized
