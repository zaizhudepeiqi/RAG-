from collections.abc import Mapping
from dataclasses import replace
from types import MappingProxyType

from app.modules.capabilities.domain import CapabilityOption
from app.modules.capabilities.errors import CapabilityNotFoundError

MODEL_TYPES = ("llm", "embedding", "rerank", "vision")
BUILTIN_TEXT_EXTENSIONS = ("csv", "json", "md", "txt")
MINERU_EXTENSIONS = (
    "bmp",
    "doc",
    "docx",
    "gif",
    "htm",
    "html",
    "jpeg",
    "jp2",
    "jpg",
    "pdf",
    "png",
    "ppt",
    "pptx",
    "webp",
    "xls",
    "xlsx",
)

INPUT_TYPE_MIME_TYPES: dict[str, tuple[str, ...]] = {
    "bmp": ("image/bmp", "image/x-ms-bmp"),
    "csv": ("application/csv", "text/csv", "text/plain"),
    "doc": ("application/msword",),
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document",),
    "gif": ("image/gif",),
    "htm": ("text/html",),
    "html": ("text/html",),
    "jpeg": ("image/jpeg",),
    "jp2": ("image/jp2",),
    "jpg": ("image/jpeg",),
    "json": ("application/json", "text/json", "text/plain"),
    "md": ("text/markdown", "text/plain"),
    "pdf": ("application/pdf",),
    "png": ("image/png",),
    "ppt": ("application/vnd.ms-powerpoint",),
    "pptx": ("application/vnd.openxmlformats-officedocument.presentationml.presentation",),
    "txt": ("text/plain",),
    "webp": ("image/webp",),
    "xls": ("application/vnd.ms-excel",),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",),
    "zip": ("application/x-zip-compressed", "application/zip"),
}


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


def _parse_config_schema(
    *,
    parser_code: str,
    model_versions: tuple[str, ...],
    supported_extensions: tuple[str, ...],
) -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "supportedExtensions": list(supported_extensions),
        "required": [
            "parserCode",
            "modelVersion",
            "language",
            "ocrEnabled",
            "tableEnabled",
            "formulaEnabled",
            "extraFormats",
            "forceProviderRefresh",
        ],
        "properties": {
            "parserCode": {"type": "string", "const": parser_code},
            "modelVersion": {"type": "string", "enum": list(model_versions)},
            "language": {"type": "string", "minLength": 1, "default": "ch"},
            "ocrEnabled": {"type": "boolean", "default": False},
            "tableEnabled": {"type": "boolean", "default": True},
            "formulaEnabled": {"type": "boolean", "default": True},
            "pageRanges": {"type": ["string", "null"], "default": None},
            "extraFormats": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
            },
            "forceProviderRefresh": {"type": "boolean", "default": False},
        },
    }


PARSER_CAPABILITIES = (
    CapabilityOption(
        code="builtin_text",
        name="内置文本解析",
        description="确定性解析 TXT、Markdown、CSV 和 JSON",
        enabled=True,
        visible=True,
        version="1",
        category="parser",
        config_schema=_parse_config_schema(
            parser_code="builtin_text",
            model_versions=("builtin",),
            supported_extensions=BUILTIN_TEXT_EXTENSIONS,
        ),
    ),
    CapabilityOption(
        code="mineru_precision_api",
        name="MinerU Precision API",
        description="通过 MinerU Cloud 解析文档、图片和 Office 文件",
        enabled=True,
        visible=True,
        version="1",
        category="parser",
        config_schema=_parse_config_schema(
            parser_code="mineru_precision_api",
            model_versions=("pipeline", "vlm", "MinerU-HTML"),
            supported_extensions=MINERU_EXTENSIONS,
        ),
        ui_schema={
            "pageRanges": {"ui:placeholder": "例如 1-5,8"},
            "extraFormats": {"ui:widget": "checkboxes"},
        },
    ),
)


def _input_type_capability(extension: str) -> CapabilityOption:
    is_archive = extension == "zip"
    is_builtin = extension in BUILTIN_TEXT_EXTENSIONS
    is_html = extension in {"htm", "html"}
    metadata: dict[str, object] = {
        "inputKind": "container" if is_archive else "file",
        "mimeTypes": list(INPUT_TYPE_MIME_TYPES[extension]),
    }
    if not is_archive:
        metadata["defaultParserCode"] = "builtin_text" if is_builtin else "mineru_precision_api"
        metadata["defaultModelVersion"] = (
            "builtin" if is_builtin else "MinerU-HTML" if is_html else "pipeline"
        )
    return CapabilityOption(
        code=extension,
        name=extension.upper(),
        description=("安全批量上传容器" if is_archive else f".{extension} 文件"),
        enabled=True,
        visible=True,
        version="1",
        category="input_type",
        config_schema=metadata,
    )


INPUT_TYPE_CAPABILITIES = tuple(
    _input_type_capability(extension)
    for extension in sorted((*BUILTIN_TEXT_EXTENSIONS, *MINERU_EXTENSIONS, "zip"))
)


def _schema(
    properties: dict[str, object] | None = None,
    *,
    rules: tuple[str, ...] = (),
) -> dict[str, object]:
    schema: dict[str, object] = {
        "type": "object",
        "additionalProperties": False,
        "properties": properties or {},
    }
    if properties:
        schema["required"] = list(properties)
    if rules:
        schema["x-crossFieldRules"] = list(rules)
    return schema


def _integer(
    default: int,
    minimum: int,
    maximum: int,
    *,
    unit: str | None = None,
) -> dict[str, object]:
    value: dict[str, object] = {
        "type": "integer",
        "minimum": minimum,
        "maximum": maximum,
        "default": default,
    }
    if unit is not None:
        value["unit"] = unit
    return value


def _number(default: float, minimum: float, maximum: float) -> dict[str, object]:
    return {
        "type": "number",
        "minimum": minimum,
        "maximum": maximum,
        "default": default,
    }


def _option(
    code: str,
    name: str,
    description: str,
    category: str,
    *,
    config_schema: dict[str, object] | None = None,
    ui_schema: dict[str, object] | None = None,
    enabled: bool = True,
    unavailable_reason: str | None = None,
    required_source_features: tuple[str, ...] = (),
    preferred_source_features: tuple[str, ...] = (),
) -> CapabilityOption:
    return CapabilityOption(
        code=code,
        name=name,
        description=description,
        enabled=enabled,
        visible=True,
        version="1",
        category=category,
        unavailable_reason=unavailable_reason,
        config_schema=config_schema or _schema(),
        ui_schema=ui_schema,
        required_source_features=required_source_features,
        preferred_source_features=preferred_source_features,
    )


INDEX_STRUCTURE_CAPABILITIES = (
    _option("chunk", "Chunk", "检索块同时作为最终上下文", "index_structure"),
    _option(
        "parent_child",
        "Parent-Child",
        "使用 Child 召回并返回 Parent 上下文",
        "index_structure",
        config_schema=_schema(
            {
                "parentChunkSize": _integer(1024, 256, 4096, unit="tokens"),
                "childChunkSize": _integer(256, 64, 1024, unit="tokens"),
                "childChunkOverlap": _integer(32, 0, 1023, unit="tokens"),
            },
            rules=(
                "childChunkOverlap < childChunkSize",
                "parentChunkSize >= 2 * childChunkSize",
            ),
        ),
    ),
    _option(
        "qa",
        "QA 索引",
        "问答对索引结构",
        "index_structure",
        enabled=False,
        unavailable_reason="第一版尚未实现",
    ),
)

CHUNK_STRATEGY_CAPABILITIES = (
    _option(
        "token",
        "Token 分块",
        "按可编辑 Token 大小和重叠切分",
        "chunk_strategy",
        config_schema=_schema(
            {
                "chunkSize": _integer(512, 64, 4096, unit="tokens"),
                "chunkOverlap": _integer(64, 0, 2048, unit="tokens"),
            },
            rules=("chunkOverlap < chunkSize", "chunkOverlap <= chunkSize * 0.5"),
        ),
        required_source_features=("hasText",),
    ),
    _option(
        "paragraph",
        "段落分块",
        "聚合短段落并拆分超长段落",
        "chunk_strategy",
        config_schema=_schema(
            {
                "maxChunkSize": _integer(512, 64, 4096, unit="tokens"),
                "minChunkSize": _integer(100, 0, 4095, unit="tokens"),
                "overlapParagraphs": _integer(1, 0, 5, unit="paragraphs"),
            },
            rules=("minChunkSize < maxChunkSize",),
        ),
        required_source_features=("hasText",),
    ),
    _option(
        "heading",
        "标题层级分块",
        "按标题结构切分, 缺失标题时明确降级",
        "chunk_strategy",
        config_schema=_schema(
            {
                "maxHeadingLevel": _integer(3, 1, 6),
                "maxChunkSize": _integer(768, 128, 4096, unit="tokens"),
                "includeHeadingPath": {"type": "boolean", "default": True},
            }
        ),
        required_source_features=("hasText",),
        preferred_source_features=("hasHeadings",),
    ),
    _option(
        "page",
        "按页分块",
        "按解析页和明确跨页段落切分",
        "chunk_strategy",
        config_schema=_schema(
            {
                "maxChunkSize": _integer(1024, 128, 4096, unit="tokens"),
                "chunkOverlap": _integer(64, 0, 4095, unit="tokens"),
            },
            rules=("chunkOverlap < maxChunkSize",),
        ),
        required_source_features=("hasText", "hasPages"),
    ),
    _option(
        "semantic",
        "语义分块",
        "使用当前知识库的 Embedding 模型识别语义边界",
        "chunk_strategy",
        config_schema=_schema(
            {
                "minChunkSize": _integer(200, 64, 1024, unit="tokens"),
                "maxChunkSize": _integer(800, 256, 4096, unit="tokens"),
                "similarityThreshold": _number(0.75, 0, 1),
                "sentenceWindow": _integer(3, 1, 10, unit="sentences"),
            },
            rules=("minChunkSize < maxChunkSize",),
        ),
        required_source_features=("hasText",),
    ),
)

STORE_CAPABILITIES = (
    _option("chroma", "Chroma", "Chroma 向量数据库", "vector_store"),
    _option(
        "hnsw",
        "HNSW",
        "Chroma HNSW cosine 向量索引",
        "vector_index",
        config_schema=_schema(
            {
                "metric": {
                    "type": "string",
                    "enum": ["cosine"],
                    "default": "cosine",
                    "readOnly": True,
                }
            }
        ),
    ),
    _option(
        "postgres_trigram",
        "PostgreSQL Trigram",
        "PostgreSQL pg_trgm GIN 关键词索引",
        "keyword_store",
    ),
)

RETRIEVAL_TYPE_CAPABILITIES = (
    _option(
        "vector",
        "向量检索",
        "按向量相似度召回",
        "retrieval_type",
        config_schema=_schema(
            {"topK": _integer(20, 1, 200), "scoreThreshold": _number(0.3, 0, 1)}
        ),
    ),
    _option(
        "keyword",
        "关键词检索",
        "按 pg_trgm 相似度召回",
        "retrieval_type",
        config_schema=_schema(
            {"topK": _integer(20, 1, 200), "scoreThreshold": _number(0.1, 0, 1)}
        ),
    ),
    _option(
        "hybrid",
        "混合检索",
        "并行执行向量和关键词召回后融合",
        "retrieval_type",
        config_schema=_schema(
            {
                "finalTopK": _integer(10, 1, 100),
                "finalScoreThreshold": _number(0, 0, 1),
            }
        ),
    ),
)

FUSION_CAPABILITIES = (
    _option(
        "rrf",
        "RRF",
        "按候选排名进行倒数排名融合",
        "fusion_strategy",
        config_schema=_schema({"rrfK": _integer(60, 1, 1000)}),
    ),
    _option(
        "weighted_score",
        "Weighted Score",
        "归一化后按权重融合两路分数",
        "fusion_strategy",
        config_schema=_schema(
            {
                "vectorWeight": _number(0.5, 0, 10),
                "keywordWeight": _number(0.5, 0, 10),
            },
            rules=("vectorWeight + keywordWeight > 0",),
        ),
    ),
)

_REWRITE_COMMON = {
    "rewriteMaxTokens": _integer(256, 32, 1024, unit="tokens"),
    "temperature": _number(0, 0, 2),
}
QUERY_REWRITE_CAPABILITIES = (
    _option("off", "关闭", "不执行查询重写", "query_rewrite"),
    _option(
        "hyde",
        "HyDE (假设性文档)",
        "生成假设性文档并与原问题共同检索",
        "query_rewrite",
        config_schema=_schema(dict(_REWRITE_COMMON)),
        ui_schema={"modelType": "llm"},
    ),
    _option(
        "multi_query",
        "多查询扩展",
        "生成多个改写查询并与原问题共同检索",
        "query_rewrite",
        config_schema=_schema(
            {"queryCount": _integer(3, 2, 5), **_REWRITE_COMMON}
        ),
        ui_schema={"modelType": "llm"},
    ),
    _option(
        "step_back",
        "回退提问",
        "生成更抽象的问题并与原问题共同检索",
        "query_rewrite",
        config_schema=_schema(dict(_REWRITE_COMMON)),
        ui_schema={"modelType": "llm"},
    ),
)

_RERANK_PROPERTIES = {
    "candidateLimit": _integer(20, 2, 100),
    "topK": _integer(10, 1, 100),
    "scoreThreshold": _number(0, 0, 1),
}
RERANK_CAPABILITIES = (
    _option("off", "关闭", "不执行重排序", "rerank"),
    _option(
        "rerank_model",
        "重排序模型",
        "使用已验证的 Rerank 模型重排候选",
        "rerank",
        config_schema=_schema(
            dict(_RERANK_PROPERTIES), rules=("topK <= candidateLimit",)
        ),
        ui_schema={"modelType": "rerank"},
    ),
    _option(
        "llm_rerank",
        "LLM 重排序",
        "使用已验证的大语言模型按候选 ID 重排",
        "rerank",
        config_schema=_schema(
            dict(_RERANK_PROPERTIES), rules=("topK <= candidateLimit",)
        ),
        ui_schema={"modelType": "llm"},
    ),
)

KNOWLEDGE_RETRIEVAL_CAPABILITIES = (
    INDEX_STRUCTURE_CAPABILITIES
    + CHUNK_STRATEGY_CAPABILITIES
    + STORE_CAPABILITIES
    + RETRIEVAL_TYPE_CAPABILITIES
    + FUSION_CAPABILITIES
    + QUERY_REWRITE_CAPABILITIES
    + RERANK_CAPABILITIES
)


class CapabilityRegistry:
    def __init__(self) -> None:
        self._options: dict[tuple[str | None, str, str], CapabilityOption] = {}

    def register(self, option: CapabilityOption) -> None:
        key = (option.category, option.code, option.version)
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

    def get(self, category: str, code: str, version: str) -> CapabilityOption:
        try:
            return self._options[(category, code, version)]
        except KeyError as error:
            raise CapabilityNotFoundError from error


def build_capability_registry() -> CapabilityRegistry:
    registry = CapabilityRegistry()
    for option in (
        MODEL_PROVIDER_CAPABILITIES
        + MODEL_TYPE_CAPABILITIES
        + PARSER_CAPABILITIES
        + INPUT_TYPE_CAPABILITIES
        + KNOWLEDGE_RETRIEVAL_CAPABILITIES
    ):
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
