from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.core.schemas import ApiModel
from app.modules.parsing.domain import (
    DataSourceDetails,
    ParsedSourceVersion,
    RegisteredUpload,
)
from app.modules.parsing.settings_schemas import ParseConfigDto


class UploadOptions(ApiModel):
    origin_type: Literal["admin_upload"] = "admin_upload"
    duplicate_action: Literal["reuse", "create_alias"] = "reuse"


class ParsedFeatureFlagsView(ApiModel):
    has_text: bool
    has_pages: bool
    has_headings: bool
    has_bounding_boxes: bool
    has_assets: bool
    has_tables: bool
    has_formulas: bool


class ParsedSourceVersionSummary(ApiModel):
    id: UUID
    data_source_id: UUID
    version_number: int
    parser_code: str
    parser_version: str
    normalizer_version: str
    config_snapshot: dict[str, object]
    config_hash: str
    status: str
    quality_level: str | None = None
    selectable: bool
    page_count: int
    block_count: int
    asset_count: int
    feature_flags: ParsedFeatureFlagsView
    operation_id: UUID | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    finished_at: datetime | None = None


class DataSourceSummary(ApiModel):
    id: UUID
    display_name: str
    source_path: str
    original_file_name: str
    extension: str
    mime_type: str
    size_bytes: int
    sha256_short: str
    origin_type: str
    latest_parsed_version: ParsedSourceVersionSummary | None = None
    version_count: int
    active_knowledge_base_reference_count: int
    revision: int
    created_at: datetime


class DataSourceReferenceView(ApiModel):
    knowledge_base_id: UUID
    knowledge_base_name: str
    config_revision_id: UUID
    active: bool


class DataSourceDetail(DataSourceSummary):
    sha256: str
    latest_versions: list[ParsedSourceVersionSummary]
    references: list[DataSourceReferenceView]
    deleted_at: datetime | None = None


class DataSourcePageView(ApiModel):
    items: list[DataSourceSummary]
    total: int
    page: int
    page_size: int


class UpdateDataSourceRequest(ApiModel):
    expected_revision: int = Field(ge=1)
    display_name: str = Field(min_length=1, max_length=255)


class UploadedDataSourceView(ApiModel):
    data_source: DataSourceSummary
    duplicate_of_data_source_id: UUID | None = None


class RejectedUploadView(ApiModel):
    file_name: str
    code: str
    message: str


class UploadBatchResult(ApiModel):
    accepted: list[UploadedDataSourceView]
    rejected: list[RejectedUploadView]


class ParseSourceRequest(ApiModel):
    expected_revision: int = Field(ge=1)
    reuse_policy: Literal["reuse_if_exact", "force_new"] = "reuse_if_exact"
    config: ParseConfigDto


class ParseSourceResponse(ApiModel):
    parsed_source_version: ParsedSourceVersionSummary
    reused: bool


def data_source_summary(details: DataSourceDetails) -> DataSourceSummary:
    source = details.source
    latest = details.latest_versions[0] if details.latest_versions else None
    return DataSourceSummary(
        id=source.id,
        display_name=source.display_name,
        source_path=source.source_path,
        original_file_name=source.original_file_name,
        extension=source.extension,
        mime_type=source.mime_type,
        size_bytes=source.size_bytes,
        sha256_short=source.sha256[:12],
        origin_type=source.origin_type,
        latest_parsed_version=(parsed_source_version_summary(latest) if latest else None),
        version_count=details.version_count,
        active_knowledge_base_reference_count=0,
        revision=source.revision,
        created_at=source.created_at,
    )


def data_source_detail(details: DataSourceDetails) -> DataSourceDetail:
    summary = data_source_summary(details)
    return DataSourceDetail(
        **summary.model_dump(),
        sha256=details.source.sha256,
        latest_versions=[parsed_source_version_summary(item) for item in details.latest_versions],
        references=[],
        deleted_at=details.source.deleted_at,
    )


def uploaded_data_source_view(uploaded: RegisteredUpload) -> UploadedDataSourceView:
    return UploadedDataSourceView(
        data_source=data_source_summary(uploaded.details),
        duplicate_of_data_source_id=uploaded.duplicate_of_data_source_id,
    )


def parsed_source_version_summary(
    version: ParsedSourceVersion,
) -> ParsedSourceVersionSummary:
    flags = version.feature_flags
    return ParsedSourceVersionSummary(
        id=version.id,
        data_source_id=version.data_source_id,
        version_number=version.version_number,
        parser_code=version.parser_code,
        parser_version=version.parser_version,
        normalizer_version=version.normalizer_version,
        config_snapshot=version.config_snapshot,
        config_hash=version.config_hash,
        status=version.status,
        quality_level=version.quality_level,
        selectable=version.status in {"succeeded", "degraded"},
        page_count=version.page_count,
        block_count=version.block_count,
        asset_count=version.asset_count,
        feature_flags=ParsedFeatureFlagsView(
            has_text=flags["hasText"],
            has_pages=flags["hasPages"],
            has_headings=flags["hasHeadings"],
            has_bounding_boxes=flags["hasBoundingBoxes"],
            has_assets=flags["hasAssets"],
            has_tables=flags["hasTables"],
            has_formulas=flags["hasFormulas"],
        ),
        operation_id=version.operation_id,
        error_code=version.error_code,
        error_message=version.error_message,
        created_at=version.created_at,
        finished_at=version.finished_at,
    )
