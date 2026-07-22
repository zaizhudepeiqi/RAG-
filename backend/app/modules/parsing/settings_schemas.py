from datetime import datetime
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr

from app.core.schemas import ApiModel
from app.modules.parsing.settings_domain import MinerUSettings, ParseConfig


class ParseConfigDto(ApiModel):
    parser_code: str = Field(min_length=1, max_length=100)
    model_version: str = Field(min_length=1, max_length=100)
    language: str = Field(min_length=1, max_length=50)
    ocr_enabled: bool
    table_enabled: bool
    formula_enabled: bool
    page_ranges: str | None = None
    extra_formats: list[str] = Field(default_factory=list)
    force_provider_refresh: bool


class CloudProcessingConsent(ApiModel):
    accepted: Literal[True]
    terms_version: Literal["mineru-cloud-v1"]


class UpdateMinerUSettingsRequest(ApiModel):
    expected_revision: int = Field(ge=1)
    base_url: AnyHttpUrl
    token: SecretStr | None = None
    default_parse_config: ParseConfigDto
    poll_timeout_seconds: int = Field(ge=300, le=7200)
    cloud_processing_consent: CloudProcessingConsent | None = None


class MinerUSettingsView(ApiModel):
    base_url: str
    token_configured: bool
    token_masked: str | None = None
    default_parse_config: ParseConfigDto
    poll_timeout_seconds: int
    cloud_processing_confirmed_at: datetime | None = None
    terms_version: str | None = None
    revision: int


def parse_config_domain(value: ParseConfigDto) -> ParseConfig:
    return ParseConfig(
        parser_code=value.parser_code,
        model_version=value.model_version,
        language=value.language,
        ocr_enabled=value.ocr_enabled,
        table_enabled=value.table_enabled,
        formula_enabled=value.formula_enabled,
        page_ranges=value.page_ranges,
        extra_formats=tuple(value.extra_formats),
        force_provider_refresh=value.force_provider_refresh,
    )


def mineru_settings_view(settings: MinerUSettings) -> MinerUSettingsView:
    config = settings.default_parse_config
    return MinerUSettingsView(
        base_url=settings.base_url,
        token_configured=settings.token_ciphertext is not None,
        token_masked=settings.token_prefix,
        default_parse_config=ParseConfigDto(
            parser_code=config.parser_code,
            model_version=config.model_version,
            language=config.language,
            ocr_enabled=config.ocr_enabled,
            table_enabled=config.table_enabled,
            formula_enabled=config.formula_enabled,
            page_ranges=config.page_ranges,
            extra_formats=list(config.extra_formats),
            force_provider_refresh=config.force_provider_refresh,
        ),
        poll_timeout_seconds=settings.poll_timeout_seconds,
        cloud_processing_confirmed_at=settings.cloud_processing_confirmed_at,
        terms_version=settings.cloud_processing_terms_version,
        revision=settings.revision,
    )
