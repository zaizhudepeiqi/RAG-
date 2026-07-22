from collections.abc import Mapping
from pathlib import Path

import pytest
from app.modules.capabilities import registry as registry_module
from app.modules.capabilities.domain import CapabilityOption
from app.modules.capabilities.errors import CapabilityNotFoundError
from app.modules.capabilities.registry import CapabilityRegistry
from app.modules.capabilities.service import CapabilityService


def option(
    code: str,
    *,
    version: str = "1",
    category: str = "chunk_strategy",
    enabled: bool = True,
    visible: bool = True,
    config_schema: dict[str, object] | None = None,
) -> CapabilityOption:
    return CapabilityOption(
        code=code,
        name=f"能力 {code}",
        description=f"{code} 描述",
        enabled=enabled,
        visible=visible,
        version=version,
        category=category,
        unavailable_reason=None if enabled else "当前版本尚未实现",
        config_schema=config_schema,
        ui_schema={"size": {"ui:widget": "number"}},
        required_source_features=("text",),
        preferred_source_features=("headings",),
    )


def test_duplicate_code_and_version_is_rejected_at_bootstrap() -> None:
    registry = CapabilityRegistry()
    registry.register(option("token", version="1"))

    with pytest.raises(ValueError, match="duplicate capability code and version"):
        registry.register(option("token", version="1"))


def test_list_filters_category_visibility_and_disabled_state() -> None:
    registry = CapabilityRegistry()
    registry.register(option("token"))
    registry.register(option("semantic", enabled=False))
    registry.register(option("internal", visible=False))
    registry.register(option("vector", category="retrieval_type"))
    service = CapabilityService(registry)

    default = service.list(category="chunk_strategy", include_disabled=False)
    with_disabled = service.list(category="chunk_strategy", include_disabled=True)

    assert [item.code for item in default] == ["token"]
    assert [item.code for item in with_disabled] == ["semantic", "token"]


def test_unknown_version_returns_capability_not_found() -> None:
    registry = CapabilityRegistry()
    registry.register(option("token", version="1"))

    with pytest.raises(CapabilityNotFoundError):
        CapabilityService(registry).get("token", "999")


def test_registry_does_not_load_arbitrary_python_plugins(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = tmp_path / "plugin-loaded"
    plugin = tmp_path / "untrusted_capability.py"
    plugin.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("RAG_CAPABILITY_PLUGINS", str(plugin))

    registry = CapabilityRegistry()

    assert registry.list(category=None, include_disabled=True) == ()
    assert not marker.exists()


def test_registered_schema_is_deeply_immutable() -> None:
    source_schema: dict[str, object] = {
        "type": "object",
        "required": ["size"],
        "properties": {"size": {"type": "integer", "minimum": 1}},
    }
    registry = CapabilityRegistry()
    registry.register(option("token", config_schema=source_schema))
    source_schema["type"] = "array"
    stored = registry.get("token", "1")

    assert stored.config_schema is not None
    assert stored.config_schema["type"] == "object"
    with pytest.raises(TypeError):
        stored.config_schema["type"] = "array"  # type: ignore[index]
    properties = stored.config_schema["properties"]
    assert isinstance(properties, dict) is False


def test_builtin_catalog_registers_supported_model_providers_and_types() -> None:
    builder = getattr(registry_module, "build_capability_registry", None)
    assert callable(builder), "build_capability_registry must define the production catalog"

    registry = builder()
    providers = registry.list(category="model_provider", include_disabled=False)
    model_types = registry.list(category="model_type", include_disabled=False)

    assert {item.code for item in providers} == {
        "openai",
        "openai_compatible",
        "deepseek",
        "qwen",
    }
    assert {item.code for item in model_types} == {"llm", "embedding", "rerank", "vision"}

    compatible = registry.get("openai_compatible", "1")
    assert compatible.config_schema is not None
    properties = compatible.config_schema["properties"]
    assert isinstance(properties, Mapping)
    assert "supportedModelTypes" in properties


def test_builtin_catalog_registers_parser_routes_and_input_types() -> None:
    registry = registry_module.build_capability_registry()

    parsers = registry.list(category="parser", include_disabled=False)
    input_types = registry.list(category="input_type", include_disabled=False)

    assert {item.code for item in parsers} == {"builtin_text", "mineru_precision_api"}
    assert {item.code for item in input_types} == {
        "bmp",
        "csv",
        "doc",
        "docx",
        "gif",
        "htm",
        "html",
        "jpeg",
        "jp2",
        "jpg",
        "json",
        "md",
        "pdf",
        "png",
        "ppt",
        "pptx",
        "txt",
        "webp",
        "xls",
        "xlsx",
        "zip",
    }

    html = registry.get("html", "1")
    assert html.config_schema is not None
    assert html.config_schema["defaultParserCode"] == "mineru_precision_api"
    assert html.config_schema["defaultModelVersion"] == "MinerU-HTML"

    text = registry.get("txt", "1")
    assert text.config_schema is not None
    assert text.config_schema["defaultParserCode"] == "builtin_text"
    assert text.config_schema["defaultModelVersion"] == "builtin"

    archive = registry.get("zip", "1")
    assert archive.config_schema is not None
    assert archive.config_schema["inputKind"] == "container"
    assert "defaultParserCode" not in archive.config_schema

    mineru = registry.get("mineru_precision_api", "1")
    assert mineru.config_schema is not None
    assert mineru.config_schema["additionalProperties"] is False
    assert "zip" not in mineru.config_schema["supportedExtensions"]
    properties = mineru.config_schema["properties"]
    assert isinstance(properties, Mapping)
    assert set(properties) == {
        "extraFormats",
        "forceProviderRefresh",
        "formulaEnabled",
        "language",
        "modelVersion",
        "ocrEnabled",
        "pageRanges",
        "parserCode",
        "tableEnabled",
    }
