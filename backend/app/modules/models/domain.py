from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class ModelType(StrEnum):
    LLM = "llm"
    EMBEDDING = "embedding"
    RERANK = "rerank"
    VISION = "vision"


class VerificationStatus(StrEnum):
    UNTESTED = "untested"
    PASSED = "passed"
    FAILED = "failed"
    STALE = "stale"


@dataclass
class ModelProvider:
    id: UUID
    provider_type: str
    display_name: str
    base_url: str
    supported_model_types: tuple[ModelType, ...]
    credential_ciphertext: bytes
    credential_nonce: bytes
    credential_key_version: str
    credential_prefix: str | None
    credential_revision: int
    enabled: bool
    revision: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    model_count: int


@dataclass(frozen=True)
class DiscoveredModelCandidate:
    model_name: str
    suggested_types: tuple[ModelType, ...]
    provider_status: str
    metadata_summary: dict[str, object]
    configured_model_ids: tuple[UUID, ...]


@dataclass
class ModelConfig:
    id: UUID
    provider_id: UUID
    model_name: str
    display_name: str
    model_type: ModelType
    enabled: bool
    verification_status: VerificationStatus
    context_window: int | None
    max_output_tokens: int | None
    embedding_dimension: int | None
    capability_version: str
    default_params: dict[str, object]
    config_schema: dict[str, object]
    revision: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


@dataclass(frozen=True)
class ModelVerificationSnapshot:
    model_id: UUID
    tested_model_revision: int
    tested_provider_revision: int
    tested_credential_revision: int
    status: str
    latency_ms: int | None
    error_code: str | None
    tested_at: datetime


@dataclass(frozen=True)
class ModelReference:
    resource_type: str
    resource_id: UUID
    display_name: str
    state: str


@dataclass(frozen=True)
class SelectableModel:
    model: ModelConfig
    provider: ModelProvider
    verification: ModelVerificationSnapshot


@dataclass(frozen=True)
class ModelConfigDetails:
    model: ModelConfig
    provider: ModelProvider
    verification: ModelVerificationSnapshot | None
    references: tuple[ModelReference, ...]


def provider_credential_aad(provider_id: UUID) -> bytes:
    return f"model-provider:{provider_id}:credential:v1".encode("ascii")


def mask_credential(value: str) -> str:
    if len(value) < 8:
        return "****"
    return f"{value[:4]}...{value[-4:]}"
