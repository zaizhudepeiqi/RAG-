from uuid import uuid4

import pytest
from app.modules.capabilities.registry import build_capability_registry
from app.modules.knowledge_bases.domain import (
    BuildConfig,
    FusionConfig,
    KeywordConfig,
    ModelSelectionSnapshot,
    QueryRewriteConfig,
    RerankConfig,
    RetrievalConfig,
    SourceSelectionSnapshot,
    VectorConfig,
    canonical_config_hash,
)
from app.modules.knowledge_bases.errors import KnowledgeBaseConfigError
from app.modules.knowledge_bases.validation import validate_configs


def source(**features: bool) -> SourceSelectionSnapshot:
    return SourceSelectionSnapshot(
        parsed_source_version_id=uuid4(),
        status="succeeded",
        feature_flags={
            "hasText": True,
            "hasPages": False,
            "hasHeadings": False,
            "hasBoundingBoxes": False,
            "hasAssets": False,
            "hasTables": False,
            "hasFormulas": False,
            **features,
        },
    )


def model(model_type: str) -> ModelSelectionSnapshot:
    return ModelSelectionSnapshot(
        id=uuid4(),
        model_type=model_type,
        enabled=True,
        verification_status="passed",
        embedding_dimension=1536 if model_type == "embedding" else None,
    )


def build_config(**overrides: object) -> BuildConfig:
    values: dict[str, object] = {
        "embedding_model_id": uuid4(),
        "embedding_params": {},
        "vector_store_code": "chroma",
        "vector_store_version": "1",
        "vector_index_code": "hnsw",
        "vector_index_version": "1",
        "vector_index_params": {"metric": "cosine"},
        "keyword_store_code": "postgres_trigram",
        "keyword_store_version": "1",
        "index_structure": "chunk",
        "index_structure_params": {},
        "chunk_strategy_code": "token",
        "chunk_strategy_version": "1",
        "chunk_params": {"chunkSize": 512, "chunkOverlap": 64},
    }
    values.update(overrides)
    return BuildConfig(**values)  # type: ignore[arg-type]


def retrieval_config(**overrides: object) -> RetrievalConfig:
    values: dict[str, object] = {
        "retrieval_type": "hybrid",
        "vector": VectorConfig(top_k=20, score_threshold=0.3),
        "keyword": KeywordConfig(top_k=20, score_threshold=0.1),
        "fusion": FusionConfig(
            strategy="rrf",
            rrf_k=60,
            vector_weight=None,
            keyword_weight=None,
            final_score_threshold=0,
        ),
        "query_rewrite": QueryRewriteConfig(code="off", model_id=None, params={}),
        "rerank": RerankConfig(code="off", model_id=None, params={}),
        "context_window": 0,
        "final_top_k": 10,
    }
    values.update(overrides)
    return RetrievalConfig(**values)  # type: ignore[arg-type]


def validate(
    *,
    build: BuildConfig | None = None,
    retrieval: RetrievalConfig | None = None,
    sources: tuple[SourceSelectionSnapshot, ...] | None = None,
    embedding_model: ModelSelectionSnapshot | None = None,
    referenced_models: dict[object, ModelSelectionSnapshot] | None = None,
) -> tuple[str, ...]:
    actual_build = build or build_config()
    actual_embedding_model = embedding_model or ModelSelectionSnapshot(
        id=actual_build.embedding_model_id,
        model_type="embedding",
        enabled=True,
        verification_status="passed",
        embedding_dimension=1536,
    )
    return validate_configs(
        actual_build,
        retrieval or retrieval_config(),
        sources or (source(),),
        actual_embedding_model,
        referenced_models or {},
        build_capability_registry(),
    )


def test_canonical_hash_sorts_mapping_keys_but_preserves_source_order() -> None:
    source_a, source_b = uuid4(), uuid4()

    first = canonical_config_hash(
        {"params": {"b": 2, "a": 1}, "sources": [str(source_a), str(source_b)]}
    )
    reordered_keys = canonical_config_hash(
        {"sources": [str(source_a), str(source_b)], "params": {"a": 1, "b": 2}}
    )
    reordered_sources = canonical_config_hash(
        {"params": {"a": 1, "b": 2}, "sources": [str(source_b), str(source_a)]}
    )

    assert first == reordered_keys
    assert first != reordered_sources


@pytest.mark.parametrize(
    "config",
    [
        build_config(chunk_params={"chunkSize": 512, "chunkOverlap": 512}),
        build_config(
            index_structure="parent_child",
            index_structure_params={
                "parentChunkSize": 400,
                "childChunkSize": 256,
                "childChunkOverlap": 32,
            },
        ),
        build_config(
            chunk_strategy_code="paragraph",
            chunk_params={"maxChunkSize": 512, "minChunkSize": 512, "overlapParagraphs": 1},
        ),
        build_config(
            chunk_strategy_code="semantic",
            chunk_params={
                "minChunkSize": 900,
                "maxChunkSize": 800,
                "similarityThreshold": 0.75,
                "sentenceWindow": 3,
            },
        ),
    ],
)
def test_cross_field_build_rules_reject_invalid_values(config: BuildConfig) -> None:
    with pytest.raises(KnowledgeBaseConfigError) as captured:
        validate(build=config)

    assert captured.value.code == "BUILD_CONFIG_INVALID"
    assert captured.value.field_errors


def test_page_strategy_requires_page_feature_before_worker_runs() -> None:
    config = build_config(
        chunk_strategy_code="page",
        chunk_params={"maxChunkSize": 1024, "chunkOverlap": 64},
    )

    with pytest.raises(KnowledgeBaseConfigError) as captured:
        validate(build=config, sources=(source(hasPages=False),))

    assert captured.value.field_errors == {
        "parsedSourceVersionIds": ["所选解析版本缺少按页分块要求的 hasPages 能力"]
    }


def test_heading_strategy_returns_warning_when_heading_feature_is_missing() -> None:
    config = build_config(
        chunk_strategy_code="heading",
        chunk_params={
            "maxHeadingLevel": 3,
            "maxChunkSize": 768,
            "includeHeadingPath": True,
        },
    )

    warnings = validate(build=config, sources=(source(hasHeadings=False),))

    assert warnings == ("CHUNK_HEADING_FALLBACK",)


@pytest.mark.parametrize(
    "embedding_model",
    [
        ModelSelectionSnapshot(uuid4(), "llm", True, "passed", None),
        ModelSelectionSnapshot(uuid4(), "embedding", False, "passed", 1536),
        ModelSelectionSnapshot(uuid4(), "embedding", True, "stale", 1536),
        ModelSelectionSnapshot(uuid4(), "embedding", True, "passed", None),
    ],
)
def test_embedding_model_must_be_selectable_and_have_dimension(
    embedding_model: ModelSelectionSnapshot,
) -> None:
    with pytest.raises(KnowledgeBaseConfigError) as captured:
        validate(embedding_model=embedding_model)

    assert "buildConfig.embeddingModelId" in captured.value.field_errors


def test_rewrite_and_rerank_require_models_of_the_correct_type() -> None:
    llm_id = uuid4()
    rerank_id = uuid4()
    config = retrieval_config(
        query_rewrite=QueryRewriteConfig(
            code="multi_query",
            model_id=llm_id,
            params={"queryCount": 3, "rewriteMaxTokens": 256, "temperature": 0},
        ),
        rerank=RerankConfig(
            code="rerank_model",
            model_id=rerank_id,
            params={"candidateLimit": 20, "topK": 10, "scoreThreshold": 0},
        ),
    )

    with pytest.raises(KnowledgeBaseConfigError) as captured:
        validate(
            retrieval=config,
            referenced_models={llm_id: model("rerank"), rerank_id: model("llm")},
        )

    assert set(captured.value.field_errors) == {
        "retrievalConfig.queryRewrite.modelId",
        "retrievalConfig.rerank.modelId",
    }


def test_off_rewrite_and_rerank_must_not_keep_a_model() -> None:
    config = retrieval_config(
        query_rewrite=QueryRewriteConfig(code="off", model_id=uuid4(), params={}),
        rerank=RerankConfig(code="off", model_id=uuid4(), params={}),
    )

    with pytest.raises(KnowledgeBaseConfigError) as captured:
        validate(retrieval=config)

    assert set(captured.value.field_errors) == {
        "retrievalConfig.queryRewrite.modelId",
        "retrievalConfig.rerank.modelId",
    }


def test_weighted_fusion_rejects_zero_total_weight() -> None:
    config = retrieval_config(
        fusion=FusionConfig(
            strategy="weighted_score",
            rrf_k=None,
            vector_weight=0,
            keyword_weight=0,
            final_score_threshold=0,
        )
    )

    with pytest.raises(KnowledgeBaseConfigError) as captured:
        validate(retrieval=config)

    assert "retrievalConfig.hybrid" in captured.value.field_errors
