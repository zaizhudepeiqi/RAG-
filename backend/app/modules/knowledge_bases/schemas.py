from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.core.schemas import ApiModel
from app.modules.knowledge_bases.domain import (
    BuildConfig,
    FusionConfig,
    KeywordConfig,
    KnowledgeBaseDetails,
    QueryRewriteConfig,
    RerankConfig,
    RetrievalConfig,
    VectorConfig,
)
from app.modules.tasks.schemas import OperationRef


class KnowledgeBaseBuildConfigDto(ApiModel):
    embedding_model_id: UUID
    embedding_params: dict[str, object] = Field(default_factory=dict)
    vector_store_code: str
    vector_index_code: str
    vector_index_params: dict[str, object] = Field(default_factory=dict)
    keyword_store_code: str
    index_structure: Literal["chunk", "parent_child"]
    index_structure_params: dict[str, object] = Field(default_factory=dict)
    chunk_strategy_code: str
    chunk_params: dict[str, object] = Field(default_factory=dict)


class VectorConfigDto(ApiModel):
    top_k: int
    score_threshold: float


class KeywordConfigDto(ApiModel):
    top_k: int
    score_threshold: float


class HybridConfigDto(ApiModel):
    fusion_strategy: Literal["rrf", "weighted_score"]
    rrf_k: int | None = None
    vector_weight: float | None = None
    keyword_weight: float | None = None
    final_score_threshold: float


class QueryRewriteConfigDto(ApiModel):
    strategy_code: Literal["off", "hyde", "multi_query", "step_back"]
    model_id: UUID | None = None
    params: dict[str, object] = Field(default_factory=dict)


class RerankConfigDto(ApiModel):
    strategy_code: Literal["off", "rerank_model", "llm_rerank"]
    model_id: UUID | None = None
    params: dict[str, object] = Field(default_factory=dict)


class RetrievalConfigDto(ApiModel):
    retrieval_type: Literal["vector", "keyword", "hybrid"]
    vector: VectorConfigDto
    keyword: KeywordConfigDto
    hybrid: HybridConfigDto
    query_rewrite: QueryRewriteConfigDto
    rerank: RerankConfigDto
    context_window: int
    final_top_k: int


class CreateKnowledgeBaseRequest(ApiModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    parsed_source_version_ids: list[UUID] = Field(min_length=1)
    build_config: KnowledgeBaseBuildConfigDto
    retrieval_config: RetrievalConfigDto


class UpdateKnowledgeBaseMetadataRequest(ApiModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    expected_revision: int = Field(ge=1)


class KnowledgeBaseStateRequest(ApiModel):
    expected_revision: int = Field(ge=1)


class KnowledgeBaseSummaryView(ApiModel):
    id: UUID
    name: str
    description: str | None = None
    enabled: bool
    derived_display_status: str
    source_count: int
    searchable_source_count: int
    chunk_count: int
    embedding_model_id: UUID | None = None
    index_structure: str | None = None
    retrieval_type: str | None = None
    bot_reference_count: int
    latest_build_at: datetime | None = None
    updated_at: datetime
    revision: int
    allowed_actions: list[str]


class KnowledgeBaseDetailView(KnowledgeBaseSummaryView):
    active_generation_id: UUID | None = None
    active_retrieval_revision_id: UUID | None = None
    pending_build_config_revision_id: UUID | None = None
    pending_retrieval_revision_id: UUID | None = None
    latest_build_operation_id: UUID | None = None
    latest_generation_id: UUID | None = None
    latest_generation_status: str | None = None
    active_completeness: str | None = None
    generation_count: int
    has_unpublished_build_changes: bool
    created_at: datetime


class KnowledgeBasePageView(ApiModel):
    items: list[KnowledgeBaseSummaryView]
    total: int
    page: int
    page_size: int


class CreateKnowledgeBaseResponse(ApiModel):
    knowledge_base: KnowledgeBaseDetailView
    operation: OperationRef


def build_config_domain(config: KnowledgeBaseBuildConfigDto) -> BuildConfig:
    return BuildConfig(
        embedding_model_id=config.embedding_model_id,
        embedding_params=config.embedding_params,
        vector_store_code=config.vector_store_code,
        vector_store_version="1",
        vector_index_code=config.vector_index_code,
        vector_index_version="1",
        vector_index_params=config.vector_index_params,
        keyword_store_code=config.keyword_store_code,
        keyword_store_version="1",
        index_structure=config.index_structure,
        index_structure_params=config.index_structure_params,
        chunk_strategy_code=config.chunk_strategy_code,
        chunk_strategy_version="1",
        chunk_params=config.chunk_params,
    )


def retrieval_config_domain(config: RetrievalConfigDto) -> RetrievalConfig:
    return RetrievalConfig(
        retrieval_type=config.retrieval_type,
        vector=VectorConfig(config.vector.top_k, config.vector.score_threshold),
        keyword=KeywordConfig(config.keyword.top_k, config.keyword.score_threshold),
        fusion=FusionConfig(
            config.hybrid.fusion_strategy,
            config.hybrid.rrf_k,
            config.hybrid.vector_weight,
            config.hybrid.keyword_weight,
            config.hybrid.final_score_threshold,
        ),
        query_rewrite=QueryRewriteConfig(
            config.query_rewrite.strategy_code,
            config.query_rewrite.model_id,
            config.query_rewrite.params,
        ),
        rerank=RerankConfig(
            config.rerank.strategy_code,
            config.rerank.model_id,
            config.rerank.params,
        ),
        context_window=config.context_window,
        final_top_k=config.final_top_k,
    )


def knowledge_base_summary(details: KnowledgeBaseDetails) -> KnowledgeBaseSummaryView:
    knowledge_base = details.knowledge_base
    runtime = details.runtime
    return KnowledgeBaseSummaryView(
        id=knowledge_base.id,
        name=knowledge_base.name,
        description=knowledge_base.description,
        enabled=knowledge_base.enabled,
        derived_display_status=details.derived_display_status,
        source_count=runtime.source_count,
        searchable_source_count=runtime.successful_source_count,
        chunk_count=runtime.chunk_count,
        embedding_model_id=runtime.embedding_model_id,
        index_structure=runtime.index_structure,
        retrieval_type=runtime.retrieval_type,
        bot_reference_count=runtime.bot_reference_count,
        latest_build_at=runtime.latest_generation_created_at,
        updated_at=knowledge_base.updated_at,
        revision=knowledge_base.revision,
        allowed_actions=list(details.allowed_actions),
    )


def knowledge_base_detail(details: KnowledgeBaseDetails) -> KnowledgeBaseDetailView:
    knowledge_base = details.knowledge_base
    runtime = details.runtime
    summary = knowledge_base_summary(details)
    return KnowledgeBaseDetailView(
        **summary.model_dump(),
        active_generation_id=knowledge_base.active_generation_id,
        active_retrieval_revision_id=knowledge_base.active_retrieval_revision_id,
        pending_build_config_revision_id=knowledge_base.pending_build_config_revision_id,
        pending_retrieval_revision_id=knowledge_base.pending_retrieval_revision_id,
        latest_build_operation_id=knowledge_base.latest_build_operation_id,
        latest_generation_id=runtime.latest_generation_id,
        latest_generation_status=runtime.latest_generation_status,
        active_completeness=runtime.active_completeness,
        generation_count=runtime.generation_count,
        has_unpublished_build_changes=(knowledge_base.pending_build_config_revision_id is not None),
        created_at=knowledge_base.created_at,
    )
