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
from app.modules.retrieval.reranking import RerankScore, RerankService
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


def rerank_config() -> RetrievalConfig:
    base = config("vector")
    return RetrievalConfig(
        retrieval_type=base.retrieval_type,
        vector=base.vector,
        keyword=base.keyword,
        fusion=base.fusion,
        query_rewrite=base.query_rewrite,
        rerank=RerankConfig(
            "rerank_model",
            UUID("66666666-6666-6666-6666-666666666666"),
            {"candidateLimit": 2, "topK": 1, "scoreThreshold": 0},
        ),
        context_window=base.context_window,
        final_top_k=base.final_top_k,
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


class ManyVectors(FakeVectors):
    def __init__(self) -> None:
        super().__init__()
        self.requested_top_k = 0

    def query(self, name, embedding, *, top_k):  # type: ignore[no-untyped-def]
        self.requested_top_k = top_k
        return tuple(
            VectorHit(
                UUID(value),
                UUID("33333333-3333-3333-3333-333333333333"),
                "chunk",
                None,
                f"policy {value}",
                0,
                "cosine",
                score,
                "cosine_distance_v1",
            )
            for value, score in (
                ("22222222-2222-2222-2222-222222222222", 0.9),
                ("44444444-4444-4444-4444-444444444444", 0.8),
                ("55555555-5555-5555-5555-555555555555", 0.7),
            )
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


def test_rerank_candidate_limit_is_applied_before_model_and_result_is_final_limited() -> None:
    vectors = ManyVectors()

    class FakeReranker:
        def rerank(self, _query, candidates, *, model_id, params):  # type: ignore[no-untyped-def]
            assert len(candidates) == 2
            return tuple(
                RerankScore(item.chunk_id, 1 - index / 10)
                for index, item in enumerate(reversed(candidates))
            )

    retriever = SingleKnowledgeBaseRetriever(
        vectors,
        FakeKeywords(),
        FakeQueryEmbedder(),
        reranker=RerankService({"rerank_model": FakeReranker()}),
    )

    result = retriever.retrieve(
        None,  # type: ignore[arg-type]
        generation_id=GENERATION_ID,
        collection_name="generation",
        query="policy",
        config=rerank_config(),
    )

    assert vectors.requested_top_k == 10
    assert len(result.candidates) == 1
    assert result.rerank_applied is True


def test_multiple_rewrite_queries_are_fused_before_final_limit() -> None:
    shared = UUID("44444444-4444-4444-4444-444444444444")

    class QueryEmbedder:
        def embed_query(self, query: str) -> tuple[float, ...]:
            return (1.0, 0.0) if query == "original" else (0.0, 1.0)

    class QueryVectors(FakeVectors):
        def query(self, _name, embedding, *, top_k):  # type: ignore[no-untyped-def]
            if embedding == (1.0, 0.0):
                values = (
                    ("22222222-2222-2222-2222-222222222222", 0.9),
                    (str(shared), 0.8),
                )
            else:
                values = (
                    (str(shared), 0.95),
                    ("55555555-5555-5555-5555-555555555555", 0.7),
                )
            return tuple(
                VectorHit(
                    UUID(value),
                    UUID("33333333-3333-3333-3333-333333333333"),
                    "chunk",
                    None,
                    value,
                    1 - score,
                    "cosine",
                    score,
                    "cosine_distance_v1",
                )
                for value, score in values
            )[:top_k]

    retriever = SingleKnowledgeBaseRetriever(QueryVectors(), FakeKeywords(), QueryEmbedder())

    result = retriever.retrieve_many(
        None,  # type: ignore[arg-type]
        generation_id=GENERATION_ID,
        collection_name="generation",
        queries=("original", "expanded"),
        query_for_rerank="original",
        config=config("vector"),
    )

    assert result.candidates[0].chunk_id == shared
    assert result.candidates[0].query_ranks == (2, 1)
    assert result.query_candidate_counts == (2, 2)
