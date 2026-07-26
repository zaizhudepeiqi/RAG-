from uuid import UUID

import pytest
from app.infrastructure.vector.chroma import (
    SCORE_TRANSFORM_VERSION,
    ChromaVectorStoreAdapter,
    cosine_distance_to_relevance,
)
from app.modules.retrieval.vector_store import VectorRecord

CHUNK_ID = UUID("11111111-1111-1111-1111-111111111111")
VERSION_ID = UUID("22222222-2222-2222-2222-222222222222")


class FakeCollection:
    def __init__(self) -> None:
        self.metadata = {
            "hnsw:space": "cosine",
            "rag:metric": "cosine",
            "rag:schema_version": "1",
        }
        self.records: dict[str, tuple[list[float], str, dict[str, str]]] = {}

    def count(self) -> int:
        return len(self.records)

    def upsert(self, *, ids, embeddings, documents, metadatas):
        for values in zip(ids, embeddings, documents, metadatas, strict=True):
            chunk_id, embedding, document, metadata = values
            self.records[chunk_id] = (embedding, document, metadata)

    def get(self, *, ids=None, limit=None, include=None):
        selected = list(self.records.items())
        if ids is not None:
            selected = [item for item in selected if item[0] in ids]
        if limit is not None:
            selected = selected[:limit]
        return {
            "ids": [item[0] for item in selected],
            "embeddings": [item[1][0] for item in selected],
            "documents": [item[1][1] for item in selected],
            "metadatas": [item[1][2] for item in selected],
        }

    def query(self, **_kwargs):
        item = next(iter(self.records.items()))
        return {
            "ids": [[item[0]]],
            "documents": [[item[1][1]]],
            "metadatas": [[item[1][2]]],
            "distances": [[0.4]],
        }

    def delete(self, *, ids):
        for chunk_id in ids:
            self.records.pop(chunk_id, None)


class FakeClient:
    def __init__(self) -> None:
        self.collections: dict[str, FakeCollection] = {}

    def get_or_create_collection(self, *, name, metadata, embedding_function):
        collection = self.collections.setdefault(name, FakeCollection())
        collection.metadata = metadata
        return collection

    def get_collection(self, *, name, embedding_function):
        return self.collections[name]

    def delete_collection(self, name):
        self.collections.pop(name, None)


def record(chunk_id: UUID = CHUNK_ID) -> VectorRecord:
    return VectorRecord(
        chunk_id=chunk_id,
        parsed_source_version_id=VERSION_ID,
        chunk_kind="chunk",
        parent_chunk_id=None,
        document="enterprise policy",
        embedding=(1.0, 0.0),
    )


def adapter(client: FakeClient) -> ChromaVectorStoreAdapter:
    return ChromaVectorStoreAdapter("localhost", 8000, client=client)


def test_upsert_is_idempotent_and_metadata_uses_only_the_whitelist() -> None:
    client = FakeClient()
    store = adapter(client)
    store.ensure_collection("kb_first_generation")

    store.upsert("kb_first_generation", (record(),))
    store.upsert("kb_first_generation", (record(),))

    collection = client.collections["kb_first_generation"]
    assert collection.count() == 1
    metadata = collection.records[str(CHUNK_ID)][2]
    assert set(metadata) == {
        "parsed_source_version_id",
        "chunk_kind",
        "parent_chunk_id",
        "schema_version",
    }


def test_query_returns_normalized_score_and_contract_fields() -> None:
    client = FakeClient()
    store = adapter(client)
    store.ensure_collection("kb_first_generation")
    store.upsert("kb_first_generation", (record(),))

    hit = store.query("kb_first_generation", (1.0, 0.0), top_k=5)[0]

    assert hit.chunk_id == CHUNK_ID
    assert hit.raw_distance == 0.4
    assert hit.relevance_score == 0.8
    assert hit.metric == "cosine"
    assert hit.score_transform_version == SCORE_TRANSFORM_VERSION


@pytest.mark.parametrize(
    ("distance", "score"),
    [(-1.0, 1.0), (0.0, 1.0), (1.0, 0.5), (2.0, 0.0), (3.0, 0.0)],
)
def test_cosine_distance_transform_is_bounded(distance: float, score: float) -> None:
    assert cosine_distance_to_relevance(distance) == score


def test_copy_validate_delete_and_collection_isolation() -> None:
    client = FakeClient()
    store = adapter(client)
    store.ensure_collection("source_generation")
    store.ensure_collection("target_generation")
    store.upsert("source_generation", (record(),))

    assert store.copy_records("source_generation", "target_generation", (CHUNK_ID,)) == 1
    validation = store.validate_collection(
        "target_generation", expected_count=1, expected_dimension=2
    )
    assert validation.record_count == 1
    assert client.collections["source_generation"] is not client.collections["target_generation"]

    store.delete_records("target_generation", (CHUNK_ID,))
    assert client.collections["target_generation"].count() == 0

    store.delete_collection("target_generation")
    assert "target_generation" not in client.collections


def test_rejects_non_indexable_kinds_and_dimension_mismatch() -> None:
    client = FakeClient()
    store = adapter(client)
    store.ensure_collection("generation")

    with pytest.raises(ValueError, match="indexable"):
        store.upsert(
            "generation",
            (VectorRecord(UUID(int=3), VERSION_ID, "parent", None, "parent", (1.0, 0.0)),),
        )
    store.upsert("generation", (record(),))
    with pytest.raises(ValueError, match="dimension"):
        store.upsert(
            "generation",
            (VectorRecord(UUID(int=4), VERSION_ID, "chunk", None, "other", (1.0, 0.0, 0.0)),),
        )
