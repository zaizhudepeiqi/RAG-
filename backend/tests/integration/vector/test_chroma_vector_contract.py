import os
from uuid import uuid4

import pytest
from app.infrastructure.vector.chroma import ChromaVectorStoreAdapter
from app.modules.retrieval.vector_store import VectorRecord

pytestmark = pytest.mark.integration


def test_real_chroma_cosine_contract_and_collection_isolation() -> None:
    store = ChromaVectorStoreAdapter(
        os.getenv("CHROMA_HOST", "127.0.0.1"),
        int(os.getenv("CHROMA_PORT", "8000")),
    )
    first_name = f"test_generation_{uuid4().hex}"
    second_name = f"test_generation_{uuid4().hex}"
    version_id = uuid4()
    first_chunk = uuid4()
    second_chunk = uuid4()
    try:
        store.ensure_collection(first_name)
        store.ensure_collection(second_name)
        store.upsert(
            first_name,
            (
                VectorRecord(first_chunk, version_id, "chunk", None, "same", (1.0, 0.0)),
                VectorRecord(second_chunk, version_id, "chunk", None, "opposite", (-1.0, 0.0)),
            ),
        )

        hits = store.query(first_name, (1.0, 0.0), top_k=2)

        assert [hit.chunk_id for hit in hits] == [first_chunk, second_chunk]
        assert hits[0].raw_distance == pytest.approx(0.0, abs=1e-6)
        assert hits[0].relevance_score == pytest.approx(1.0, abs=1e-6)
        assert hits[1].raw_distance == pytest.approx(2.0, abs=1e-6)
        assert hits[1].relevance_score == pytest.approx(0.0, abs=1e-6)
        assert (
            store.validate_collection(
                first_name, expected_count=2, expected_dimension=2
            ).embedding_dimension
            == 2
        )
        assert (
            store.validate_collection(
                second_name, expected_count=0, expected_dimension=2
            ).record_count
            == 0
        )
        assert store.copy_records(first_name, second_name, (first_chunk,)) == 1
        assert (
            store.validate_collection(
                second_name, expected_count=1, expected_dimension=2
            ).embedding_dimension
            == 2
        )
        assert store.query(second_name, (1.0, 0.0), top_k=1)[0].chunk_id == first_chunk
    finally:
        store.delete_collection(first_name)
        store.delete_collection(second_name)
        store.delete_collection(second_name)
