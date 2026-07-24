from __future__ import annotations

from collections.abc import Mapping
from numbers import Real
from uuid import UUID

from app.modules.capabilities.domain import CapabilityOption
from app.modules.capabilities.errors import CapabilityNotFoundError
from app.modules.capabilities.registry import CapabilityRegistry
from app.modules.knowledge_bases.domain import (
    BuildConfig,
    ModelSelectionSnapshot,
    RetrievalConfig,
    SourceSelectionSnapshot,
)
from app.modules.knowledge_bases.errors import KnowledgeBaseConfigError

FieldErrors = dict[str, list[str]]


def validate_configs(
    build: BuildConfig,
    retrieval: RetrievalConfig,
    sources: tuple[SourceSelectionSnapshot, ...],
    embedding_model: ModelSelectionSnapshot,
    referenced_models: Mapping[UUID, ModelSelectionSnapshot],
    capabilities: CapabilityRegistry,
) -> tuple[str, ...]:
    errors: FieldErrors = {}
    warnings: list[str] = []
    _validate_sources(sources, errors)
    _validate_embedding_model(build, embedding_model, errors)
    chunk_capability = _validate_build_capabilities(build, capabilities, errors)
    _validate_build_cross_fields(build, errors)
    if chunk_capability is not None:
        _validate_source_features(chunk_capability, sources, errors, warnings)
    _validate_retrieval(retrieval, referenced_models, capabilities, errors)
    if errors:
        code = (
            "BUILD_CONFIG_INVALID"
            if any(key.startswith(("buildConfig", "parsedSourceVersionIds")) for key in errors)
            else "RETRIEVAL_CONFIG_INVALID"
        )
        raise KnowledgeBaseConfigError(code, errors)
    return tuple(dict.fromkeys(warnings))


def _validate_sources(sources: tuple[SourceSelectionSnapshot, ...], errors: FieldErrors) -> None:
    path = "parsedSourceVersionIds"
    if not sources:
        _add(errors, path, "至少选择一个已解析数据源版本")
        return
    ids = [source.parsed_source_version_id for source in sources]
    if len(ids) != len(set(ids)):
        _add(errors, path, "不能重复选择同一解析版本")
    if any(source.status not in {"succeeded", "degraded"} for source in sources):
        _add(errors, path, "只能选择 succeeded 或 degraded 的解析版本")
    if any(not source.feature_flags.get("hasText", False) for source in sources):
        _add(errors, path, "所选解析版本必须包含可检索文本")


def _validate_embedding_model(
    build: BuildConfig,
    model: ModelSelectionSnapshot,
    errors: FieldErrors,
) -> None:
    path = "buildConfig.embeddingModelId"
    if model.id != build.embedding_model_id:
        _add(errors, path, "Embedding 模型引用与已加载模型不一致")
    if model.model_type != "embedding":
        _add(errors, path, "必须选择 Embedding 类型模型")
    if not model.enabled or model.verification_status != "passed":
        _add(errors, path, "Embedding 模型必须已启用且验证通过")
    if model.embedding_dimension is None or model.embedding_dimension <= 0:
        _add(errors, path, "Embedding 模型必须具有有效向量维度")


def _validate_build_capabilities(
    build: BuildConfig,
    capabilities: CapabilityRegistry,
    errors: FieldErrors,
) -> CapabilityOption | None:
    selections: tuple[tuple[str, str, str, Mapping[str, object], str], ...] = (
        (
            "vector_store",
            build.vector_store_code,
            build.vector_store_version,
            {},
            "buildConfig.vectorStoreCode",
        ),
        (
            "vector_index",
            build.vector_index_code,
            build.vector_index_version,
            build.vector_index_params,
            "buildConfig.vectorIndexParams",
        ),
        (
            "keyword_store",
            build.keyword_store_code,
            build.keyword_store_version,
            {},
            "buildConfig.keywordStoreCode",
        ),
        (
            "index_structure",
            build.index_structure,
            "1",
            build.index_structure_params,
            "buildConfig.indexStructureParams",
        ),
        (
            "chunk_strategy",
            build.chunk_strategy_code,
            build.chunk_strategy_version,
            build.chunk_params,
            "buildConfig.chunkParams",
        ),
    )
    chunk_capability: CapabilityOption | None = None
    for category, code, version, params, path in selections:
        capability = _capability(capabilities, category, code, version, path, errors)
        if capability is not None:
            _validate_schema(params, capability.config_schema, path, errors)
        if category == "chunk_strategy":
            chunk_capability = capability
    return chunk_capability


def _validate_build_cross_fields(build: BuildConfig, errors: FieldErrors) -> None:
    params = build.chunk_params
    path = "buildConfig.chunkParams"
    if build.chunk_strategy_code == "token":
        size = _int(params.get("chunkSize"))
        overlap = _int(params.get("chunkOverlap"))
        if size is not None and overlap is not None and (overlap >= size or overlap > size * 0.5):
            _add(errors, path, "chunkOverlap 必须小于 chunkSize 且不超过其 50%")
    if build.chunk_strategy_code == "paragraph":
        minimum = _int(params.get("minChunkSize"))
        maximum = _int(params.get("maxChunkSize"))
        if minimum is not None and maximum is not None and minimum >= maximum:
            _add(errors, path, "minChunkSize 必须小于 maxChunkSize")
    if build.chunk_strategy_code == "page":
        maximum = _int(params.get("maxChunkSize"))
        overlap = _int(params.get("chunkOverlap"))
        if maximum is not None and overlap is not None and overlap >= maximum:
            _add(errors, path, "chunkOverlap 必须小于 maxChunkSize")
    if build.chunk_strategy_code == "semantic":
        minimum = _int(params.get("minChunkSize"))
        maximum = _int(params.get("maxChunkSize"))
        if minimum is not None and maximum is not None and minimum >= maximum:
            _add(errors, path, "minChunkSize 必须小于 maxChunkSize")

    if build.index_structure == "parent_child":
        structure = build.index_structure_params
        parent = _int(structure.get("parentChunkSize"))
        child = _int(structure.get("childChunkSize"))
        overlap = _int(structure.get("childChunkOverlap"))
        if child is not None and overlap is not None and overlap >= child:
            _add(
                errors,
                "buildConfig.indexStructureParams",
                "childChunkOverlap 必须小于 childChunkSize",
            )
        if parent is not None and child is not None and parent < child * 2:
            _add(
                errors,
                "buildConfig.indexStructureParams",
                "parentChunkSize 必须至少为 childChunkSize 的两倍",
            )


def _validate_source_features(
    capability: CapabilityOption,
    sources: tuple[SourceSelectionSnapshot, ...],
    errors: FieldErrors,
    warnings: list[str],
) -> None:
    for feature in capability.required_source_features:
        if any(not source.feature_flags.get(feature, False) for source in sources):
            if feature == "hasPages":
                _add(
                    errors,
                    "parsedSourceVersionIds",
                    "所选解析版本缺少按页分块要求的 hasPages 能力",
                )
            else:
                _add(errors, "parsedSourceVersionIds", f"所选解析版本缺少 {feature} 能力")
    if "hasHeadings" in capability.preferred_source_features and any(
        not source.feature_flags.get("hasHeadings", False) for source in sources
    ):
        warnings.append("CHUNK_HEADING_FALLBACK")


def _validate_retrieval(
    config: RetrievalConfig,
    models: Mapping[UUID, ModelSelectionSnapshot],
    capabilities: CapabilityRegistry,
    errors: FieldErrors,
) -> None:
    retrieval_capability = _capability(
        capabilities,
        "retrieval_type",
        config.retrieval_type,
        "1",
        "retrievalConfig.retrievalType",
        errors,
    )
    if retrieval_capability is not None:
        params: Mapping[str, object]
        if config.retrieval_type == "vector":
            params = config.vector.as_capability_params()
        elif config.retrieval_type == "keyword":
            params = config.keyword.as_capability_params()
        else:
            params = {
                "finalTopK": config.final_top_k,
                "finalScoreThreshold": config.fusion.final_score_threshold,
            }
        _validate_schema(
            params,
            retrieval_capability.config_schema,
            "retrievalConfig",
            errors,
        )
    _validate_schema(
        config.vector.as_capability_params(),
        capabilities.get("retrieval_type", "vector", "1").config_schema,
        "retrievalConfig.vector",
        errors,
    )
    _validate_schema(
        config.keyword.as_capability_params(),
        capabilities.get("retrieval_type", "keyword", "1").config_schema,
        "retrievalConfig.keyword",
        errors,
    )
    fusion = _capability(
        capabilities,
        "fusion_strategy",
        config.fusion.strategy,
        "1",
        "retrievalConfig.hybrid.fusionStrategy",
        errors,
    )
    if fusion is not None:
        _validate_schema(
            config.fusion.as_capability_params(),
            fusion.config_schema,
            "retrievalConfig.hybrid",
            errors,
        )
    if config.fusion.strategy == "weighted_score":
        vector_weight = config.fusion.vector_weight
        keyword_weight = config.fusion.keyword_weight
        if (
            vector_weight is not None
            and keyword_weight is not None
            and (vector_weight + keyword_weight <= 0)
        ):
            _add(errors, "retrievalConfig.hybrid", "向量和关键词权重不能同时为 0")
    if not 0 <= config.context_window <= 5:
        _add(errors, "retrievalConfig.contextWindow", "contextWindow 必须在 0 到 5 之间")
    if not 1 <= config.final_top_k <= 100:
        _add(errors, "retrievalConfig.finalTopK", "finalTopK 必须在 1 到 100 之间")
    _validate_model_strategy(
        category="query_rewrite",
        code=config.query_rewrite.code,
        model_id=config.query_rewrite.model_id,
        params=config.query_rewrite.params,
        required_model_type="llm",
        path="retrievalConfig.queryRewrite",
        models=models,
        capabilities=capabilities,
        errors=errors,
    )
    rerank_model_type = "rerank" if config.rerank.code == "rerank_model" else "llm"
    _validate_model_strategy(
        category="rerank",
        code=config.rerank.code,
        model_id=config.rerank.model_id,
        params=config.rerank.params,
        required_model_type=rerank_model_type,
        path="retrievalConfig.rerank",
        models=models,
        capabilities=capabilities,
        errors=errors,
    )
    if config.rerank.code != "off":
        candidate_limit = _int(config.rerank.params.get("candidateLimit"))
        top_k = _int(config.rerank.params.get("topK"))
        if candidate_limit is not None and top_k is not None and top_k > candidate_limit:
            _add(errors, "retrievalConfig.rerank.params", "topK 不能超过 candidateLimit")


def _validate_model_strategy(
    *,
    category: str,
    code: str,
    model_id: UUID | None,
    params: Mapping[str, object],
    required_model_type: str,
    path: str,
    models: Mapping[UUID, ModelSelectionSnapshot],
    capabilities: CapabilityRegistry,
    errors: FieldErrors,
) -> None:
    capability = _capability(capabilities, category, code, "1", f"{path}.strategyCode", errors)
    if capability is not None:
        _validate_schema(params, capability.config_schema, f"{path}.params", errors)
    if code == "off":
        if model_id is not None:
            _add(errors, f"{path}.modelId", "关闭时模型必须为无")
        return
    if model_id is None:
        _add(errors, f"{path}.modelId", "启用策略时必须选择模型")
        return
    model = models.get(model_id)
    if model is None:
        _add(errors, f"{path}.modelId", "所选模型不存在")
        return
    if (
        model.model_type != required_model_type
        or not model.enabled
        or model.verification_status != "passed"
    ):
        _add(errors, f"{path}.modelId", f"必须选择验证通过的 {required_model_type} 模型")


def _capability(
    registry: CapabilityRegistry,
    category: str,
    code: str,
    version: str,
    path: str,
    errors: FieldErrors,
) -> CapabilityOption | None:
    try:
        capability = registry.get(category, code, version)
    except CapabilityNotFoundError:
        _add(errors, path, "能力或版本不存在")
        return None
    if not capability.enabled:
        _add(errors, path, "该能力当前不可用")
        return None
    return capability


def _validate_schema(
    params: Mapping[str, object],
    schema: Mapping[str, object] | None,
    path: str,
    errors: FieldErrors,
) -> None:
    if schema is None:
        return
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return
    required = schema.get("required", ())
    if isinstance(required, (list, tuple)):
        for key in required:
            if isinstance(key, str) and key not in params:
                _add(errors, f"{path}.{key}", "字段必填")
    if schema.get("additionalProperties") is False:
        for key in set(params) - set(properties):
            _add(errors, f"{path}.{key}", "字段不属于当前能力版本")
    for key, value in params.items():
        field_schema = properties.get(key)
        if not isinstance(field_schema, Mapping):
            continue
        _validate_scalar(value, field_schema, f"{path}.{key}", errors)


def _validate_scalar(
    value: object,
    schema: Mapping[str, object],
    path: str,
    errors: FieldErrors,
) -> None:
    expected = schema.get("type")
    valid_type = True
    if expected == "integer":
        valid_type = isinstance(value, int) and not isinstance(value, bool)
    elif expected == "number":
        valid_type = isinstance(value, Real) and not isinstance(value, bool)
    elif expected == "boolean":
        valid_type = isinstance(value, bool)
    elif expected == "string":
        valid_type = isinstance(value, str)
    if not valid_type:
        _add(errors, path, "字段类型无效")
        return
    if isinstance(value, Real) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if isinstance(minimum, Real) and value < minimum:
            _add(errors, path, f"不能小于 {minimum}")
        if isinstance(maximum, Real) and value > maximum:
            _add(errors, path, f"不能大于 {maximum}")
    enum_values = schema.get("enum")
    if isinstance(enum_values, (list, tuple)) and value not in enum_values:
        _add(errors, path, "字段值不在允许范围内")


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _add(errors: FieldErrors, path: str, message: str) -> None:
    errors.setdefault(path, []).append(message)
