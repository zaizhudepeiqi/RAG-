from datetime import datetime
from uuid import UUID

from pydantic import AnyHttpUrl, Field, SecretStr

from app.core.schemas import ApiModel
from app.modules.models.domain import (
    DiscoveredModelCandidate,
    ModelConfigDetails,
    ModelProvider,
    ModelReference,
    ModelType,
    VerificationStatus,
)


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


class ProviderOperationRequest(ApiModel):
    expected_revision: int = Field(ge=1)


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


class DiscoveredModelView(ApiModel):
    provider_model_name: str
    suggested_display_name: str
    supported_model_types: list[ModelType]
    already_configured_model_ids: list[UUID]
    discovery_metadata: dict[str, object]


class CreateModelRequest(ApiModel):
    provider_id: UUID
    model_name: str = Field(min_length=1, max_length=300)
    display_name: str = Field(min_length=1, max_length=200)
    model_type: ModelType
    context_window: int | None = Field(default=None, ge=1)
    max_output_tokens: int | None = Field(default=None, ge=1)
    embedding_dimension: int | None = Field(default=None, ge=1)
    default_params: dict[str, object] = Field(default_factory=dict)


class UpdateModelRequest(ApiModel):
    expected_revision: int = Field(ge=1)
    model_name: str | None = Field(default=None, min_length=1, max_length=300)
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    model_type: ModelType | None = None
    context_window: int | None = Field(default=None, ge=1)
    max_output_tokens: int | None = Field(default=None, ge=1)
    embedding_dimension: int | None = Field(default=None, ge=1)
    capability_version: str | None = Field(default=None, min_length=1, max_length=50)
    default_params: dict[str, object] | None = None
    config_schema: dict[str, object] | None = None


class ModelStateRequest(ApiModel):
    expected_revision: int = Field(ge=1)


class ResourceRef(ApiModel):
    id: UUID
    display_name: str


class LastModelVerificationView(ApiModel):
    status: str
    latency_ms: int | None = None
    tested_at: datetime
    error_code: str | None = None


class ModelView(ApiModel):
    id: UUID
    provider: ResourceRef
    model_name: str
    display_name: str
    model_type: ModelType
    enabled: bool
    verification_status: VerificationStatus
    context_window: int | None = None
    max_output_tokens: int | None = None
    embedding_dimension: int | None = None
    capability_version: str
    default_params: dict[str, object]
    config_schema: dict[str, object]
    last_verification: LastModelVerificationView | None = None
    used_by_knowledge_base_count: int
    used_by_bot_count: int
    revision: int


class ModelPageView(ApiModel):
    items: list[ModelView]
    total: int
    page: int
    page_size: int


class ModelReferenceView(ApiModel):
    resource_type: str
    resource_id: UUID
    display_name: str
    state: str


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


def discovered_model_view(candidate: DiscoveredModelCandidate) -> DiscoveredModelView:
    allowed_metadata = {
        key: value
        for key, value in candidate.metadata_summary.items()
        if key in {"ownedBy", "created"}
    }
    return DiscoveredModelView(
        provider_model_name=candidate.model_name,
        suggested_display_name=candidate.model_name,
        supported_model_types=list(candidate.suggested_types),
        already_configured_model_ids=list(candidate.configured_model_ids),
        discovery_metadata=allowed_metadata,
    )


def model_view(details: ModelConfigDetails) -> ModelView:
    model = details.model
    last_verification = details.verification
    return ModelView(
        id=model.id,
        provider=ResourceRef(id=details.provider.id, display_name=details.provider.display_name),
        model_name=model.model_name,
        display_name=model.display_name,
        model_type=model.model_type,
        enabled=model.enabled,
        verification_status=model.verification_status,
        context_window=model.context_window,
        max_output_tokens=model.max_output_tokens,
        embedding_dimension=model.embedding_dimension,
        capability_version=model.capability_version,
        default_params=model.default_params,
        config_schema=model.config_schema,
        last_verification=(
            LastModelVerificationView(
                status=last_verification.status,
                latency_ms=last_verification.latency_ms,
                tested_at=last_verification.tested_at,
                error_code=last_verification.error_code,
            )
            if last_verification is not None
            else None
        ),
        used_by_knowledge_base_count=sum(
            item.resource_type == "knowledge_base" for item in details.references
        ),
        used_by_bot_count=sum(item.resource_type == "bot" for item in details.references),
        revision=model.revision,
    )


def model_reference_view(reference: ModelReference) -> ModelReferenceView:
    return ModelReferenceView(
        resource_type=reference.resource_type,
        resource_id=reference.resource_id,
        display_name=reference.display_name,
        state=reference.state,
    )
