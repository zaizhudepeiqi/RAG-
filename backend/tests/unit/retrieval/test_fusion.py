from uuid import UUID

import pytest
from app.modules.retrieval.fusion import (
    RetrievalCandidate,
    fuse_candidates,
)
from app.modules.retrieval.keyword_store import KeywordHit
from app.modules.retrieval.vector_store import VectorHit


def vector_hit(chunk_id: str, score: float) -> VectorHit:
    return VectorHit(
        UUID(chunk_id),
        UUID("22222222-2222-2222-2222-222222222222"),
        "chunk",
        None,
        f"vector {chunk_id}",
        1 - score,
        "cosine",
        score,
        "cosine_distance_v1",
    )


def keyword_hit(chunk_id: str, score: float) -> KeywordHit:
    return KeywordHit(
        UUID(chunk_id),
        UUID("22222222-2222-2222-2222-222222222222"),
        "chunk",
        None,
        f"keyword {chunk_id}",
        score,
        False,
        False,
        score,
        "postgres_trigram_v1",
        False,
    )


def test_rrf_uses_one_based_rank_and_merges_route_evidence() -> None:
    shared = "11111111-1111-1111-1111-111111111111"
    vector_only = "33333333-3333-3333-3333-333333333333"
    keyword_only = "44444444-4444-4444-4444-444444444444"

    result = fuse_candidates(
        (vector_hit(shared, 0.9), vector_hit(vector_only, 0.8)),
        (keyword_hit(shared, 0.2), keyword_hit(keyword_only, 0.9)),
        strategy="rrf",
        rrf_k=1,
        final_top_k=10,
        final_score_threshold=0,
    )

    assert [candidate.chunk_id for candidate in result] == [
        UUID(shared),
        UUID(vector_only),
        UUID(keyword_only),
    ]
    assert result[0].vector_rank == 1
    assert result[0].keyword_rank == 1
    assert result[0].fused_score == pytest.approx(1.0)
    assert result[1].fused_score == pytest.approx(1 / 3)
    assert result[2].fused_score == pytest.approx(1 / 3)


def test_weighted_score_min_max_singleton_and_tie_are_deterministic() -> None:
    first = "11111111-1111-1111-1111-111111111111"
    second = "33333333-3333-3333-3333-333333333333"
    result = fuse_candidates(
        (vector_hit(first, 0.5), vector_hit(second, 0.5)),
        (keyword_hit(first, 0.2),),
        strategy="weighted_score",
        vector_weight=2,
        keyword_weight=1,
        rrf_k=60,
        final_top_k=10,
        final_score_threshold=0,
    )

    assert [candidate.chunk_id for candidate in result] == [UUID(first), UUID(second)]
    assert result[0].vector_normalized == pytest.approx(1)
    assert result[1].vector_normalized == pytest.approx(1)
    assert result[0].keyword_normalized == pytest.approx(1)
    assert result[0].fused_score == pytest.approx(1)
    assert result[1].fused_score == pytest.approx(2 / 3)


@pytest.mark.parametrize("strategy", ["unknown", "rrf", "weighted_score"])
def test_fusion_rejects_invalid_strategy_arguments(strategy: str) -> None:
    kwargs = {
        "strategy": strategy,
        "rrf_k": 0 if strategy == "rrf" else 60,
        "vector_weight": 0 if strategy == "weighted_score" else None,
        "keyword_weight": 0 if strategy == "weighted_score" else None,
        "final_top_k": 0,
        "final_score_threshold": 0,
    }
    with pytest.raises(ValueError):
        fuse_candidates((), (), **kwargs)


def test_candidate_is_a_small_serializable_contract() -> None:
    candidate = RetrievalCandidate(
        chunk_id=UUID("11111111-1111-1111-1111-111111111111"),
        parsed_source_version_id=UUID("22222222-2222-2222-2222-222222222222"),
        chunk_kind="chunk",
        parent_chunk_id=None,
        document="policy",
        vector_score=0.8,
        keyword_score=None,
        vector_rank=1,
        keyword_rank=None,
        vector_normalized=1,
        keyword_normalized=None,
        fused_score=0.8,
    )
    assert candidate.chunk_kind == "chunk"
