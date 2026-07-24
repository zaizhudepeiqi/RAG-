"""Add knowledge base configuration, generations, and chunks.

Revision ID: 0004_knowledge_retrieval
Revises: 0003_source_parsing
Create Date: 2026-07-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_knowledge_retrieval"
down_revision: str | None = "0003_source_parsing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SHA256_PATTERN = "^[0-9a-f]{64}$"
GENERATION_STATUSES = (
    "'queued', 'building', 'validating', 'succeeded', 'partial_ready', "
    "'partial_failed', 'failed', 'cancelled', 'discarded'"
)
ITEM_STATUSES = (
    "'queued', 'chunking', 'embedding', 'keyword_indexing', "
    "'vector_indexing', 'validating', 'succeeded', 'failed'"
)


def _timestamps(*, deleted: bool = False) -> list[sa.Column[object]]:
    columns: list[sa.Column[object]] = [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        )
    ]
    if deleted:
        columns.extend(
            [
                sa.Column(
                    "updated_at",
                    sa.DateTime(timezone=True),
                    server_default=sa.func.now(),
                    nullable=False,
                ),
                sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            ]
        )
    return columns


def create_knowledge_bases() -> None:
    op.create_table(
        "knowledge_bases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("active_generation_id", sa.Uuid(), nullable=True),
        sa.Column("active_retrieval_revision_id", sa.Uuid(), nullable=True),
        sa.Column("pending_build_config_revision_id", sa.Uuid(), nullable=True),
        sa.Column("pending_retrieval_revision_id", sa.Uuid(), nullable=True),
        sa.Column("latest_build_operation_id", sa.Uuid(), nullable=True),
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
        *_timestamps(deleted=True),
        sa.CheckConstraint(
            "char_length(name) BETWEEN 1 AND 100",
            name=op.f("knowledge_bases_name_length_ck"),
        ),
        sa.CheckConstraint("revision >= 1", name=op.f("knowledge_bases_revision_positive_ck")),
        sa.ForeignKeyConstraint(
            ["latest_build_operation_id"],
            ["operations.id"],
            name=op.f("knowledge_bases_latest_build_operation_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("knowledge_bases_pkey")),
    )
    op.create_index(
        "knowledge_bases_name_active_uq",
        "knowledge_bases",
        [sa.text("lower(name)")],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "knowledge_bases_updated_id_idx",
        "knowledge_bases",
        [sa.text("updated_at DESC"), "id"],
    )


def create_config_revisions() -> None:
    json_object_checks = (
        "embedding_model_snapshot",
        "embedding_params",
        "vector_index_params",
        "index_structure_params",
        "chunk_params",
        "token_counter_snapshot",
    )
    op.create_table(
        "kb_build_config_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("embedding_model_id", sa.Uuid(), nullable=False),
        sa.Column("embedding_model_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("embedding_params", postgresql.JSONB(), nullable=False),
        sa.Column("vector_store_code", sa.Text(), nullable=False),
        sa.Column("vector_store_version", sa.Text(), nullable=False),
        sa.Column("vector_index_code", sa.Text(), nullable=False),
        sa.Column("vector_index_version", sa.Text(), nullable=False),
        sa.Column("vector_index_params", postgresql.JSONB(), nullable=False),
        sa.Column("keyword_store_code", sa.Text(), nullable=False),
        sa.Column("keyword_store_version", sa.Text(), nullable=False),
        sa.Column("index_structure", sa.Text(), nullable=False),
        sa.Column("index_structure_params", postgresql.JSONB(), nullable=False),
        sa.Column("chunk_strategy_code", sa.Text(), nullable=False),
        sa.Column("chunk_strategy_version", sa.Text(), nullable=False),
        sa.Column("chunk_params", postgresql.JSONB(), nullable=False),
        sa.Column("token_counter_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("config_hash", sa.CHAR(length=64), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "revision_number >= 1",
            name=op.f("kb_build_config_revisions_revision_number_positive_ck"),
        ),
        sa.CheckConstraint(
            "index_structure IN ('chunk', 'parent_child')",
            name=op.f("kb_build_config_revisions_index_structure_valid_ck"),
        ),
        sa.CheckConstraint(
            f"config_hash ~ '{SHA256_PATTERN}'",
            name=op.f("kb_build_config_revisions_config_hash_valid_ck"),
        ),
        *(
            sa.CheckConstraint(
                f"jsonb_typeof({column}) = 'object'",
                name=op.f(f"kb_build_config_revisions_{column}_object_ck"),
            )
            for column in json_object_checks
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"],
            ["knowledge_bases.id"],
            name=op.f("kb_build_config_revisions_knowledge_base_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["embedding_model_id"],
            ["model_configs.id"],
            name=op.f("kb_build_config_revisions_embedding_model_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("kb_build_config_revisions_pkey")),
        sa.UniqueConstraint(
            "knowledge_base_id",
            "revision_number",
            name=op.f("kb_build_config_revisions_kb_revision_uq"),
        ),
        sa.UniqueConstraint(
            "knowledge_base_id",
            "config_hash",
            name=op.f("kb_build_config_revisions_kb_hash_uq"),
        ),
    )
    op.create_table(
        "kb_build_config_sources",
        sa.Column("config_revision_id", sa.Uuid(), nullable=False),
        sa.Column("parsed_source_version_id", sa.Uuid(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "order_index >= 0",
            name=op.f("kb_build_config_sources_order_index_nonnegative_ck"),
        ),
        sa.ForeignKeyConstraint(
            ["config_revision_id"],
            ["kb_build_config_revisions.id"],
            name=op.f("kb_build_config_sources_config_revision_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parsed_source_version_id"],
            ["parsed_source_versions.id"],
            name=op.f("kb_build_config_sources_parsed_source_version_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "config_revision_id",
            "parsed_source_version_id",
            name=op.f("kb_build_config_sources_pkey"),
        ),
        sa.UniqueConstraint(
            "config_revision_id",
            "order_index",
            name=op.f("kb_build_config_sources_revision_order_uq"),
        ),
    )

    retrieval_json_columns = (
        "vector_config",
        "keyword_config",
        "fusion_config",
        "query_rewrite_params",
        "rerank_params",
    )
    op.create_table(
        "kb_retrieval_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("retrieval_type", sa.Text(), nullable=False),
        sa.Column("vector_config", postgresql.JSONB(), nullable=False),
        sa.Column("keyword_config", postgresql.JSONB(), nullable=False),
        sa.Column("fusion_config", postgresql.JSONB(), nullable=False),
        sa.Column("query_rewrite_code", sa.Text(), nullable=False),
        sa.Column("query_rewrite_version", sa.Text(), nullable=False),
        sa.Column("query_rewrite_model_id", sa.Uuid(), nullable=True),
        sa.Column("query_rewrite_params", postgresql.JSONB(), nullable=False),
        sa.Column("rerank_code", sa.Text(), nullable=False),
        sa.Column("rerank_version", sa.Text(), nullable=False),
        sa.Column("rerank_model_id", sa.Uuid(), nullable=True),
        sa.Column("rerank_params", postgresql.JSONB(), nullable=False),
        sa.Column("context_window", sa.Integer(), nullable=False),
        sa.Column("final_top_k", sa.Integer(), nullable=False),
        sa.Column("config_hash", sa.CHAR(length=64), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "revision_number >= 1",
            name=op.f("kb_retrieval_revisions_revision_number_positive_ck"),
        ),
        sa.CheckConstraint(
            "retrieval_type IN ('vector', 'keyword', 'hybrid')",
            name=op.f("kb_retrieval_revisions_retrieval_type_valid_ck"),
        ),
        sa.CheckConstraint(
            "context_window BETWEEN 0 AND 5",
            name=op.f("kb_retrieval_revisions_context_window_valid_ck"),
        ),
        sa.CheckConstraint(
            "final_top_k BETWEEN 1 AND 100",
            name=op.f("kb_retrieval_revisions_final_top_k_valid_ck"),
        ),
        sa.CheckConstraint(
            f"config_hash ~ '{SHA256_PATTERN}'",
            name=op.f("kb_retrieval_revisions_config_hash_valid_ck"),
        ),
        *(
            sa.CheckConstraint(
                f"jsonb_typeof({column}) = 'object'",
                name=op.f(f"kb_retrieval_revisions_{column}_object_ck"),
            )
            for column in retrieval_json_columns
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"],
            ["knowledge_bases.id"],
            name=op.f("kb_retrieval_revisions_knowledge_base_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["query_rewrite_model_id"],
            ["model_configs.id"],
            name=op.f("kb_retrieval_revisions_query_rewrite_model_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["rerank_model_id"],
            ["model_configs.id"],
            name=op.f("kb_retrieval_revisions_rerank_model_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("kb_retrieval_revisions_pkey")),
        sa.UniqueConstraint(
            "knowledge_base_id",
            "revision_number",
            name=op.f("kb_retrieval_revisions_kb_revision_uq"),
        ),
        sa.UniqueConstraint(
            "knowledge_base_id",
            "config_hash",
            name=op.f("kb_retrieval_revisions_kb_hash_uq"),
        ),
    )


def create_generations() -> None:
    op.create_table(
        "index_generations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("generation_number", sa.Integer(), nullable=False),
        sa.Column("build_config_revision_id", sa.Uuid(), nullable=False),
        sa.Column("retrieval_revision_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("completeness", sa.Text(), nullable=True),
        sa.Column("collection_name", sa.Text(), nullable=False),
        sa.Column("keyword_namespace", sa.Uuid(), nullable=False),
        sa.Column("source_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "successful_source_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("failed_source_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("chunk_count", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("vector_count", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "validation_report",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("operation_id", sa.Uuid(), nullable=True),
        sa.Column("is_frozen", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retain_until", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "generation_number >= 1",
            name=op.f("index_generations_generation_number_positive_ck"),
        ),
        sa.CheckConstraint(
            f"status IN ({GENERATION_STATUSES})",
            name=op.f("index_generations_status_valid_ck"),
        ),
        sa.CheckConstraint(
            "completeness IS NULL OR completeness IN ('full', 'partial')",
            name=op.f("index_generations_completeness_valid_ck"),
        ),
        sa.CheckConstraint(
            "source_count >= 0 AND successful_source_count >= 0 "
            "AND failed_source_count >= 0 AND chunk_count >= 0 AND vector_count >= 0",
            name=op.f("index_generations_counts_nonnegative_ck"),
        ),
        sa.CheckConstraint(
            "successful_source_count + failed_source_count <= source_count",
            name=op.f("index_generations_source_counts_consistent_ck"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(validation_report) = 'object'",
            name=op.f("index_generations_validation_report_object_ck"),
        ),
        sa.CheckConstraint(
            "activated_at IS NULL OR is_frozen = true",
            name=op.f("index_generations_activated_frozen_ck"),
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"],
            ["knowledge_bases.id"],
            name=op.f("index_generations_knowledge_base_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["build_config_revision_id"],
            ["kb_build_config_revisions.id"],
            name=op.f("index_generations_build_config_revision_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["retrieval_revision_id"],
            ["kb_retrieval_revisions.id"],
            name=op.f("index_generations_retrieval_revision_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["operations.id"],
            name=op.f("index_generations_operation_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("index_generations_pkey")),
        sa.UniqueConstraint("collection_name", name=op.f("index_generations_collection_name_uq")),
        sa.UniqueConstraint(
            "keyword_namespace",
            name=op.f("index_generations_keyword_namespace_uq"),
        ),
        sa.UniqueConstraint(
            "knowledge_base_id",
            "generation_number",
            name=op.f("index_generations_kb_generation_uq"),
        ),
    )
    op.create_index(
        "index_generations_kb_status_created_idx",
        "index_generations",
        ["knowledge_base_id", "status", sa.text("created_at DESC")],
    )

    op.create_table(
        "index_generation_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("index_generation_id", sa.Uuid(), nullable=False),
        sa.Column("parsed_source_version_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "stage_progress",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("chunk_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("vector_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("source_copy_from_item_id", sa.Uuid(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retryable", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            f"status IN ({ITEM_STATUSES})",
            name=op.f("index_generation_items_status_valid_ck"),
        ),
        sa.CheckConstraint(
            "chunk_count >= 0 AND vector_count >= 0",
            name=op.f("index_generation_items_counts_nonnegative_ck"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(stage_progress) = 'object'",
            name=op.f("index_generation_items_stage_progress_object_ck"),
        ),
        sa.ForeignKeyConstraint(
            ["index_generation_id"],
            ["index_generations.id"],
            name=op.f("index_generation_items_index_generation_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parsed_source_version_id"],
            ["parsed_source_versions.id"],
            name=op.f("index_generation_items_parsed_source_version_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("index_generation_items_pkey")),
        sa.UniqueConstraint(
            "index_generation_id",
            "parsed_source_version_id",
            name=op.f("index_generation_items_generation_source_uq"),
        ),
    )
    op.create_foreign_key(
        op.f("index_generation_items_source_copy_from_item_id_fkey"),
        "index_generation_items",
        "index_generation_items",
        ["source_copy_from_item_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def create_chunks() -> None:
    op.create_table(
        "chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("index_generation_id", sa.Uuid(), nullable=False),
        sa.Column("generation_item_id", sa.Uuid(), nullable=False),
        sa.Column("parsed_source_version_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_kind", sa.Text(), nullable=False),
        sa.Column("parent_chunk_id", sa.Uuid(), nullable=True),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("text_content", sa.Text(), nullable=False),
        sa.Column("searchable_text", sa.Text(), nullable=False),
        sa.Column("normalized_text_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("token_counter_code", sa.Text(), nullable=False),
        sa.Column("token_counter_version", sa.Text(), nullable=False),
        sa.Column("heading_path", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("page_range", postgresql.ARRAY(sa.Integer()), nullable=True),
        sa.Column("primary_page_number", sa.Integer(), nullable=True),
        sa.Column("bounding_boxes", postgresql.JSONB(), nullable=True),
        sa.Column("previous_chunk_id", sa.Uuid(), nullable=True),
        sa.Column("next_chunk_id", sa.Uuid(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "chunk_kind IN ('chunk', 'parent', 'child')",
            name=op.f("chunks_chunk_kind_valid_ck"),
        ),
        sa.CheckConstraint("order_index >= 0", name=op.f("chunks_order_index_nonnegative_ck")),
        sa.CheckConstraint("token_count >= 0", name=op.f("chunks_token_count_nonnegative_ck")),
        sa.CheckConstraint(
            f"normalized_text_hash ~ '{SHA256_PATTERN}'",
            name=op.f("chunks_normalized_text_hash_valid_ck"),
        ),
        sa.CheckConstraint(
            "parent_chunk_id IS NULL OR chunk_kind = 'child'",
            name=op.f("chunks_parent_only_for_child_ck"),
        ),
        sa.CheckConstraint(
            "bounding_boxes IS NULL OR jsonb_typeof(bounding_boxes) = 'array'",
            name=op.f("chunks_bounding_boxes_array_ck"),
        ),
        sa.ForeignKeyConstraint(
            ["index_generation_id"],
            ["index_generations.id"],
            name=op.f("chunks_index_generation_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["generation_item_id"],
            ["index_generation_items.id"],
            name=op.f("chunks_generation_item_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parsed_source_version_id"],
            ["parsed_source_versions.id"],
            name=op.f("chunks_parsed_source_version_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("chunks_pkey")),
        sa.UniqueConstraint(
            "index_generation_id",
            "generation_item_id",
            "chunk_kind",
            "order_index",
            name=op.f("chunks_generation_item_kind_order_uq"),
        ),
    )
    for column in ("parent_chunk_id", "previous_chunk_id", "next_chunk_id"):
        op.create_foreign_key(
            op.f(f"chunks_{column}_fkey"),
            "chunks",
            "chunks",
            [column],
            ["id"],
            ondelete="RESTRICT",
        )
    op.create_index(
        "chunks_generation_kind_idx",
        "chunks",
        ["index_generation_id", "chunk_kind"],
    )
    op.create_index(
        "chunks_searchable_trgm_idx",
        "chunks",
        ["searchable_text"],
        postgresql_using="gin",
        postgresql_ops={"searchable_text": "gin_trgm_ops"},
    )
    op.create_index(
        "chunks_source_idx",
        "chunks",
        ["parsed_source_version_id", "index_generation_id"],
    )

    op.create_table(
        "chunk_source_blocks",
        sa.Column("chunk_id", sa.Uuid(), nullable=False),
        sa.Column("parsed_block_id", sa.Uuid(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "order_index >= 0",
            name=op.f("chunk_source_blocks_order_index_nonnegative_ck"),
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["chunks.id"],
            name=op.f("chunk_source_blocks_chunk_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parsed_block_id"],
            ["parsed_blocks.id"],
            name=op.f("chunk_source_blocks_parsed_block_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "chunk_id", "parsed_block_id", name=op.f("chunk_source_blocks_pkey")
        ),
        sa.UniqueConstraint(
            "chunk_id",
            "order_index",
            name=op.f("chunk_source_blocks_chunk_order_uq"),
        ),
    )
    op.create_table(
        "chunk_assets",
        sa.Column("chunk_id", sa.Uuid(), nullable=False),
        sa.Column("parsed_asset_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["chunks.id"],
            name=op.f("chunk_assets_chunk_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parsed_asset_id"],
            ["parsed_assets.id"],
            name=op.f("chunk_assets_parsed_asset_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("chunk_id", "parsed_asset_id", name=op.f("chunk_assets_pkey")),
    )


def create_delayed_pointers_and_freeze_guard() -> None:
    pointer_targets = (
        ("active_generation_id", "index_generations"),
        ("active_retrieval_revision_id", "kb_retrieval_revisions"),
        ("pending_build_config_revision_id", "kb_build_config_revisions"),
        ("pending_retrieval_revision_id", "kb_retrieval_revisions"),
    )
    for column, target in pointer_targets:
        op.create_foreign_key(
            op.f(f"knowledge_bases_{column}_fkey"),
            "knowledge_bases",
            target,
            [column],
            ["id"],
            ondelete="RESTRICT",
        )

    op.execute(
        """
        CREATE FUNCTION reject_frozen_generation_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
          generation_id uuid;
          target_chunk_id uuid;
        BEGIN
          IF TG_TABLE_NAME = 'index_generation_items' THEN
            generation_id := CASE WHEN TG_OP = 'DELETE'
              THEN OLD.index_generation_id ELSE NEW.index_generation_id END;
          ELSIF TG_TABLE_NAME = 'chunks' THEN
            generation_id := CASE WHEN TG_OP = 'DELETE'
              THEN OLD.index_generation_id ELSE NEW.index_generation_id END;
          ELSE
            target_chunk_id := CASE WHEN TG_OP = 'DELETE'
              THEN OLD.chunk_id ELSE NEW.chunk_id END;
            SELECT index_generation_id INTO generation_id
            FROM chunks WHERE id = target_chunk_id;
          END IF;

          IF EXISTS (
            SELECT 1 FROM index_generations
            WHERE id = generation_id AND is_frozen = true
          ) THEN
            RAISE EXCEPTION 'cannot mutate frozen generation %', generation_id
              USING ERRCODE = '55000';
          END IF;
          IF TG_OP = 'DELETE' THEN
            RETURN OLD;
          END IF;
          RETURN NEW;
        END;
        $$
        """
    )
    for table in ("index_generation_items", "chunks", "chunk_source_blocks", "chunk_assets"):
        op.execute(
            f"""
            CREATE TRIGGER reject_frozen_generation_mutation
            BEFORE INSERT OR UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION reject_frozen_generation_mutation()
            """
        )


def upgrade() -> None:
    create_knowledge_bases()
    create_config_revisions()
    create_generations()
    create_chunks()
    create_delayed_pointers_and_freeze_guard()


def downgrade() -> None:
    for table in ("index_generation_items", "chunks", "chunk_source_blocks", "chunk_assets"):
        op.execute(f"DROP TRIGGER reject_frozen_generation_mutation ON {table}")
    op.execute("DROP FUNCTION reject_frozen_generation_mutation()")

    for column in (
        "active_generation_id",
        "active_retrieval_revision_id",
        "pending_build_config_revision_id",
        "pending_retrieval_revision_id",
    ):
        op.drop_constraint(
            op.f(f"knowledge_bases_{column}_fkey"),
            "knowledge_bases",
            type_="foreignkey",
        )

    op.drop_table("chunk_assets")
    op.drop_table("chunk_source_blocks")
    op.drop_index("chunks_source_idx", table_name="chunks")
    op.drop_index("chunks_searchable_trgm_idx", table_name="chunks")
    op.drop_index("chunks_generation_kind_idx", table_name="chunks")
    op.drop_table("chunks")
    op.drop_table("index_generation_items")
    op.drop_index("index_generations_kb_status_created_idx", table_name="index_generations")
    op.drop_table("index_generations")
    op.drop_table("kb_retrieval_revisions")
    op.drop_table("kb_build_config_sources")
    op.drop_table("kb_build_config_revisions")
    op.drop_index("knowledge_bases_updated_id_idx", table_name="knowledge_bases")
    op.drop_index("knowledge_bases_name_active_uq", table_name="knowledge_bases")
    op.drop_table("knowledge_bases")
