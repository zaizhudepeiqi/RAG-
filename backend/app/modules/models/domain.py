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


def provider_credential_aad(provider_id: UUID) -> bytes:
    return f"model-provider:{provider_id}:credential:v1".encode("ascii")


def mask_credential(value: str) -> str:
    if len(value) < 8:
        return "****"
    return f"{value[:4]}...{value[-4:]}"
