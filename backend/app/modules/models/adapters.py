from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, Protocol

from pydantic import SecretStr

from app.modules.models.domain import ModelType


@dataclass(frozen=True)
class ProviderDescriptor:
    provider_type: str
    supported_model_types: frozenset[ModelType]
    discovery_path: str | None
    llm_path: str | None
    embedding_path: str | None
    rerank_path: str | None
    vision_path: str | None
    configurable_model_types: bool = False

    @property
    def supports_discovery(self) -> bool:
        return self.discovery_path is not None


@dataclass(frozen=True)
class ProviderConnectionRequest:
    base_url: str
    credential: SecretStr


@dataclass(frozen=True)
class ProviderConnectionResult:
    model_count: int
    latency_ms: int
    provider_request_id: str | None


@dataclass(frozen=True)
class DiscoverModelsRequest:
    base_url: str
    credential: SecretStr


@dataclass(frozen=True)
class DiscoveredModel:
    model_name: str
    suggested_types: tuple[ModelType, ...]
    provider_status: Literal["available", "unavailable", "unknown"]
    metadata_summary: Mapping[str, object]


@dataclass(frozen=True)
class ModelVerificationRequest:
    base_url: str
    credential: SecretStr
    model_name: str
    model_type: ModelType
    default_params: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class VerificationResult:
    output_text: str | None = None
    embedding: tuple[float, ...] | None = None
    rerank_scores: tuple[float, ...] | None = None
    provider_request_id: str | None = None
    usage_input_tokens: int | None = None
    usage_output_tokens: int | None = None


class ModelProviderError(Exception):
    def __init__(self, code: str, *, retryable: bool) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


class ModelTypeMismatchError(ModelProviderError):
    def __init__(self) -> None:
        super().__init__("MODEL_TYPE_MISMATCH", retryable=False)


class DuplicateProviderAdapterError(ValueError):
    def __init__(self, provider_type: str) -> None:
        super().__init__("duplicate model provider adapter")
        self.provider_type = provider_type


class ProviderAdapterNotFoundError(LookupError):
    def __init__(self, provider_type: str) -> None:
        super().__init__("model provider adapter not found")
        self.provider_type = provider_type


class ModelProviderAdapter(Protocol):
    descriptor: ProviderDescriptor

    def test_provider(self, request: ProviderConnectionRequest) -> ProviderConnectionResult: ...

    def discover_models(self, request: DiscoverModelsRequest) -> tuple[DiscoveredModel, ...]: ...

    def verify_llm(self, request: ModelVerificationRequest) -> VerificationResult: ...

    def verify_embedding(self, request: ModelVerificationRequest) -> VerificationResult: ...

    def verify_rerank(self, request: ModelVerificationRequest) -> VerificationResult: ...

    def verify_vision(self, request: ModelVerificationRequest) -> VerificationResult: ...


class ModelProviderAdapterResolver(Protocol):
    def get(self, provider_type: str) -> ModelProviderAdapter: ...
