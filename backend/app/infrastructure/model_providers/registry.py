from app.infrastructure.model_providers.openai_compatible import (
    OpenAICompatibleAdapter,
    QwenAdapter,
)
from app.modules.models.adapters import (
    DuplicateProviderAdapterError,
    ModelProviderAdapter,
    ModelTypeMismatchError,
    ProviderAdapterNotFoundError,
    ProviderDescriptor,
)
from app.modules.models.domain import ModelType

OPENAI_DESCRIPTOR = ProviderDescriptor(
    provider_type="openai",
    supported_model_types=frozenset({ModelType.LLM, ModelType.EMBEDDING, ModelType.VISION}),
    discovery_path="models",
    llm_path="chat/completions",
    embedding_path="embeddings",
    rerank_path=None,
    vision_path="chat/completions",
)

OPENAI_COMPATIBLE_DESCRIPTOR = ProviderDescriptor(
    provider_type="openai_compatible",
    supported_model_types=frozenset(ModelType),
    discovery_path="models",
    llm_path="chat/completions",
    embedding_path="embeddings",
    rerank_path="rerank",
    vision_path="chat/completions",
    configurable_model_types=True,
)

DEEPSEEK_DESCRIPTOR = ProviderDescriptor(
    provider_type="deepseek",
    supported_model_types=frozenset({ModelType.LLM}),
    discovery_path="models",
    llm_path="chat/completions",
    embedding_path=None,
    rerank_path=None,
    vision_path=None,
)

QWEN_DESCRIPTOR = ProviderDescriptor(
    provider_type="qwen",
    supported_model_types=frozenset(ModelType),
    discovery_path="api/v1/models",
    llm_path="compatible-mode/v1/chat/completions",
    embedding_path="api/v1/services/embeddings/text-embedding/text-embedding",
    rerank_path="api/v1/services/rerank/text-rerank/text-rerank",
    vision_path="compatible-mode/v1/chat/completions",
)


class ModelProviderAdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, ModelProviderAdapter] = {}

    @property
    def provider_types(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))

    def register(self, adapter: ModelProviderAdapter) -> None:
        provider_type = adapter.descriptor.provider_type
        if provider_type in self._adapters:
            raise DuplicateProviderAdapterError(provider_type)
        self._adapters[provider_type] = adapter

    def get(self, provider_type: str) -> ModelProviderAdapter:
        try:
            return self._adapters[provider_type]
        except KeyError as error:
            raise ProviderAdapterNotFoundError(provider_type) from error

    def require(self, provider_type: str, model_type: ModelType) -> ModelProviderAdapter:
        adapter = self.get(provider_type)
        if model_type not in adapter.descriptor.supported_model_types:
            raise ModelTypeMismatchError
        return adapter


def build_model_provider_adapter_registry() -> ModelProviderAdapterRegistry:
    registry = ModelProviderAdapterRegistry()
    registry.register(OpenAICompatibleAdapter(OPENAI_DESCRIPTOR))
    registry.register(OpenAICompatibleAdapter(OPENAI_COMPATIBLE_DESCRIPTOR))
    registry.register(OpenAICompatibleAdapter(DEEPSEEK_DESCRIPTOR))
    registry.register(QwenAdapter(QWEN_DESCRIPTOR))
    return registry
