from datetime import datetime
from uuid import UUID

from pydantic import AnyHttpUrl, Field, SecretStr

from app.core.schemas import ApiModel
from app.modules.models.domain import ModelProvider, ModelType


class CreateModelProviderRequest(ApiModel):
    provider_type: str
    display_name: str = Field(min_length=1, max_length=200)
    base_url: AnyHttpUrl
    credential: SecretStr = Field(min_length=1)
    supported_model_types: list[ModelType] | None = None


class UpdateModelProviderRequest(ApiModel):
    expected_revision: int = Field(ge=1)
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    credential: SecretStr | None = Field(default=None, min_length=1)


class ModelProviderView(ApiModel):
    id: UUID
    provider_type: str
    display_name: str
    base_url: str
    credential_configured: bool
    credential_masked: str | None = None
    enabled: bool
    model_count: int
    revision: int
    created_at: datetime
    updated_at: datetime


class ModelProviderPageView(ApiModel):
    items: list[ModelProviderView]
    total: int
    page: int
    page_size: int


def model_provider_view(provider: ModelProvider) -> ModelProviderView:
    return ModelProviderView(
        id=provider.id,
        provider_type=provider.provider_type,
        display_name=provider.display_name,
        base_url=provider.base_url,
        credential_configured=bool(provider.credential_ciphertext),
        credential_masked=provider.credential_prefix,
        enabled=provider.enabled,
        model_count=provider.model_count,
        revision=provider.revision,
        created_at=provider.created_at,
        updated_at=provider.updated_at,
    )
