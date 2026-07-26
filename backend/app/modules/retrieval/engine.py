from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.modules.knowledge_bases.domain import RetrievalConfig
from app.modules.models.adapters import ModelProviderError
from app.modules.retrieval.fusion import (
    RetrievalCandidate,
    fuse_candidates,
    rank_single_route,
)
from app.modules.retrieval.keyword_store import KeywordHit, KeywordStoreAdapter
from app.modules.retrieval.vector_store import VectorHit, VectorStoreAdapter


class QueryEmbeddingPort(Protocol):
    def embed_query(self, query: str) -> tuple[float, ...]: ...


@dataclass(frozen=True)
class RetrievalResult:
    candidates: tuple[RetrievalCandidate, ...]
    retrieval_type: str
    vector_candidate_count: int
    keyword_candidate_count: int


class RetrievalExecutionError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class SingleKnowledgeBaseRetriever:
    def __init__(
        self,
        vectors: VectorStoreAdapter,
        keywords: KeywordStoreAdapter,
        query_embedder: QueryEmbeddingPort,
    ) -> None:
        self._vectors = vectors
        self._keywords = keywords
        self._query_embedder = query_embedder

    def retrieve(
        self,
        session: Session,
        *,
        generation_id: UUID,
        collection_name: str,
        query: str,
        config: RetrievalConfig,
    ) -> RetrievalResult:
        vector_hits: tuple[VectorHit, ...] = ()
        keyword_hits: tuple[KeywordHit, ...] = ()
        if config.retrieval_type in {"vector", "hybrid"}:
            try:
                embedding = self._query_embedder.embed_query(query)
            except (ModelProviderError, OSError, RuntimeError, ValueError) as error:
                raise RetrievalExecutionError("QUERY_EMBEDDING_FAILED") from error
            try:
                vector_hits = tuple(
                    hit
                    for hit in self._vectors.query(
                        collection_name,
                        embedding,
                        top_k=config.vector.top_k,
                    )
                    if hit.relevance_score >= config.vector.score_threshold
                )
            except (OSError, RuntimeError, ValueError) as error:
                raise RetrievalExecutionError("VECTOR_STORE_UNAVAILABLE") from error
        if config.retrieval_type in {"keyword", "hybrid"}:
            try:
                keyword_hits = self._keywords.query(
                    session,
                    generation_id=generation_id,
                    query=query,
                    top_k=config.keyword.top_k,
                    score_threshold=config.keyword.score_threshold,
                    candidate_limit=config.keyword.top_k,
                )
            except SQLAlchemyError as error:
                raise RetrievalExecutionError("KEYWORD_STORE_UNAVAILABLE") from error
            except (OSError, RuntimeError, ValueError) as error:
                raise RetrievalExecutionError("KEYWORD_STORE_UNAVAILABLE") from error

        if config.retrieval_type == "vector":
            candidates = rank_single_route(
                vector_hits,
                (),
                final_top_k=config.final_top_k,
                final_score_threshold=config.fusion.final_score_threshold,
            )
        elif config.retrieval_type == "keyword":
            candidates = rank_single_route(
                (),
                keyword_hits,
                final_top_k=config.final_top_k,
                final_score_threshold=config.fusion.final_score_threshold,
            )
        elif config.retrieval_type == "hybrid":
            candidates = fuse_candidates(
                vector_hits,
                keyword_hits,
                strategy=config.fusion.strategy,
                rrf_k=config.fusion.rrf_k,
                vector_weight=config.fusion.vector_weight,
                keyword_weight=config.fusion.keyword_weight,
                final_top_k=config.final_top_k,
                final_score_threshold=config.fusion.final_score_threshold,
            )
        else:
            raise RetrievalExecutionError("RETRIEVAL_CONFIG_INVALID")
        return RetrievalResult(
            candidates=candidates,
            retrieval_type=config.retrieval_type,
            vector_candidate_count=len(vector_hits),
            keyword_candidate_count=len(keyword_hits),
        )
