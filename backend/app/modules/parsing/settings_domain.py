from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

MINERU_SETTINGS_ID = UUID("00000000-0000-0000-0000-000000000001")
CLOUD_PROCESSING_TERMS_VERSION = "mineru-cloud-v1"
DEFAULT_MINERU_BASE_URL = "https://mineru.net"


@dataclass(frozen=True)
class ParseConfig:
    parser_code: str
    model_version: str
    language: str
    ocr_enabled: bool
    table_enabled: bool
    formula_enabled: bool
    page_ranges: str | None
    extra_formats: tuple[str, ...]
    force_provider_refresh: bool


DEFAULT_PARSE_CONFIG = ParseConfig(
    parser_code="mineru_precision_api",
    model_version="pipeline",
    language="ch",
    ocr_enabled=False,
    table_enabled=True,
    formula_enabled=True,
    page_ranges=None,
    extra_formats=(),
    force_provider_refresh=False,
)


@dataclass
class MinerUSettings:
    id: UUID
    base_url: str
    token_ciphertext: bytes | None
    token_nonce: bytes | None
    token_key_version: str | None
    token_prefix: str | None
    token_revision: int
    default_parse_config: ParseConfig
    poll_timeout_seconds: int
    cloud_processing_confirmed_at: datetime | None
    cloud_processing_confirmed_by: UUID | None
    cloud_processing_terms_version: str | None
    revision: int
    created_at: datetime
    updated_at: datetime


def default_mineru_settings(now: datetime) -> MinerUSettings:
    return MinerUSettings(
        id=MINERU_SETTINGS_ID,
        base_url=DEFAULT_MINERU_BASE_URL,
        token_ciphertext=None,
        token_nonce=None,
        token_key_version=None,
        token_prefix=None,
        token_revision=1,
        default_parse_config=DEFAULT_PARSE_CONFIG,
        poll_timeout_seconds=1800,
        cloud_processing_confirmed_at=None,
        cloud_processing_confirmed_by=None,
        cloud_processing_terms_version=None,
        revision=1,
        created_at=now,
        updated_at=now,
    )


def mineru_token_aad(settings_id: UUID) -> bytes:
    return f"mineru-settings:{settings_id}:credential:v1".encode("ascii")


def mask_token(value: str) -> str:
    if len(value) < 8:
        return "****"
    return f"{value[:4]}...{value[-4:]}"
