from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.modules.capabilities.registry import BUILTIN_TEXT_EXTENSIONS, MINERU_EXTENSIONS
from app.modules.parsing.settings_domain import ParseConfig

PARSER_VERSION = "1"
NORMALIZER_VERSION = "1"
ALLOWED_EXTRA_FORMATS = frozenset({"json", "markdown"})


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
class ParseTaskSnapshot:
    operation_id: UUID
    version_id: UUID
    parser_code: str
    parser_version: str
    extension: str
    source_storage_key: str


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
        bounds = part.split("-", 1)
        if not all(bound.isdigit() and int(bound) >= 1 for bound in bounds):
            raise ValueError("invalid page range")
        if len(bounds) == 2 and int(bounds[0]) > int(bounds[1]):
            raise ValueError("invalid page range")
        normalized.append("-".join(str(int(bound)) for bound in bounds))
    if not normalized:
        raise ValueError("invalid page range")
    return ",".join(normalized)
