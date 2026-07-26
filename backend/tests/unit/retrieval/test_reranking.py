from __future__ import annotations

from uuid import UUID

import pytest
from app.modules.models.adapters import ModelProviderError
from app.modules.retrieval.context import ContextChunk, expand_context
from app.modules.retrieval.fusion import RetrievalCandidate
from app.modules.retrieval.reranking import (
    RerankError,
    RerankScore,
    RerankService,
)

GENERATION_ID = UUID("11111111-1111-1111-1111-111111111111")
SOURCE_ID = UUID("22222222-2222-2222-2222-222222222222")


def candidate(value: str, score: float, *, parent: UUID | None = None) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=UUID(value),
        parsed_source_version_id=SOURCE_ID,
        chunk_kind="child" if parent else "chunk",
        parent_chunk_id=parent,
        document=f"document {value}",
        vector_score=None,
        keyword_score=None,
        vector_rank=None,
        keyword_rank=None,
        vector_normalized=None,
        keyword_normalized=None,
        fused_score=score,
    )


class FakeReranker:
    def __init__(self, scores: tuple[RerankScore, ...] | None = None) -> None:
        self.scores = scores or ()
        self.calls: list[tuple[str, tuple[UUID, ...], UUID | None]] = []

    def rerank(
        self,
        query: str,
        candidates: tuple[RetrievalCandidate, ...],
        *,
        model_id: UUID | None,
        params: dict[str, object],
    ) -> tuple[RerankScore, ...]:
        self.calls.append((query, tuple(item.chunk_id for item in candidates), model_id))
        return self.scores


def test_rerank_hard_limits_candidates_and_applies_score_and_top_k() -> None:
    first = UUID("33333333-3333-3333-3333-333333333333")
    second = UUID("44444444-4444-4444-4444-444444444444")
    third = UUID("55555555-5555-5555-5555-555555555555")
    adapter = FakeReranker(
        (
            RerankScore(second, 0.91),
            RerankScore(first, 0.82),
        )
    )

    result = RerankService({"rerank_model": adapter}).apply(
        "policy",
        (candidate(str(first), 0.8), candidate(str(second), 0.7), candidate(str(third), 0.6)),
        code="rerank_model",
        model_id=UUID("66666666-6666-6666-6666-666666666666"),
        params={"candidateLimit": 2, "topK": 1, "scoreThreshold": 0.8},
    )

    assert adapter.calls[0][1] == (first, second)
    assert [item.chunk_id for item in result.candidates] == [second]
    assert result.candidates[0].rerank_score == pytest.approx(0.91)
    assert result.candidates[0].rerank_rank == 1
    assert result.applied is True


def test_retryable_rerank_failure_returns_original_order_with_warning() -> None:
    class FailingReranker(FakeReranker):
        def rerank(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise ModelProviderError("MODEL_RATE_LIMITED", retryable=True)

    first = UUID("33333333-3333-3333-3333-333333333333")
    second = UUID("44444444-4444-4444-4444-444444444444")
    result = RerankService({"llm_rerank": FailingReranker()}).apply(
        "policy",
        (candidate(str(first), 0.8), candidate(str(second), 0.7)),
        code="llm_rerank",
        model_id=UUID("66666666-6666-6666-6666-666666666666"),
        params={"candidateLimit": 2, "topK": 1, "scoreThreshold": 0.99},
    )

    assert [item.chunk_id for item in result.candidates] == [first]
    assert result.applied is False
    assert result.degraded is True
    assert result.warning_code == "RERANK_DEGRADED"


def test_invalid_rerank_response_is_a_failed_retrieval() -> None:
    unknown = UUID("77777777-7777-7777-7777-777777777777")
    adapter = FakeReranker((RerankScore(unknown, 0.9),))

    with pytest.raises(RerankError, match="RERANK_FAILED"):
        RerankService({"rerank_model": adapter}).apply(
            "policy",
            (candidate("33333333-3333-3333-3333-333333333333", 0.8),),
            code="rerank_model",
            model_id=UUID("66666666-6666-6666-6666-666666666666"),
            params={"candidateLimit": 2, "topK": 1, "scoreThreshold": 0},
        )


def test_context_expansion_deduplicates_parent_and_stays_within_source_and_parent() -> None:
    parent = UUID("88888888-8888-8888-8888-888888888888")
    child = UUID("33333333-3333-3333-3333-333333333333")
    neighbor = UUID("44444444-4444-4444-4444-444444444444")
    other_parent = UUID("99999999-9999-9999-9999-999999999999")
    other_source = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    chunks = (
        ContextChunk(parent, GENERATION_ID, SOURCE_ID, "parent", None, 0, "parent text"),
        ContextChunk(child, GENERATION_ID, SOURCE_ID, "child", parent, 1, "child text"),
        ContextChunk(neighbor, GENERATION_ID, SOURCE_ID, "child", parent, 2, "neighbor text"),
        ContextChunk(
            UUID("55555555-5555-5555-5555-555555555555"),
            GENERATION_ID,
            SOURCE_ID,
            "child",
            other_parent,
            3,
            "other parent text",
        ),
        ContextChunk(
            UUID("66666666-6666-6666-6666-666666666666"),
            GENERATION_ID,
            other_source,
            "child",
            parent,
            4,
            "other source text",
        ),
    )

    result = expand_context(
        (candidate(str(child), 0.9, parent=parent), candidate(str(neighbor), 0.8, parent=parent)),
        chunks,
        context_window=1,
    )

    assert [item.chunk_id for item in result] == [parent]
    assert result[0].matched_child_ids == (child, neighbor)


def test_context_window_does_not_follow_cross_generation_links() -> None:
    first = UUID("33333333-3333-3333-3333-333333333333")
    cross_generation = UUID("44444444-4444-4444-4444-444444444444")
    chunks = (
        ContextChunk(
            first,
            GENERATION_ID,
            SOURCE_ID,
            "chunk",
            None,
            0,
            "first",
            next_chunk_id=cross_generation,
        ),
        ContextChunk(
            cross_generation,
            UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            SOURCE_ID,
            "chunk",
            None,
            1,
            "cross generation",
        ),
    )

    result = expand_context((candidate(str(first), 0.9),), chunks, context_window=1)

    assert [item.chunk_id for item in result] == [first]
