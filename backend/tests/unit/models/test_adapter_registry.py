import json
from pathlib import Path

import respx
from app.infrastructure.model_providers.registry import build_model_provider_adapter_registry
from app.modules.models.adapters import (
    DiscoverModelsRequest,
    DuplicateProviderAdapterError,
    ModelTypeMismatchError,
)
from app.modules.models.domain import ModelType
from httpx import Response
from pydantic import SecretStr

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "model_providers"


def test_registry_exposes_real_provider_descriptors() -> None:
    registry = build_model_provider_adapter_registry()

    assert registry.provider_types == ("deepseek", "openai", "openai_compatible", "qwen")
    assert registry.get("openai").descriptor.supported_model_types == frozenset(
        {ModelType.LLM, ModelType.EMBEDDING, ModelType.VISION}
    )
    assert registry.get("deepseek").descriptor.supported_model_types == frozenset({ModelType.LLM})
    assert registry.get("qwen").descriptor.supported_model_types == frozenset(ModelType)
    assert registry.get("openai_compatible").descriptor.configurable_model_types is True


def test_registry_rejects_duplicate_provider_type() -> None:
    registry = build_model_provider_adapter_registry()

    try:
        registry.register(registry.get("openai"))
    except DuplicateProviderAdapterError as error:
        assert error.provider_type == "openai"
    else:
        raise AssertionError("duplicate provider adapter must be rejected")


def test_registry_rejects_unsupported_model_type_with_stable_error() -> None:
    registry = build_model_provider_adapter_registry()

    try:
        registry.require("deepseek", ModelType.EMBEDDING)
    except ModelTypeMismatchError as error:
        assert error.code == "MODEL_TYPE_MISMATCH"
        assert error.retryable is False
    else:
        raise AssertionError("unsupported model type must be rejected")


@respx.mock
def test_discovery_uses_versioned_response_without_model_name_inference() -> None:
    fixture = json.loads((FIXTURES / "openai_models_v1.json").read_text(encoding="utf-8"))
    route = respx.get("https://8.8.8.8/v1/models").mock(
        return_value=Response(200, json=fixture, headers={"x-request-id": "req-models-001"})
    )
    adapter = build_model_provider_adapter_registry().get("openai")

    discovered = adapter.discover_models(
        DiscoverModelsRequest(
            base_url="https://8.8.8.8/v1",
            credential=SecretStr("test-only-provider-key"),
        )
    )

    assert route.called
    assert [item.model_name for item in discovered] == [
        "gpt-4.1-mini",
        "text-embedding-3-small",
    ]
    assert all(item.suggested_types == () for item in discovered)
    assert all(item.provider_status == "available" for item in discovered)
