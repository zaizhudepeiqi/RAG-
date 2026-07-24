from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    ARRAY,
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base, utc_now

SHA256_PATTERN = "^[0-9a-f]{64}$"
GENERATION_STATUSES = (
    "'queued', 'building', 'validating', 'succeeded', 'partial_ready', "
    "'partial_failed', 'failed', 'cancelled', 'discarded'"
)
ITEM_STATUSES = (
    "'queued', 'chunking', 'embedding', 'keyword_indexing', "
    "'vector_indexing', 'validating', 'succeeded', 'failed'"
)


class KnowledgeBaseModel(Base):
    __tablename__ = "knowledge_bases"
    __table_args__ = (
        CheckConstraint("char_length(name) BETWEEN 1 AND 100", name="name_length"),
        CheckConstraint("revision >= 1", name="revision_positive"),
        Index(
            "knowledge_bases_name_active_uq",
            func.lower(text("name")),
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("knowledge_bases_updated_id_idx", text("updated_at DESC"), "id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    active_generation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "index_generations.id",
            name="knowledge_bases_active_generation_id_fkey",
            ondelete="RESTRICT",
            use_alter=True,
        )
    )
    active_retrieval_revision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "kb_retrieval_revisions.id",
            name="knowledge_bases_active_retrieval_revision_id_fkey",
            ondelete="RESTRICT",
            use_alter=True,
        )
    )
    pending_build_config_revision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "kb_build_config_revisions.id",
            name="knowledge_bases_pending_build_config_revision_id_fkey",
            ondelete="RESTRICT",
            use_alter=True,
        )
    )
    pending_retrieval_revision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "kb_retrieval_revisions.id",
            name="knowledge_bases_pending_retrieval_revision_id_fkey",
            ondelete="RESTRICT",
            use_alter=True,
        )
    )
    latest_build_operation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("operations.id", ondelete="RESTRICT")
    )
    revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KnowledgeBaseBuildConfigRevisionModel(Base):
    __tablename__ = "kb_build_config_revisions"
    __table_args__ = (
        CheckConstraint("revision_number >= 1", name="revision_number_positive"),
        CheckConstraint(
            "index_structure IN ('chunk', 'parent_child')", name="index_structure_valid"
        ),
        CheckConstraint(f"config_hash ~ '{SHA256_PATTERN}'", name="config_hash_valid"),
        CheckConstraint(
            "jsonb_typeof(embedding_model_snapshot) = 'object'",
            name="embedding_model_snapshot_object",
        ),
        CheckConstraint(
            "jsonb_typeof(embedding_params) = 'object'", name="embedding_params_object"
        ),
        CheckConstraint(
            "jsonb_typeof(vector_index_params) = 'object'", name="vector_index_params_object"
        ),
        CheckConstraint(
            "jsonb_typeof(index_structure_params) = 'object'",
            name="index_structure_params_object",
        ),
        CheckConstraint("jsonb_typeof(chunk_params) = 'object'", name="chunk_params_object"),
        CheckConstraint(
            "jsonb_typeof(token_counter_snapshot) = 'object'",
            name="token_counter_snapshot_object",
        ),
        UniqueConstraint(
            "knowledge_base_id",
            "revision_number",
            name="kb_build_config_revisions_kb_revision_uq",
        ),
        UniqueConstraint(
            "knowledge_base_id",
            "config_hash",
            name="kb_build_config_revisions_kb_hash_uq",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    knowledge_base_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="RESTRICT"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding_model_id: Mapped[UUID] = mapped_column(
        ForeignKey("model_configs.id", ondelete="RESTRICT"), nullable=False
    )
    embedding_model_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    embedding_params: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    vector_store_code: Mapped[str] = mapped_column(Text, nullable=False)
    vector_store_version: Mapped[str] = mapped_column(Text, nullable=False)
    vector_index_code: Mapped[str] = mapped_column(Text, nullable=False)
    vector_index_version: Mapped[str] = mapped_column(Text, nullable=False)
    vector_index_params: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    keyword_store_code: Mapped[str] = mapped_column(Text, nullable=False)
    keyword_store_version: Mapped[str] = mapped_column(Text, nullable=False)
    index_structure: Mapped[str] = mapped_column(Text, nullable=False)
    index_structure_params: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    chunk_strategy_code: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_strategy_version: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_params: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    token_counter_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    config_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )


class KnowledgeBaseBuildConfigSourceModel(Base):
    __tablename__ = "kb_build_config_sources"
    __table_args__ = (
        CheckConstraint("order_index >= 0", name="order_index_nonnegative"),
        UniqueConstraint(
            "config_revision_id",
            "order_index",
            name="kb_build_config_sources_revision_order_uq",
        ),
    )

    config_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("kb_build_config_revisions.id", ondelete="RESTRICT"), primary_key=True
    )
    parsed_source_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("parsed_source_versions.id", ondelete="RESTRICT"), primary_key=True
    )
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )


class KnowledgeBaseRetrievalRevisionModel(Base):
    __tablename__ = "kb_retrieval_revisions"
    __table_args__ = (
        CheckConstraint("revision_number >= 1", name="revision_number_positive"),
        CheckConstraint(
            "retrieval_type IN ('vector', 'keyword', 'hybrid')", name="retrieval_type_valid"
        ),
        CheckConstraint("context_window BETWEEN 0 AND 5", name="context_window_valid"),
        CheckConstraint("final_top_k BETWEEN 1 AND 100", name="final_top_k_valid"),
        CheckConstraint(f"config_hash ~ '{SHA256_PATTERN}'", name="config_hash_valid"),
        CheckConstraint("jsonb_typeof(vector_config) = 'object'", name="vector_config_object"),
        CheckConstraint("jsonb_typeof(keyword_config) = 'object'", name="keyword_config_object"),
        CheckConstraint("jsonb_typeof(fusion_config) = 'object'", name="fusion_config_object"),
        CheckConstraint(
            "jsonb_typeof(query_rewrite_params) = 'object'", name="query_rewrite_params_object"
        ),
        CheckConstraint("jsonb_typeof(rerank_params) = 'object'", name="rerank_params_object"),
        UniqueConstraint(
            "knowledge_base_id",
            "revision_number",
            name="kb_retrieval_revisions_kb_revision_uq",
        ),
        UniqueConstraint(
            "knowledge_base_id",
            "config_hash",
            name="kb_retrieval_revisions_kb_hash_uq",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    knowledge_base_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="RESTRICT"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    retrieval_type: Mapped[str] = mapped_column(Text, nullable=False)
    vector_config: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    keyword_config: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    fusion_config: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    query_rewrite_code: Mapped[str] = mapped_column(Text, nullable=False)
    query_rewrite_version: Mapped[str] = mapped_column(Text, nullable=False)
    query_rewrite_model_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("model_configs.id", ondelete="RESTRICT")
    )
    query_rewrite_params: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    rerank_code: Mapped[str] = mapped_column(Text, nullable=False)
    rerank_version: Mapped[str] = mapped_column(Text, nullable=False)
    rerank_model_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("model_configs.id", ondelete="RESTRICT")
    )
    rerank_params: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    context_window: Mapped[int] = mapped_column(Integer, nullable=False)
    final_top_k: Mapped[int] = mapped_column(Integer, nullable=False)
    config_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )


class IndexGenerationModel(Base):
    __tablename__ = "index_generations"
    __table_args__ = (
        CheckConstraint("generation_number >= 1", name="generation_number_positive"),
        CheckConstraint(f"status IN ({GENERATION_STATUSES})", name="status_valid"),
        CheckConstraint(
            "completeness IS NULL OR completeness IN ('full', 'partial')",
            name="completeness_valid",
        ),
        CheckConstraint(
            "source_count >= 0 AND successful_source_count >= 0 "
            "AND failed_source_count >= 0 AND chunk_count >= 0 AND vector_count >= 0",
            name="counts_nonnegative",
        ),
        CheckConstraint(
            "successful_source_count + failed_source_count <= source_count",
            name="source_counts_consistent",
        ),
        CheckConstraint(
            "jsonb_typeof(validation_report) = 'object'", name="validation_report_object"
        ),
        CheckConstraint("activated_at IS NULL OR is_frozen = true", name="activated_frozen"),
        UniqueConstraint(
            "knowledge_base_id",
            "generation_number",
            name="index_generations_kb_generation_uq",
        ),
        Index(
            "index_generations_kb_status_created_idx",
            "knowledge_base_id",
            "status",
            text("created_at DESC"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    knowledge_base_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="RESTRICT"), nullable=False
    )
    generation_number: Mapped[int] = mapped_column(Integer, nullable=False)
    build_config_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("kb_build_config_revisions.id", ondelete="RESTRICT"), nullable=False
    )
    retrieval_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("kb_retrieval_revisions.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)
    completeness: Mapped[str | None] = mapped_column(Text)
    collection_name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    keyword_namespace: Mapped[UUID] = mapped_column(nullable=False, unique=True)
    source_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    successful_source_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    failed_source_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    chunk_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=text("0")
    )
    vector_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=text("0")
    )
    validation_report: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    operation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("operations.id", ondelete="RESTRICT")
    )
    is_frozen: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retain_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )


class IndexGenerationItemModel(Base):
    __tablename__ = "index_generation_items"
    __table_args__ = (
        CheckConstraint(f"status IN ({ITEM_STATUSES})", name="status_valid"),
        CheckConstraint("chunk_count >= 0 AND vector_count >= 0", name="counts_nonnegative"),
        CheckConstraint("jsonb_typeof(stage_progress) = 'object'", name="stage_progress_object"),
        UniqueConstraint(
            "index_generation_id",
            "parsed_source_version_id",
            name="index_generation_items_generation_source_uq",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    index_generation_id: Mapped[UUID] = mapped_column(
        ForeignKey("index_generations.id", ondelete="RESTRICT"), nullable=False
    )
    parsed_source_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("parsed_source_versions.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)
    stage_progress: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    chunk_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    vector_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    source_copy_from_item_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("index_generation_items.id", ondelete="RESTRICT")
    )
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    retryable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )


class ChunkModel(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        CheckConstraint("chunk_kind IN ('chunk', 'parent', 'child')", name="chunk_kind_valid"),
        CheckConstraint("order_index >= 0", name="order_index_nonnegative"),
        CheckConstraint("token_count >= 0", name="token_count_nonnegative"),
        CheckConstraint(
            f"normalized_text_hash ~ '{SHA256_PATTERN}'", name="normalized_text_hash_valid"
        ),
        CheckConstraint(
            "parent_chunk_id IS NULL OR chunk_kind = 'child'", name="parent_only_for_child"
        ),
        CheckConstraint(
            "bounding_boxes IS NULL OR jsonb_typeof(bounding_boxes) = 'array'",
            name="bounding_boxes_array",
        ),
        UniqueConstraint(
            "index_generation_id",
            "generation_item_id",
            "chunk_kind",
            "order_index",
            name="chunks_generation_item_kind_order_uq",
        ),
        Index("chunks_generation_kind_idx", "index_generation_id", "chunk_kind"),
        Index(
            "chunks_searchable_trgm_idx",
            "searchable_text",
            postgresql_using="gin",
            postgresql_ops={"searchable_text": "gin_trgm_ops"},
        ),
        Index("chunks_source_idx", "parsed_source_version_id", "index_generation_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    index_generation_id: Mapped[UUID] = mapped_column(
        ForeignKey("index_generations.id", ondelete="RESTRICT"), nullable=False
    )
    generation_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("index_generation_items.id", ondelete="RESTRICT"), nullable=False
    )
    parsed_source_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("parsed_source_versions.id", ondelete="RESTRICT"), nullable=False
    )
    chunk_kind: Mapped[str] = mapped_column(Text, nullable=False)
    parent_chunk_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("chunks.id", ondelete="RESTRICT")
    )
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text_content: Mapped[str] = mapped_column(Text, nullable=False)
    searchable_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_text_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    token_counter_code: Mapped[str] = mapped_column(Text, nullable=False)
    token_counter_version: Mapped[str] = mapped_column(Text, nullable=False)
    heading_path: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    page_range: Mapped[list[int] | None] = mapped_column(ARRAY(Integer))
    primary_page_number: Mapped[int | None] = mapped_column(Integer)
    bounding_boxes: Mapped[list[dict[str, object]] | None] = mapped_column(JSONB)
    previous_chunk_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("chunks.id", ondelete="RESTRICT")
    )
    next_chunk_id: Mapped[UUID | None] = mapped_column(ForeignKey("chunks.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )


class ChunkSourceBlockModel(Base):
    __tablename__ = "chunk_source_blocks"
    __table_args__ = (
        CheckConstraint("order_index >= 0", name="order_index_nonnegative"),
        UniqueConstraint("chunk_id", "order_index", name="chunk_source_blocks_chunk_order_uq"),
    )

    chunk_id: Mapped[UUID] = mapped_column(
        ForeignKey("chunks.id", ondelete="RESTRICT"), primary_key=True
    )
    parsed_block_id: Mapped[UUID] = mapped_column(
        ForeignKey("parsed_blocks.id", ondelete="RESTRICT"), primary_key=True
    )
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)


class ChunkAssetModel(Base):
    __tablename__ = "chunk_assets"

    chunk_id: Mapped[UUID] = mapped_column(
        ForeignKey("chunks.id", ondelete="RESTRICT"), primary_key=True
    )
    parsed_asset_id: Mapped[UUID] = mapped_column(
        ForeignKey("parsed_assets.id", ondelete="RESTRICT"), primary_key=True
    )
