from __future__ import annotations

from app.infrastructure.model_providers.embedding import ConfiguredDocumentEmbedder
from app.infrastructure.retrieval.models import (
    BoundQueryEmbedder,
    ConfiguredRewriteModel,
    ConfiguredTextGenerator,
    LlmRerankAdapter,
    ModelRerankAdapter,
)
from app.modules.knowledge_bases.domain import RetrievalConfig
from app.modules.retrieval.context import ContextStore
from app.modules.retrieval.engine import SingleKnowledgeBaseRetriever
from app.modules.retrieval.keyword_store import KeywordStoreAdapter
from app.modules.retrieval.query_rewrite import QueryRewriteError, QueryRewriteService
from app.modules.retrieval.reranking import RerankService
from app.modules.retrieval.testing import RetrievalTestSnapshot
from app.modules.retrieval.vector_store import VectorStoreAdapter


class RetrievalRuntimeFactory:
    def __init__(
        self,
        document_embedder: ConfiguredDocumentEmbedder,
        text_generator: ConfiguredTextGenerator,
        vectors: VectorStoreAdapter,
        keywords: KeywordStoreAdapter,
        contexts: ContextStore,
    ) -> None:
        self._document_embedder = document_embedder
        self._text_generator = text_generator
        self._vectors = vectors
        self._keywords = keywords
        self._contexts = contexts

    def create_retriever(
        self,
        snapshot: RetrievalTestSnapshot,
        _config: RetrievalConfig,
    ) -> SingleKnowledgeBaseRetriever:
        reranker = RerankService(
            {
                "rerank_model": ModelRerankAdapter(self._text_generator),
                "llm_rerank": LlmRerankAdapter(self._text_generator),
            }
        )
        return SingleKnowledgeBaseRetriever(
            self._vectors,
            self._keywords,
            BoundQueryEmbedder(self._document_embedder, snapshot.build_revision),
            reranker=reranker,
            context_store=self._contexts,
        )

    def create_rewrite_service(self, config: RetrievalConfig) -> QueryRewriteService:
        if config.query_rewrite.code == "off":
            return QueryRewriteService(_OffRewriteModel())
        model_id = config.query_rewrite.model_id
        if model_id is None:
            raise QueryRewriteError("QUERY_REWRITE_CONFIG_INVALID")
        return QueryRewriteService(ConfiguredRewriteModel(self._text_generator, model_id))


class _OffRewriteModel:
    def generate(self, prompt: str, *, max_tokens: int, temperature: float) -> str:
        del prompt, max_tokens, temperature
        raise AssertionError("disabled query rewrite must not invoke a model")
