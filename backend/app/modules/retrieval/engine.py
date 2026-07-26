from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.modules.knowledge_bases.domain import RetrievalConfig
from app.modules.models.adapters import ModelProviderError
from app.modules.retrieval.context import ContextStore, RetrievedContext, expand_context
from app.modules.retrieval.fusion import (
    RetrievalCandidate,
    fuse_candidates,
    rank_single_route,
)
from app.modules.retrieval.keyword_store import KeywordHit, KeywordStoreAdapter
from app.modules.retrieval.reranking import RerankError, RerankService
from app.modules.retrieval.vector_store import VectorHit, VectorStoreAdapter


class QueryEmbeddingPort(Protocol):
    def embed_query(self, query: str) -> tuple[float, ...]: ...


@dataclass(frozen=True)
class RetrievalResult:
    candidates: tuple[RetrievalCandidate, ...]
    retrieval_type: str
    vector_candidate_count: int
    keyword_candidate_count: int
    contexts: tuple[RetrievedContext, ...] = ()
    rerank_applied: bool = False
    rerank_degraded: bool = False
    warnings: tuple[str, ...] = ()


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
        *,
        reranker: RerankService | None = None,
        context_store: ContextStore | None = None,
    ) -> None:
        self._vectors = vectors
        self._keywords = keywords
        self._query_embedder = query_embedder
        self._reranker = reranker
        self._context_store = context_store

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
        pre_rerank_top_k = _pre_rerank_top_k(config)
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
                        top_k=max(config.vector.top_k, pre_rerank_top_k),
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
                    top_k=max(config.keyword.top_k, pre_rerank_top_k),
                    score_threshold=config.keyword.score_threshold,
                    candidate_limit=max(config.keyword.top_k, pre_rerank_top_k),
                )
            except SQLAlchemyError as error:
                raise RetrievalExecutionError("KEYWORD_STORE_UNAVAILABLE") from error
            except (OSError, RuntimeError, ValueError) as error:
                raise RetrievalExecutionError("KEYWORD_STORE_UNAVAILABLE") from error

        if config.retrieval_type == "vector":
            candidates = rank_single_route(
                vector_hits,
                (),
                final_top_k=pre_rerank_top_k,
                final_score_threshold=config.fusion.final_score_threshold,
            )
        elif config.retrieval_type == "keyword":
            candidates = rank_single_route(
                (),
                keyword_hits,
                final_top_k=pre_rerank_top_k,
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
                final_top_k=pre_rerank_top_k,
                final_score_threshold=config.fusion.final_score_threshold,
            )
        else:
            raise RetrievalExecutionError("RETRIEVAL_CONFIG_INVALID")
        rerank_applied = False
        rerank_degraded = False
        warnings: tuple[str, ...] = ()
        if config.rerank.code != "off":
            if self._reranker is None:
                raise RetrievalExecutionError("RERANK_CONFIG_INVALID")
            try:
                rerank_result = self._reranker.apply(
                    query,
                    candidates,
                    code=config.rerank.code,
                    model_id=config.rerank.model_id,
                    params=config.rerank.params,
                )
            except RerankError as error:
                raise RetrievalExecutionError(error.code) from error
            candidates = rerank_result.candidates[: config.final_top_k]
            rerank_applied = rerank_result.applied
            rerank_degraded = rerank_result.degraded
            if rerank_result.warning_code is not None:
                warnings = (rerank_result.warning_code,)

        contexts: tuple[RetrievedContext, ...] = ()
        if self._context_store is not None:
            try:
                chunks = self._context_store.load_context_chunks(
                    session,
                    generation_id=generation_id,
                    candidates=candidates,
                    context_window=config.context_window,
                )
                contexts = expand_context(
                    candidates,
                    chunks,
                    context_window=config.context_window,
                )
            except RetrievalExecutionError:
                raise
            except (OSError, RuntimeError, ValueError) as error:
                raise RetrievalExecutionError("CONTEXT_STORE_UNAVAILABLE") from error

        return RetrievalResult(
            candidates=candidates,
            retrieval_type=config.retrieval_type,
            vector_candidate_count=len(vector_hits),
            keyword_candidate_count=len(keyword_hits),
            contexts=contexts,
            rerank_applied=rerank_applied,
            rerank_degraded=rerank_degraded,
            warnings=warnings,
        )


def _pre_rerank_top_k(config: RetrievalConfig) -> int:
    if config.rerank.code == "off":
        return config.final_top_k
    candidate_limit = config.rerank.params.get("candidateLimit")
    if isinstance(candidate_limit, int) and not isinstance(candidate_limit, bool):
        return max(config.final_top_k, candidate_limit)
    return config.final_top_k
