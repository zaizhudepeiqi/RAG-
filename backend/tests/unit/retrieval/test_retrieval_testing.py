from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import pytest
from app.modules.knowledge_bases.domain import (
    BuildConfig,
    BuildConfigRevision,
    FusionConfig,
    KeywordConfig,
    QueryRewriteConfig,
    RerankConfig,
    RetrievalConfig,
    RetrievalConfigRevision,
    VectorConfig,
)
from app.modules.retrieval.engine import RetrievalResult
from app.modules.retrieval.fusion import RetrievalCandidate
from app.modules.retrieval.query_rewrite import QueryRewriteResult
from app.modules.retrieval.testing import (
    RetrievalTestService,
    RetrievalTestSnapshot,
    RetrievalTestUnavailableError,
)

KB_ID = UUID("11111111-1111-1111-1111-111111111111")
GENERATION_ID = UUID("22222222-2222-2222-2222-222222222222")
RETRIEVAL_ID = UUID("33333333-3333-3333-3333-333333333333")
BUILD_ID = UUID("44444444-4444-4444-4444-444444444444")
EMBEDDING_ID = UUID("55555555-5555-5555-5555-555555555555")
CHUNK_ID = UUID("66666666-6666-6666-6666-666666666666")
SOURCE_ID = UUID("77777777-7777-7777-7777-777777777777")


def config() -> RetrievalConfig:
    return RetrievalConfig(
        retrieval_type="vector",
        vector=VectorConfig(10, 0.3),
        keyword=KeywordConfig(10, 0.1),
        fusion=FusionConfig("rrf", 60, None, None, 0),
        query_rewrite=QueryRewriteConfig(
            "multi_query", UUID("88888888-8888-8888-8888-888888888888"), {}
        ),
        rerank=RerankConfig("off", None, {}),
        context_window=0,
        final_top_k=5,
    )


def snapshot() -> RetrievalTestSnapshot:
    now = datetime.now(UTC)
    build = BuildConfigRevision(
        id=BUILD_ID,
        knowledge_base_id=KB_ID,
        revision_number=1,
        config_hash="a" * 64,
        config=BuildConfig(
            embedding_model_id=EMBEDDING_ID,
            embedding_params={},
            vector_store_code="chroma",
            vector_store_version="1",
            vector_index_code="hnsw",
            vector_index_version="1",
            vector_index_params={},
            keyword_store_code="postgres_trigram",
            keyword_store_version="1",
            index_structure="chunk",
            index_structure_params={},
            chunk_strategy_code="token",
            chunk_strategy_version="1",
            chunk_params={},
        ),
        embedding_model_snapshot={"embeddingDimension": 2},
        source_ids=(SOURCE_ID,),
        created_at=now,
    )
    retrieval = RetrievalConfigRevision(
        id=RETRIEVAL_ID,
        knowledge_base_id=KB_ID,
        revision_number=1,
        config_hash="b" * 64,
        config=config(),
        created_at=now,
    )
    return RetrievalTestSnapshot(
        knowledge_base_id=KB_ID,
        generation_id=GENERATION_ID,
        collection_name="generation-1",
        build_revision=build,
        retrieval_revision=retrieval,
    )


class FakeSnapshots:
    def __init__(self, value: RetrievalTestSnapshot | None) -> None:
        self.value = value

    def get_active(self, _session, knowledge_base_id: UUID) -> RetrievalTestSnapshot | None:
        assert knowledge_base_id == KB_ID
        return self.value


class FakeRewriteService:
    def rewrite(self, query: str, *, code: str, params: dict[str, object]) -> QueryRewriteResult:
        assert code == "multi_query"
        return QueryRewriteResult(query, (query, "expanded"), ("expanded",), False, None)


@dataclass
class FakeRetriever:
    calls: list[tuple[str, ...]]

    def retrieve_many(self, _session, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(kwargs["queries"])
        candidate = RetrievalCandidate(
            chunk_id=CHUNK_ID,
            parsed_source_version_id=SOURCE_ID,
            chunk_kind="chunk",
            parent_chunk_id=None,
            document="policy",
            vector_score=0.9,
            keyword_score=None,
            vector_rank=1,
            keyword_rank=None,
            vector_normalized=0.9,
            keyword_normalized=None,
            fused_score=0.9,
        )
        return RetrievalResult(
            (candidate,),
            "vector",
            2,
            0,
            query_candidate_counts=(1, 1),
        )


def test_retrieval_test_uses_active_snapshot_and_never_persists_override() -> None:
    retriever = FakeRetriever([])
    service = RetrievalTestService(
        FakeSnapshots(snapshot()),
        lambda _snapshot, _config: retriever,
        lambda _config: FakeRewriteService(),
    )
    override = config()

    result = service.run(None, knowledge_base_id=KB_ID, query="policy", override=override)

    assert retriever.calls == [("policy", "expanded")]
    assert result.snapshot.retrieval_revision.id == RETRIEVAL_ID
    assert result.config is override
    assert result.rewrite.generated_queries == ("expanded",)
    assert result.result.candidates[0].chunk_id == CHUNK_ID


def test_retrieval_test_rejects_knowledge_base_without_active_generation() -> None:
    service = RetrievalTestService(
        FakeSnapshots(None),
        lambda _snapshot, _config: pytest.fail("must not create retriever"),
        lambda _config: pytest.fail("must not create rewrite service"),
    )

    with pytest.raises(RetrievalTestUnavailableError, match="RETRIEVAL_TEST_UNAVAILABLE"):
        service.run(None, knowledge_base_id=KB_ID, query="policy")
