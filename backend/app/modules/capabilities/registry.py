from collections.abc import Mapping
from dataclasses import replace
from types import MappingProxyType

from app.modules.capabilities.domain import CapabilityOption
from app.modules.capabilities.errors import CapabilityNotFoundError

MODEL_TYPES = ("llm", "embedding", "rerank", "vision")


def _provider_schema(
    *,
    default_base_url: str,
    supported_model_types: tuple[str, ...],
    configurable_types: bool = False,
) -> dict[str, object]:
    type_schema: dict[str, object] = {
        "type": "array",
        "items": {"type": "string", "enum": list(MODEL_TYPES)},
        "uniqueItems": True,
        "minItems": 1,
        "default": list(supported_model_types),
    }
    if not configurable_types:
        type_schema["readOnly"] = True
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["baseUrl", "credential", "supportedModelTypes"],
        "properties": {
            "baseUrl": {
                "type": "string",
                "format": "uri",
                "default": default_base_url,
            },
            "credential": {
                "type": "string",
                "format": "password",
                "writeOnly": True,
                "minLength": 1,
            },
            "supportedModelTypes": type_schema,
        },
    }


MODEL_PROVIDER_CAPABILITIES = (
    CapabilityOption(
        code="openai",
        name="OpenAI",
        description="OpenAI 官方 API",
        enabled=True,
        visible=True,
        version="1",
        category="model_provider",
        config_schema=_provider_schema(
            default_base_url="https://api.openai.com/v1",
            supported_model_types=("llm", "embedding", "vision"),
        ),
        ui_schema={"credential": {"ui:widget": "password"}},
    ),
    CapabilityOption(
        code="openai_compatible",
        name="OpenAI-Compatible",
        description="实现 OpenAI 兼容协议的自定义供应商",
        enabled=True,
        visible=True,
        version="1",
        category="model_provider",
        config_schema=_provider_schema(
            default_base_url="https://example.com/v1",
            supported_model_types=("llm",),
            configurable_types=True,
        ),
        ui_schema={
            "credential": {"ui:widget": "password"},
            "supportedModelTypes": {"ui:widget": "checkboxes"},
        },
    ),
    CapabilityOption(
        code="deepseek",
        name="DeepSeek",
        description="DeepSeek 官方 API",
        enabled=True,
        visible=True,
        version="1",
        category="model_provider",
        config_schema=_provider_schema(
            default_base_url="https://api.deepseek.com",
            supported_model_types=("llm",),
        ),
        ui_schema={"credential": {"ui:widget": "password"}},
    ),
    CapabilityOption(
        code="qwen",
        name="通义千问",
        description="阿里云百炼 DashScope API",
        enabled=True,
        visible=True,
        version="1",
        category="model_provider",
        config_schema=_provider_schema(
            default_base_url="https://dashscope.aliyuncs.com",
            supported_model_types=MODEL_TYPES,
        ),
        ui_schema={"credential": {"ui:widget": "password"}},
    ),
)

MODEL_TYPE_CAPABILITIES = tuple(
    CapabilityOption(
        code=code,
        name=name,
        description=description,
        enabled=True,
        visible=True,
        version="1",
        category="model_type",
        config_schema={"type": "object", "additionalProperties": False},
    )
    for code, name, description in (
        ("llm", "大语言模型", "文本生成、改写和 LLM 重排"),
        ("embedding", "Embedding 模型", "文本向量化"),
        ("rerank", "重排模型", "候选文档相关性重排"),
        ("vision", "视觉模型", "图像理解连接能力"),
    )
)


class CapabilityRegistry:
    def __init__(self) -> None:
        self._options: dict[tuple[str, str], CapabilityOption] = {}

    def register(self, option: CapabilityOption) -> None:
        key = (option.code, option.version)
        if key in self._options:
            raise ValueError("duplicate capability code and version")
        self._options[key] = replace(
            option,
            config_schema=_freeze_mapping(option.config_schema),
            ui_schema=_freeze_mapping(option.ui_schema),
            required_source_features=tuple(option.required_source_features),
            preferred_source_features=tuple(option.preferred_source_features),
        )

    def list(
        self,
        *,
        category: str | None,
        include_disabled: bool,
    ) -> tuple[CapabilityOption, ...]:
        options = (
            option
            for option in self._options.values()
            if option.visible
            and (category is None or option.category == category)
            and (include_disabled or option.enabled)
        )
        return tuple(sorted(options, key=lambda item: (item.code, item.version)))

    def get(self, code: str, version: str) -> CapabilityOption:
        try:
            return self._options[(code, version)]
        except KeyError as error:
            raise CapabilityNotFoundError from error


def build_capability_registry() -> CapabilityRegistry:
    registry = CapabilityRegistry()
    for option in MODEL_PROVIDER_CAPABILITIES + MODEL_TYPE_CAPABILITIES:
        registry.register(option)
    return registry


def _freeze_mapping(value: Mapping[str, object] | None) -> Mapping[str, object] | None:
    if value is None:
        return None
    return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})


def _freeze_json(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    return value
