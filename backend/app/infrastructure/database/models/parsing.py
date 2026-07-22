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


class SourceBlobModel(Base):
    __tablename__ = "source_blobs"
    __table_args__ = (
        CheckConstraint(f"sha256 ~ '{SHA256_PATTERN}'", name="sha256_valid"),
        CheckConstraint("size_bytes >= 0", name="size_bytes_nonnegative"),
        CheckConstraint("reference_count >= 0", name="reference_count_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False, unique=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    reference_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    last_referenced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    purge_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DataSourceModel(Base):
    __tablename__ = "data_sources"
    __table_args__ = (
        CheckConstraint(
            "origin_type IN ('admin_upload', 'channel_ingest', 'future_connector')",
            name="origin_type_valid",
        ),
        CheckConstraint("jsonb_typeof(origin_ref) = 'object'", name="origin_ref_object"),
        CheckConstraint(f"sha256 ~ '{SHA256_PATTERN}'", name="sha256_valid"),
        CheckConstraint("size_bytes >= 0", name="size_bytes_nonnegative"),
        CheckConstraint("revision >= 1", name="revision_positive"),
        Index("data_sources_sha256_idx", "sha256"),
        Index("data_sources_origin_created_idx", "origin_type", text("created_at DESC")),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_blob_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_blobs.id", ondelete="RESTRICT"), nullable=False
    )
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    original_file_name: Mapped[str] = mapped_column(Text, nullable=False)
    extension: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    origin_type: Mapped[str] = mapped_column(Text, nullable=False)
    origin_ref: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
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


Index(
    "data_sources_display_name_trgm_idx",
    func.lower(DataSourceModel.display_name).label("display_name_lower"),
    postgresql_using="gin",
    postgresql_ops={"display_name_lower": "gin_trgm_ops"},
)


class ParsedSourceVersionModel(Base):
    __tablename__ = "parsed_source_versions"
    __table_args__ = (
        CheckConstraint("version_number >= 1", name="version_number_positive"),
        CheckConstraint(f"config_hash ~ '{SHA256_PATTERN}'", name="config_hash_valid"),
        CheckConstraint(f"source_sha256 ~ '{SHA256_PATTERN}'", name="source_sha256_valid"),
        CheckConstraint(f"status IN ({PARSE_STATUSES})", name="status_valid"),
        CheckConstraint(
            "quality_level IS NULL OR quality_level IN ('full', 'degraded')",
            name="quality_level_valid",
        ),
        CheckConstraint("jsonb_typeof(config_snapshot) = 'object'", name="config_snapshot_object"),
        CheckConstraint(_feature_flags_check(), name="feature_flags_valid"),
        CheckConstraint(
            "(progress_current IS NULL AND progress_total IS NULL) OR "
            "(progress_current IS NOT NULL AND progress_total IS NOT NULL "
            "AND progress_current >= 0 AND progress_total > 0 "
            "AND progress_current <= progress_total)",
            name="progress_valid",
        ),
        CheckConstraint(
            "asset_count >= 0 AND block_count >= 0 AND page_count >= 0 "
            "AND markdown_char_count >= 0",
            name="counts_nonnegative",
        ),
        UniqueConstraint(
            "data_source_id",
            "version_number",
            name="parsed_source_versions_data_source_version_uq",
        ),
        Index(
            "parsed_source_versions_reuse_idx",
            "source_sha256",
            "parser_code",
            "parser_version",
            "config_hash",
            "status",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    data_source_id: Mapped[UUID] = mapped_column(
        ForeignKey("data_sources.id", ondelete="RESTRICT"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    parser_code: Mapped[str] = mapped_column(Text, nullable=False)
    parser_version: Mapped[str] = mapped_column(Text, nullable=False)
    normalizer_version: Mapped[str] = mapped_column(Text, nullable=False)
    config_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    config_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    source_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    quality_level: Mapped[str | None] = mapped_column(Text)
    progress_current: Mapped[int | None] = mapped_column(Integer)
    progress_total: Mapped[int | None] = mapped_column(Integer)
    progress_unit: Mapped[str | None] = mapped_column(Text)
    provider_batch_id: Mapped[str | None] = mapped_column(Text)
    provider_task_id: Mapped[str | None] = mapped_column(Text)
    provider_data_id: Mapped[str | None] = mapped_column(Text)
    provider_trace_id: Mapped[str | None] = mapped_column(Text)
    raw_result_storage_key: Mapped[str | None] = mapped_column(Text)
    normalized_storage_key: Mapped[str | None] = mapped_column(Text)
    page_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    block_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    asset_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    markdown_char_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=text("0")
    )
    feature_flags: Mapped[dict[str, bool]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text(FEATURE_FLAGS_DEFAULT),
    )
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    retryable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    operation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("operations.id", ondelete="RESTRICT")
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )


class ParsedBlockModel(Base):
    __tablename__ = "parsed_blocks"
    __table_args__ = (
        CheckConstraint("order_index >= 0", name="order_index_nonnegative"),
        CheckConstraint(f"content_hash ~ '{SHA256_PATTERN}'", name="content_hash_valid"),
        UniqueConstraint(
            "parsed_source_version_id",
            "order_index",
            name="parsed_blocks_version_order_uq",
        ),
        Index(
            "parsed_blocks_version_page_order_idx",
            "parsed_source_version_id",
            "page_number",
            "order_index",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    parsed_source_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("parsed_source_versions.id", ondelete="RESTRICT"), nullable=False
    )
    block_type: Mapped[str] = mapped_column(Text, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text_content: Mapped[str | None] = mapped_column(Text)
    markdown_content: Mapped[str | None] = mapped_column(Text)
    heading_level: Mapped[int | None] = mapped_column(Integer)
    heading_path: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    page_number: Mapped[int | None] = mapped_column(Integer)
    bounding_box: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    raw_locator: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    content_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )


class ParsedAssetModel(Base):
    __tablename__ = "parsed_assets"
    __table_args__ = (
        CheckConstraint("order_index >= 0", name="order_index_nonnegative"),
        CheckConstraint(f"sha256 ~ '{SHA256_PATTERN}'", name="sha256_valid"),
        CheckConstraint("size_bytes >= 0", name="size_bytes_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    parsed_source_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("parsed_source_versions.id", ondelete="RESTRICT"), nullable=False
    )
    asset_type: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    bounding_box: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    caption: Mapped[str | None] = mapped_column(Text)
    ocr_text: Mapped[str | None] = mapped_column(Text)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )


class ParsedBlockAssetModel(Base):
    __tablename__ = "parsed_block_assets"

    block_id: Mapped[UUID] = mapped_column(
        ForeignKey("parsed_blocks.id", ondelete="RESTRICT"), primary_key=True
    )
    asset_id: Mapped[UUID] = mapped_column(
        ForeignKey("parsed_assets.id", ondelete="RESTRICT"), primary_key=True
    )


class ParsedArtifactModel(Base):
    __tablename__ = "parsed_artifacts"
    __table_args__ = (
        CheckConstraint(f"sha256 ~ '{SHA256_PATTERN}'", name="sha256_valid"),
        CheckConstraint("size_bytes >= 0", name="size_bytes_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    parsed_source_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("parsed_source_versions.id", ondelete="RESTRICT"), nullable=False
    )
    artifact_type: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    is_downloadable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
