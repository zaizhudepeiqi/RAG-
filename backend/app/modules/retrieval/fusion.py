from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.modules.retrieval.keyword_store import KeywordHit
from app.modules.retrieval.vector_store import VectorHit


@dataclass(frozen=True)
class RetrievalCandidate:
    chunk_id: UUID
    parsed_source_version_id: UUID
    chunk_kind: str
    parent_chunk_id: UUID | None
    document: str
    vector_score: float | None
    keyword_score: float | None
    vector_rank: int | None
    keyword_rank: int | None
    vector_normalized: float | None
    keyword_normalized: float | None
    fused_score: float
    rerank_score: float | None = None
    rerank_rank: int | None = None
    query_ranks: tuple[int, ...] = ()


@dataclass
class _Evidence:
    chunk_id: UUID
    parsed_source_version_id: UUID
    chunk_kind: str
    parent_chunk_id: UUID | None
    document: str
    vector_score: float | None = None
    keyword_score: float | None = None
    vector_rank: int | None = None
    keyword_rank: int | None = None


def fuse_candidates(
    vector_hits: tuple[VectorHit, ...],
    keyword_hits: tuple[KeywordHit, ...],
    *,
    strategy: str,
    rrf_k: int | None = 60,
    vector_weight: float | None = 0.5,
    keyword_weight: float | None = 0.5,
    final_top_k: int,
    final_score_threshold: float,
) -> tuple[RetrievalCandidate, ...]:
    _validate_fusion_config(
        strategy,
        rrf_k,
        vector_weight,
        keyword_weight,
        final_top_k,
        final_score_threshold,
    )
    evidence: dict[UUID, _Evidence] = {}
    for rank, hit in enumerate(vector_hits, start=1):
        current = evidence.setdefault(
            hit.chunk_id,
            _Evidence(
                hit.chunk_id,
                hit.parsed_source_version_id,
                hit.chunk_kind,
                hit.parent_chunk_id,
                hit.document,
            ),
        )
        current.vector_score = hit.relevance_score
        current.vector_rank = rank
    for rank, keyword_hit in enumerate(keyword_hits, start=1):
        current = evidence.setdefault(
            keyword_hit.chunk_id,
            _Evidence(
                keyword_hit.chunk_id,
                keyword_hit.parsed_source_version_id,
                keyword_hit.chunk_kind,
                keyword_hit.parent_chunk_id,
                keyword_hit.document,
            ),
        )
        current.keyword_score = keyword_hit.keyword_score
        current.keyword_rank = rank

    vector_normalized = _normalize({key: item.vector_score for key, item in evidence.items()})
    keyword_normalized = _normalize({key: item.keyword_score for key, item in evidence.items()})
    candidates = []
    for item in evidence.values():
        if strategy == "rrf":
            score = _rrf_score(item.vector_rank, item.keyword_rank, rrf_k or 0)
        else:
            score = _weighted_score(
                vector_normalized.get(item.chunk_id),
                keyword_normalized.get(item.chunk_id),
                vector_weight or 0,
                keyword_weight or 0,
            )
        if score < final_score_threshold:
            continue
        candidates.append(
            RetrievalCandidate(
                chunk_id=item.chunk_id,
                parsed_source_version_id=item.parsed_source_version_id,
                chunk_kind=item.chunk_kind,
                parent_chunk_id=item.parent_chunk_id,
                document=item.document,
                vector_score=item.vector_score,
                keyword_score=item.keyword_score,
                vector_rank=item.vector_rank,
                keyword_rank=item.keyword_rank,
                vector_normalized=vector_normalized.get(item.chunk_id),
                keyword_normalized=keyword_normalized.get(item.chunk_id),
                fused_score=score,
            )
        )
    candidates.sort(key=lambda item: (-item.fused_score, str(item.chunk_id)))
    return tuple(candidates[:final_top_k])


def rank_single_route(
    vector_hits: tuple[VectorHit, ...],
    keyword_hits: tuple[KeywordHit, ...],
    *,
    final_top_k: int,
    final_score_threshold: float,
) -> tuple[RetrievalCandidate, ...]:
    if vector_hits and keyword_hits:
        raise ValueError("single-route ranking accepts one route")
    route_hits: tuple[VectorHit | KeywordHit, ...] = (
        tuple(vector_hits) if vector_hits else tuple(keyword_hits)
    )
    if not 1 <= final_top_k <= 100 or not 0 <= final_score_threshold <= 1:
        raise ValueError("invalid single-route fusion limits")
    candidates = []
    for rank, hit in enumerate(route_hits, start=1):
        if isinstance(hit, VectorHit):
            score = hit.relevance_score
            vector_score, keyword_score = score, None
            vector_rank, keyword_rank = rank, None
        else:
            score = hit.keyword_score
            vector_score, keyword_score = None, score
            vector_rank, keyword_rank = None, rank
        if score < final_score_threshold:
            continue
        candidates.append(
            RetrievalCandidate(
                hit.chunk_id,
                hit.parsed_source_version_id,
                hit.chunk_kind,
                hit.parent_chunk_id,
                hit.document,
                vector_score,
                keyword_score,
                vector_rank,
                keyword_rank,
                score,
                score,
                score,
            )
        )
    candidates.sort(key=lambda item: (-item.fused_score, str(item.chunk_id)))
    return tuple(candidates[:final_top_k])


def _normalize(scores: dict[UUID, float | None]) -> dict[UUID, float]:
    present = {key: value for key, value in scores.items() if value is not None}
    if not present:
        return {}
    minimum = min(present.values())
    maximum = max(present.values())
    if minimum == maximum:
        return {key: 1.0 for key in present}
    return {key: (value - minimum) / (maximum - minimum) for key, value in present.items()}


def _rrf_score(vector_rank: int | None, keyword_rank: int | None, rrf_k: int) -> float:
    return sum(1 / (rrf_k + rank) for rank in (vector_rank, keyword_rank) if rank is not None)


def _weighted_score(
    vector_score: float | None,
    keyword_score: float | None,
    vector_weight: float,
    keyword_weight: float,
) -> float:
    numerator = (vector_score or 0) * vector_weight + (keyword_score or 0) * keyword_weight
    return numerator / (vector_weight + keyword_weight)


def _validate_fusion_config(
    strategy: str,
    rrf_k: int | None,
    vector_weight: float | None,
    keyword_weight: float | None,
    final_top_k: int,
    final_score_threshold: float,
) -> None:
    if strategy not in {"rrf", "weighted_score"}:
        raise ValueError("unsupported fusion strategy")
    if not 1 <= final_top_k <= 100:
        raise ValueError("final_top_k must be between 1 and 100")
    if not 0 <= final_score_threshold <= 1:
        raise ValueError("final_score_threshold must be between 0 and 1")
    if strategy == "rrf" and (rrf_k is None or not 1 <= rrf_k <= 1000):
        raise ValueError("rrf_k must be between 1 and 1000")
    if strategy == "weighted_score":
        weights = (vector_weight, keyword_weight)
        if any(value is None or not 0 <= value <= 10 for value in weights):
            raise ValueError("fusion weights must be between 0 and 10")
        if sum(value or 0 for value in weights) == 0:
            raise ValueError("fusion weights cannot both be zero")
