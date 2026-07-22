"""Add source upload and parsing persistence.

Revision ID: 0003_source_parsing
Revises: 0002_models_and_mineru_settings
Create Date: 2026-07-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_source_parsing"
down_revision: str | None = "0002_models_and_mineru_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SHA256_PATTERN = "^[0-9a-f]{64}$"
PARSE_STATUSES = (
    "'queued', 'submitting', 'uploading', 'provider_pending', 'parsing', "
    "'downloading', 'normalizing', 'succeeded', 'degraded', 'failed', 'cancelled'"
)
FEATURE_FLAG_KEYS = (
    "'hasText', 'hasPages', 'hasHeadings', 'hasBoundingBoxes', "
    "'hasAssets', 'hasTables', 'hasFormulas'"
)
FEATURE_FLAGS_DEFAULT = (
    '\'{"hasText": false, "hasPages": false, "hasHeadings": false, '
    '"hasBoundingBoxes": false, "hasAssets": false, "hasTables": false, '
    '"hasFormulas": false}\'::jsonb'
)


def create_source_blobs() -> None:
    op.create_table(
        "source_blobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.Text(), nullable=False),
        sa.Column("reference_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "last_referenced_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("purge_after", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "reference_count >= 0",
            name=op.f("source_blobs_reference_count_nonnegative_ck"),
        ),
        sa.CheckConstraint(
            f"sha256 ~ '{SHA256_PATTERN}'",
            name=op.f("source_blobs_sha256_valid_ck"),
        ),
        sa.CheckConstraint(
            "size_bytes >= 0",
            name=op.f("source_blobs_size_bytes_nonnegative_ck"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("source_blobs_pkey")),
        sa.UniqueConstraint("sha256", name=op.f("source_blobs_sha256_uq")),
        sa.UniqueConstraint("storage_key", name=op.f("source_blobs_storage_key_uq")),
    )


def create_data_sources() -> None:
    op.create_table(
        "data_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_blob_id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("original_file_name", sa.Text(), nullable=False),
        sa.Column("extension", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("origin_type", sa.Text(), nullable=False),
        sa.Column(
            "origin_ref",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "jsonb_typeof(origin_ref) = 'object'",
            name=op.f("data_sources_origin_ref_object_ck"),
        ),
        sa.CheckConstraint(
            "origin_type IN ('admin_upload', 'channel_ingest', 'future_connector')",
            name=op.f("data_sources_origin_type_valid_ck"),
        ),
        sa.CheckConstraint("revision >= 1", name=op.f("data_sources_revision_positive_ck")),
        sa.CheckConstraint(
            f"sha256 ~ '{SHA256_PATTERN}'",
            name=op.f("data_sources_sha256_valid_ck"),
        ),
        sa.CheckConstraint(
            "size_bytes >= 0",
            name=op.f("data_sources_size_bytes_nonnegative_ck"),
        ),
        sa.ForeignKeyConstraint(
            ["source_blob_id"],
            ["source_blobs.id"],
            name=op.f("data_sources_source_blob_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("data_sources_pkey")),
    )
    op.create_index(
        "data_sources_display_name_trgm_idx",
        "data_sources",
        [sa.func.lower(sa.column("display_name")).label("display_name_lower")],
        postgresql_using="gin",
        postgresql_ops={"display_name_lower": "gin_trgm_ops"},
    )
    op.create_index("data_sources_sha256_idx", "data_sources", ["sha256"])
    op.create_index(
        "data_sources_origin_created_idx",
        "data_sources",
        ["origin_type", sa.text("created_at DESC")],
    )


def _feature_flags_check() -> str:
    boolean_checks = " AND ".join(
        f"jsonb_typeof(feature_flags -> {key}) = 'boolean'"
        for key in (
            "'hasText'",
            "'hasPages'",
            "'hasHeadings'",
            "'hasBoundingBoxes'",
            "'hasAssets'",
            "'hasTables'",
            "'hasFormulas'",
        )
    )
    return (
        "jsonb_typeof(feature_flags) = 'object' "
        f"AND feature_flags ?& ARRAY[{FEATURE_FLAG_KEYS}] "
        f"AND (feature_flags - ARRAY[{FEATURE_FLAG_KEYS}]) = '{{}}'::jsonb "
        f"AND {boolean_checks}"
    )


def create_parsed_source_versions() -> None:
    op.create_table(
        "parsed_source_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("data_source_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("parser_code", sa.Text(), nullable=False),
        sa.Column("parser_version", sa.Text(), nullable=False),
        sa.Column("normalizer_version", sa.Text(), nullable=False),
        sa.Column("config_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("config_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("source_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("quality_level", sa.Text(), nullable=True),
        sa.Column("progress_current", sa.Integer(), nullable=True),
        sa.Column("progress_total", sa.Integer(), nullable=True),
        sa.Column("progress_unit", sa.Text(), nullable=True),
        sa.Column("provider_batch_id", sa.Text(), nullable=True),
        sa.Column("provider_task_id", sa.Text(), nullable=True),
        sa.Column("provider_data_id", sa.Text(), nullable=True),
        sa.Column("provider_trace_id", sa.Text(), nullable=True),
        sa.Column("raw_result_storage_key", sa.Text(), nullable=True),
        sa.Column("normalized_storage_key", sa.Text(), nullable=True),
        sa.Column("page_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("block_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("asset_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "markdown_char_count", sa.BigInteger(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "feature_flags",
            postgresql.JSONB(),
            server_default=sa.text(FEATURE_FLAGS_DEFAULT),
            nullable=False,
        ),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retryable", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("operation_id", sa.Uuid(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "asset_count >= 0 AND block_count >= 0 AND page_count >= 0 "
            "AND markdown_char_count >= 0",
            name=op.f("parsed_source_versions_counts_nonnegative_ck"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(config_snapshot) = 'object'",
            name=op.f("parsed_source_versions_config_snapshot_object_ck"),
        ),
        sa.CheckConstraint(
            f"config_hash ~ '{SHA256_PATTERN}'",
            name=op.f("parsed_source_versions_config_hash_valid_ck"),
        ),
        sa.CheckConstraint(
            _feature_flags_check(),
            name=op.f("parsed_source_versions_feature_flags_valid_ck"),
        ),
        sa.CheckConstraint(
            "(progress_current IS NULL AND progress_total IS NULL) OR "
            "(progress_current IS NOT NULL AND progress_total IS NOT NULL "
            "AND progress_current >= 0 AND progress_total > 0 "
            "AND progress_current <= progress_total)",
            name=op.f("parsed_source_versions_progress_valid_ck"),
        ),
        sa.CheckConstraint(
            "quality_level IS NULL OR quality_level IN ('full', 'degraded')",
            name=op.f("parsed_source_versions_quality_level_valid_ck"),
        ),
        sa.CheckConstraint(
            f"source_sha256 ~ '{SHA256_PATTERN}'",
            name=op.f("parsed_source_versions_source_sha256_valid_ck"),
        ),
        sa.CheckConstraint(
            f"status IN ({PARSE_STATUSES})",
            name=op.f("parsed_source_versions_status_valid_ck"),
        ),
        sa.CheckConstraint(
            "version_number >= 1",
            name=op.f("parsed_source_versions_version_number_positive_ck"),
        ),
        sa.ForeignKeyConstraint(
            ["data_source_id"],
            ["data_sources.id"],
            name=op.f("parsed_source_versions_data_source_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["operations.id"],
            name=op.f("parsed_source_versions_operation_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("parsed_source_versions_pkey")),
        sa.UniqueConstraint(
            "data_source_id",
            "version_number",
            name=op.f("parsed_source_versions_data_source_version_uq"),
        ),
    )
    op.create_index(
        "parsed_source_versions_reuse_idx",
        "parsed_source_versions",
        ["source_sha256", "parser_code", "parser_version", "config_hash", "status"],
    )


def create_parsed_content() -> None:
    op.create_table(
        "parsed_blocks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("parsed_source_version_id", sa.Uuid(), nullable=False),
        sa.Column("block_type", sa.Text(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("text_content", sa.Text(), nullable=True),
        sa.Column("markdown_content", sa.Text(), nullable=True),
        sa.Column("heading_level", sa.Integer(), nullable=True),
        sa.Column("heading_path", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("bounding_box", postgresql.JSONB(), nullable=True),
        sa.Column("raw_locator", postgresql.JSONB(), nullable=True),
        sa.Column("content_hash", sa.CHAR(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            f"content_hash ~ '{SHA256_PATTERN}'",
            name=op.f("parsed_blocks_content_hash_valid_ck"),
        ),
        sa.CheckConstraint(
            "order_index >= 0",
            name=op.f("parsed_blocks_order_index_nonnegative_ck"),
        ),
        sa.ForeignKeyConstraint(
            ["parsed_source_version_id"],
            ["parsed_source_versions.id"],
            name=op.f("parsed_blocks_parsed_source_version_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("parsed_blocks_pkey")),
        sa.UniqueConstraint(
            "parsed_source_version_id",
            "order_index",
            name=op.f("parsed_blocks_version_order_uq"),
        ),
    )
    op.create_index(
        "parsed_blocks_version_page_order_idx",
        "parsed_blocks",
        ["parsed_source_version_id", "page_number", "order_index"],
    )

    op.create_table(
        "parsed_assets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("parsed_source_version_id", sa.Uuid(), nullable=False),
        sa.Column("asset_type", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.Text(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("bounding_box", postgresql.JSONB(), nullable=True),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("ocr_text", sa.Text(), nullable=True),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "order_index >= 0",
            name=op.f("parsed_assets_order_index_nonnegative_ck"),
        ),
        sa.CheckConstraint(
            f"sha256 ~ '{SHA256_PATTERN}'",
            name=op.f("parsed_assets_sha256_valid_ck"),
        ),
        sa.CheckConstraint(
            "size_bytes >= 0",
            name=op.f("parsed_assets_size_bytes_nonnegative_ck"),
        ),
        sa.ForeignKeyConstraint(
            ["parsed_source_version_id"],
            ["parsed_source_versions.id"],
            name=op.f("parsed_assets_parsed_source_version_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("parsed_assets_pkey")),
    )

    op.create_table(
        "parsed_block_assets",
        sa.Column("block_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["parsed_assets.id"],
            name=op.f("parsed_block_assets_asset_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["block_id"],
            ["parsed_blocks.id"],
            name=op.f("parsed_block_assets_block_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("block_id", "asset_id", name=op.f("parsed_block_assets_pkey")),
    )

    op.create_table(
        "parsed_artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("parsed_source_version_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_type", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("is_downloadable", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            f"sha256 ~ '{SHA256_PATTERN}'",
            name=op.f("parsed_artifacts_sha256_valid_ck"),
        ),
        sa.CheckConstraint(
            "size_bytes >= 0",
            name=op.f("parsed_artifacts_size_bytes_nonnegative_ck"),
        ),
        sa.ForeignKeyConstraint(
            ["parsed_source_version_id"],
            ["parsed_source_versions.id"],
            name=op.f("parsed_artifacts_parsed_source_version_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("parsed_artifacts_pkey")),
    )


def upgrade() -> None:
    create_source_blobs()
    create_data_sources()
    create_parsed_source_versions()
    create_parsed_content()


def downgrade() -> None:
    op.drop_table("parsed_artifacts")
    op.drop_table("parsed_block_assets")
    op.drop_table("parsed_assets")
    op.drop_index("parsed_blocks_version_page_order_idx", table_name="parsed_blocks")
    op.drop_table("parsed_blocks")
    op.drop_index("parsed_source_versions_reuse_idx", table_name="parsed_source_versions")
    op.drop_table("parsed_source_versions")
    op.drop_index("data_sources_origin_created_idx", table_name="data_sources")
    op.drop_index("data_sources_sha256_idx", table_name="data_sources")
    op.drop_index("data_sources_display_name_trgm_idx", table_name="data_sources")
    op.drop_table("data_sources")
    op.drop_table("source_blobs")
