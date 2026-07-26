from uuid import UUID

import pytest
from app.modules.knowledge_bases.domain import (
    FusionConfig,
    KeywordConfig,
    QueryRewriteConfig,
    RerankConfig,
    RetrievalConfig,
    VectorConfig,
)
from app.modules.retrieval.engine import (
    RetrievalExecutionError,
    SingleKnowledgeBaseRetriever,
)
from app.modules.retrieval.keyword_store import KeywordHit
from app.modules.retrieval.vector_store import (
    VectorHit,
)

GENERATION_ID = UUID("11111111-1111-1111-1111-111111111111")


def config(retrieval_type: str) -> RetrievalConfig:
    return RetrievalConfig(
        retrieval_type=retrieval_type,
        vector=VectorConfig(10, 0.3),
        keyword=KeywordConfig(10, 0.1),
        fusion=FusionConfig("rrf", 60, None, None, 0),
        query_rewrite=QueryRewriteConfig("off", None, {}),
        rerank=RerankConfig("off", None, {}),
        context_window=0,
        final_top_k=5,
    )


class FakeQueryEmbedder:
    def embed_query(self, query: str) -> tuple[float, ...]:
        assert query == "policy"
        return (1.0, 0.0)


class FakeVectors:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def query(self, _name: str, _embedding: tuple[float, ...], *, top_k: int):
        if self.fail:
            raise OSError("chroma unavailable")
        return (
            VectorHit(
                UUID("22222222-2222-2222-2222-222222222222"),
                UUID("33333333-3333-3333-3333-333333333333"),
                "chunk",
                None,
                "policy",
                0,
                "cosine",
                1,
                "cosine_distance_v1",
            ),
        )[:top_k]


class FakeKeywords:
    def query(self, _session, **_kwargs):
        return (
            KeywordHit(
                UUID("44444444-4444-4444-4444-444444444444"),
                UUID("33333333-3333-3333-3333-333333333333"),
                "chunk",
                None,
                "policy",
                1,
                True,
                False,
                0.95,
                "postgres_trigram_v1",
                False,
            ),
        )


def test_vector_and_hybrid_retrieval_use_route_threshold_and_fusion() -> None:
    retriever = SingleKnowledgeBaseRetriever(FakeVectors(), FakeKeywords(), FakeQueryEmbedder())

    vector_result = retriever.retrieve(
        None,  # type: ignore[arg-type]
        generation_id=GENERATION_ID,
        collection_name="generation",
        query="policy",
        config=config("vector"),
    )
    hybrid_result = retriever.retrieve(
        None,  # type: ignore[arg-type]
        generation_id=GENERATION_ID,
        collection_name="generation",
        query="policy",
        config=config("hybrid"),
    )

    assert vector_result.candidates[0].fused_score == 1
    assert vector_result.vector_candidate_count == 1
    assert hybrid_result.keyword_candidate_count == 1


def test_vector_store_failure_is_not_reported_as_empty_result() -> None:
    retriever = SingleKnowledgeBaseRetriever(
        FakeVectors(fail=True), FakeKeywords(), FakeQueryEmbedder()
    )

    with pytest.raises(RetrievalExecutionError, match="VECTOR_STORE_UNAVAILABLE"):
        retriever.retrieve(
            None,  # type: ignore[arg-type]
            generation_id=GENERATION_ID,
            collection_name="generation",
            query="policy",
            config=config("vector"),
        )
