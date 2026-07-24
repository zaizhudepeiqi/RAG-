from collections.abc import Mapping

from app.modules.capabilities.registry import build_capability_registry


def _codes(category: str, *, include_disabled: bool = False) -> set[str]:
    registry = build_capability_registry()
    return {
        option.code
        for option in registry.list(category=category, include_disabled=include_disabled)
    }


def _properties(code: str) -> Mapping[str, object]:
    categories = {
        "token": "chunk_strategy",
        "semantic": "chunk_strategy",
        "vector": "retrieval_type",
        "keyword": "retrieval_type",
        "rrf": "fusion_strategy",
        "weighted_score": "fusion_strategy",
        "multi_query": "query_rewrite",
        "rerank_model": "rerank",
    }
    option = build_capability_registry().get(categories[code], code, "1")
    assert option.config_schema is not None
    properties = option.config_schema.get("properties")
    assert isinstance(properties, Mapping)
    return properties


def test_catalog_exposes_all_v1_knowledge_and_retrieval_choices() -> None:
    assert _codes("index_structure") == {"chunk", "parent_child"}
    assert _codes("index_structure", include_disabled=True) == {
        "chunk",
        "parent_child",
        "qa",
    }
    assert _codes("chunk_strategy") == {
        "token",
        "paragraph",
        "heading",
        "page",
        "semantic",
    }
    assert _codes("vector_store") == {"chroma"}
    assert _codes("vector_index") == {"hnsw"}
    assert _codes("keyword_store") == {"postgres_trigram"}
    assert _codes("retrieval_type") == {"vector", "keyword", "hybrid"}
    assert _codes("fusion_strategy") == {"rrf", "weighted_score"}
    assert _codes("query_rewrite") == {"off", "hyde", "multi_query", "step_back"}
    assert _codes("rerank") == {"off", "rerank_model", "llm_rerank"}


def test_disabled_qa_structure_is_visible_but_cannot_be_selected() -> None:
    qa = build_capability_registry().get("index_structure", "qa", "1")

    assert qa.visible is True
    assert qa.enabled is False
    assert qa.unavailable_reason == "第一版尚未实现"


def test_chunk_strategy_schemas_keep_user_tunable_defaults_and_bounds() -> None:
    token = _properties("token")
    assert token["chunkSize"] == {
        "type": "integer",
        "minimum": 64,
        "maximum": 4096,
        "default": 512,
        "unit": "tokens",
    }
    assert token["chunkOverlap"] == {
        "type": "integer",
        "minimum": 0,
        "maximum": 2048,
        "default": 64,
        "unit": "tokens",
    }

    semantic = _properties("semantic")
    assert semantic["similarityThreshold"] == {
        "type": "number",
        "minimum": 0,
        "maximum": 1,
        "default": 0.75,
    }
    assert semantic["sentenceWindow"] == {
        "type": "integer",
        "minimum": 1,
        "maximum": 10,
        "default": 3,
        "unit": "sentences",
    }


def test_source_feature_contract_distinguishes_hard_and_soft_compatibility() -> None:
    registry = build_capability_registry()

    page = registry.get("chunk_strategy", "page", "1")
    heading = registry.get("chunk_strategy", "heading", "1")
    token = registry.get("chunk_strategy", "token", "1")

    assert page.required_source_features == ("hasText", "hasPages")
    assert heading.required_source_features == ("hasText",)
    assert heading.preferred_source_features == ("hasHeadings",)
    assert token.required_source_features == ("hasText",)


def test_retrieval_capabilities_publish_complete_parameter_schemas() -> None:
    vector = _properties("vector")
    keyword = _properties("keyword")
    rrf = _properties("rrf")
    weighted = _properties("weighted_score")

    assert vector["topK"] == {
        "type": "integer",
        "minimum": 1,
        "maximum": 200,
        "default": 20,
    }
    assert keyword["scoreThreshold"] == {
        "type": "number",
        "minimum": 0,
        "maximum": 1,
        "default": 0.1,
    }
    assert rrf["rrfK"] == {
        "type": "integer",
        "minimum": 1,
        "maximum": 1000,
        "default": 60,
    }
    assert weighted["vectorWeight"] == {
        "type": "number",
        "minimum": 0,
        "maximum": 10,
        "default": 0.5,
    }


def test_rewrite_and_rerank_schemas_declare_model_type_requirements() -> None:
    registry = build_capability_registry()

    hyde = registry.get("query_rewrite", "hyde", "1")
    multi_query = registry.get("query_rewrite", "multi_query", "1")
    rerank_model = registry.get("rerank", "rerank_model", "1")
    llm_rerank = registry.get("rerank", "llm_rerank", "1")

    assert hyde.ui_schema == {"modelType": "llm"}
    assert multi_query.ui_schema == {"modelType": "llm"}
    assert rerank_model.ui_schema == {"modelType": "rerank"}
    assert llm_rerank.ui_schema == {"modelType": "llm"}

    multi_query_properties = _properties("multi_query")
    assert multi_query_properties["queryCount"] == {
        "type": "integer",
        "minimum": 2,
        "maximum": 5,
        "default": 3,
    }
    rerank_properties = _properties("rerank_model")
    assert rerank_properties["candidateLimit"] == {
        "type": "integer",
        "minimum": 2,
        "maximum": 100,
        "default": 20,
    }
