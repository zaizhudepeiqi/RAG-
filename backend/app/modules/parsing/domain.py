from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.modules.capabilities.registry import BUILTIN_TEXT_EXTENSIONS, MINERU_EXTENSIONS
from app.modules.parsing.settings_domain import MinerUSettings, ParseConfig

PARSER_VERSION = "1"
NORMALIZER_VERSION = "1"
ALLOWED_EXTRA_FORMATS = frozenset({"docx", "html", "latex"})
PAGE_RANGE_PART = re.compile(r"^(?P<start>\d+)(?:-(?P<end>-?\d+))?$")


class ParseState(StrEnum):
    QUEUED = "queued"
    SUBMITTING = "submitting"
    UPLOADING = "uploading"
    PROVIDER_PENDING = "provider_pending"
    PARSING = "parsing"
    DOWNLOADING = "downloading"
    NORMALIZING = "normalizing"
    SUCCEEDED = "succeeded"
    DEGRADED = "degraded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ParseEvent(StrEnum):
    SUBMIT = "submit"
    UPLOAD = "upload"
    WAIT_PROVIDER = "wait_provider"
    PROVIDER_RUNNING = "provider_running"
    PROVIDER_CONVERTING = "provider_converting"
    DOWNLOAD = "download"
    NORMALIZE = "normalize"
    SUCCEED = "succeed"
    DEGRADE = "degrade"
    FAIL = "fail"
    CANCEL = "cancel"
    DUPLICATE = "duplicate"
    RESUME_PROVIDER_QUERY = "resume_provider_query"


TERMINAL_PARSE_STATES = frozenset(
    {ParseState.SUCCEEDED, ParseState.DEGRADED, ParseState.FAILED, ParseState.CANCELLED}
)
PARSE_TRANSITIONS = {
    (ParseState.QUEUED, ParseEvent.SUBMIT): ParseState.SUBMITTING,
    (ParseState.QUEUED, ParseEvent.NORMALIZE): ParseState.NORMALIZING,
    (ParseState.QUEUED, ParseEvent.CANCEL): ParseState.CANCELLED,
    (ParseState.SUBMITTING, ParseEvent.UPLOAD): ParseState.UPLOADING,
    (ParseState.UPLOADING, ParseEvent.WAIT_PROVIDER): ParseState.PROVIDER_PENDING,
    (ParseState.PROVIDER_PENDING, ParseEvent.PROVIDER_RUNNING): ParseState.PARSING,
    (ParseState.PROVIDER_PENDING, ParseEvent.PROVIDER_CONVERTING): ParseState.PARSING,
    (ParseState.PROVIDER_PENDING, ParseEvent.DOWNLOAD): ParseState.DOWNLOADING,
    (ParseState.PARSING, ParseEvent.PROVIDER_RUNNING): ParseState.PARSING,
    (ParseState.PARSING, ParseEvent.PROVIDER_CONVERTING): ParseState.PARSING,
    (ParseState.PARSING, ParseEvent.DOWNLOAD): ParseState.DOWNLOADING,
    (ParseState.DOWNLOADING, ParseEvent.NORMALIZE): ParseState.NORMALIZING,
    (ParseState.NORMALIZING, ParseEvent.SUCCEED): ParseState.SUCCEEDED,
    (ParseState.NORMALIZING, ParseEvent.DEGRADE): ParseState.DEGRADED,
    (ParseState.FAILED, ParseEvent.RESUME_PROVIDER_QUERY): ParseState.PROVIDER_PENDING,
}


def transition_parse_state(current: ParseState, event: ParseEvent) -> ParseState:
    if event is ParseEvent.DUPLICATE and current in TERMINAL_PARSE_STATES:
        return current
    if event is ParseEvent.FAIL and current not in TERMINAL_PARSE_STATES:
        return ParseState.FAILED
    try:
        return PARSE_TRANSITIONS[(current, event)]
    except KeyError as error:
        raise ValueError("invalid parse state transition") from error


@dataclass
class SourceBlob:
    id: UUID
    sha256: str
    size_bytes: int
    storage_key: str
    mime_type: str
    reference_count: int
    created_at: datetime
    last_referenced_at: datetime
    purge_after: datetime | None


@dataclass
class DataSource:
    id: UUID
    source_blob_id: UUID
    display_name: str
    source_path: str
    original_file_name: str
    extension: str
    mime_type: str
    size_bytes: int
    sha256: str
    origin_type: str
    origin_ref: dict[str, object]
    revision: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


@dataclass(frozen=True)
class DataSourceDetails:
    source: DataSource
    blob: SourceBlob
    version_count: int = 0
    latest_versions: tuple[ParsedSourceVersion, ...] = ()
    references: tuple[ParsingReference, ...] = ()


@dataclass(frozen=True)
class RegisteredUpload:
    details: DataSourceDetails
    duplicate_of_data_source_id: UUID | None


@dataclass
class ParsedSourceVersion:
    id: UUID
    data_source_id: UUID
    version_number: int
    parser_code: str
    parser_version: str
    normalizer_version: str
    config_snapshot: dict[str, object]
    config_hash: str
    source_sha256: str
    status: str
    quality_level: str | None
    progress_current: int | None
    progress_total: int | None
    progress_unit: str | None
    page_count: int
    block_count: int
    asset_count: int
    markdown_char_count: int
    feature_flags: dict[str, bool]
    error_code: str | None
    error_message: str | None
    retryable: bool
    operation_id: UUID | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class ParsedSourceVersionDetails:
    version: ParsedSourceVersion
    provider_batch_id: str | None
    provider_task_id: str | None
    provider_data_id: str | None
    provider_trace_id: str | None
    normalized_storage_key: str | None


@dataclass(frozen=True)
class ParsedBlock:
    id: UUID
    block_type: str
    order_index: int
    text_content: str | None
    markdown_content: str | None
    heading_level: int | None
    heading_path: tuple[str, ...] | None
    page_number: int | None
    bounding_box: dict[str, object] | None
    raw_locator: dict[str, object] | None
    asset_ids: tuple[UUID, ...]


@dataclass(frozen=True)
class ParsedAsset:
    id: UUID
    asset_type: str
    mime_type: str
    page_number: int | None
    bounding_box: dict[str, object] | None
    storage_key: str
    sha256: str
    size_bytes: int
    caption: str | None
    ocr_text: str | None
    order_index: int


@dataclass(frozen=True)
class ParsedArtifact:
    id: UUID
    artifact_type: str
    display_name: str
    storage_key: str
    sha256: str
    size_bytes: int
    is_downloadable: bool
    created_at: datetime


@dataclass(frozen=True)
class ParseTaskSnapshot:
    operation_id: UUID
    version_id: UUID
    parser_code: str
    parser_version: str
    extension: str
    source_storage_key: str
    source_file_name: str
    config_snapshot: dict[str, object]
    status: ParseState
    provider_batch_id: str | None
    provider_task_id: str | None
    provider_data_id: str | None
    provider_trace_id: str | None
    raw_result_storage_key: str | None
    mineru_settings: MinerURuntimeSettings | None


@dataclass(frozen=True)
class MinerURuntimeSettings:
    id: UUID
    base_url: str
    token_ciphertext: bytes | None
    token_nonce: bytes | None
    token_key_version: str | None
    poll_timeout_seconds: int
    cloud_processing_confirmed: bool


@dataclass(frozen=True)
class MinerUTestTaskSnapshot:
    operation_id: UUID
    settings: MinerUSettings


@dataclass(frozen=True)
class ParsingReference:
    knowledge_base_id: UUID
    knowledge_base_name: str
    config_revision_id: UUID
    active: bool


@dataclass(frozen=True)
class ParsingCleanupTaskSnapshot:
    operation_id: UUID
    target_type: str
    target_id: UUID
    version_ids: tuple[UUID, ...]
    storage_keys: tuple[str, ...]
    source_blob_id: UUID | None
    source_blob_storage_key: str | None


@dataclass(frozen=True)
class NormalizedParseConfig:
    parser_code: str
    parser_version: str
    normalizer_version: str
    snapshot: dict[str, object]
    config_hash: str


def normalize_parse_config(
    extension: str,
    requested: ParseConfig,
    *,
    force_new: bool = False,
) -> NormalizedParseConfig:
    extension = extension.casefold()
    if extension in BUILTIN_TEXT_EXTENSIONS:
        snapshot: dict[str, object] = {
            "parserCode": "builtin_text",
            "parserVersion": PARSER_VERSION,
            "normalizerVersion": NORMALIZER_VERSION,
            "modelVersion": "builtin",
        }
        return _normalized(snapshot)
    if extension not in MINERU_EXTENSIONS:
        raise ValueError("source extension has no parser route")

    extra_formats = sorted(set(requested.extra_formats))
    if not set(extra_formats).issubset(ALLOWED_EXTRA_FORMATS):
        raise ValueError("unsupported extra format")
    if extension in {"htm", "html"}:
        snapshot = {
            "parserCode": "mineru_precision_api",
            "parserVersion": PARSER_VERSION,
            "normalizerVersion": NORMALIZER_VERSION,
            "modelVersion": "MinerU-HTML",
            "extraFormats": extra_formats,
            "forceProviderRefresh": force_new or requested.force_provider_refresh,
        }
        return _normalized(snapshot)

    if requested.model_version not in {"pipeline", "vlm"}:
        raise ValueError("unsupported MinerU model version")
    snapshot = {
        "parserCode": "mineru_precision_api",
        "parserVersion": PARSER_VERSION,
        "normalizerVersion": NORMALIZER_VERSION,
        "modelVersion": requested.model_version,
        "language": requested.language.strip(),
        "ocrEnabled": requested.ocr_enabled,
        "tableEnabled": requested.table_enabled,
        "formulaEnabled": requested.formula_enabled,
        "extraFormats": extra_formats,
        "forceProviderRefresh": force_new or requested.force_provider_refresh,
    }
    if not snapshot["language"]:
        raise ValueError("language is required")
    if extension == "pdf" and requested.page_ranges is not None:
        snapshot["pageRanges"] = _normalize_page_ranges(requested.page_ranges)
    return _normalized(snapshot)


def _normalized(snapshot: dict[str, object]) -> NormalizedParseConfig:
    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return NormalizedParseConfig(
        parser_code=str(snapshot["parserCode"]),
        parser_version=PARSER_VERSION,
        normalizer_version=NORMALIZER_VERSION,
        snapshot=snapshot,
        config_hash=hashlib.sha256(canonical.encode("ascii")).hexdigest(),
    )


def _normalize_page_ranges(value: str) -> str:
    normalized: list[str] = []
    for raw_part in value.split(","):
        part = raw_part.strip()
        match = PAGE_RANGE_PART.fullmatch(part)
        if match is None:
            raise ValueError("invalid page range")
        start = int(match.group("start"))
        end_value = match.group("end")
        end = int(end_value) if end_value is not None else None
        if start < 1 or end == 0 or (end is not None and end > 0 and start > end):
            raise ValueError("invalid page range")
        normalized.append(str(start) if end is None else f"{start}-{end}")
    if not normalized:
        raise ValueError("invalid page range")
    return ",".join(normalized)
