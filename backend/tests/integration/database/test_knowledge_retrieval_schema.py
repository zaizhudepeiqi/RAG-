import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, Engine, inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from tests.integration.database.test_models_schema import insert_model, insert_provider
from tests.integration.database.test_parsing_schema import (
    FEATURE_FLAGS,
    insert_blob,
    insert_source,
    insert_version,
)

pytestmark = pytest.mark.integration

KNOWLEDGE_TABLES = {
    "knowledge_bases",
    "kb_build_config_revisions",
    "kb_build_config_sources",
    "kb_retrieval_revisions",
    "index_generations",
    "index_generation_items",
    "chunks",
    "chunk_source_blocks",
    "chunk_assets",
}


def _insert_graph(connection: Connection) -> dict[str, UUID]:
    fixture_key = uuid4().hex
    provider_id = insert_provider(connection, display_name=f"Provider {fixture_key}")
    model_id = insert_model(
        connection,
        provider_id=provider_id,
        verification_status="passed",
    )
    blob_id = insert_blob(connection)
    source_id = insert_source(connection, blob_id=blob_id)
    version_id = insert_version(
        connection,
        source_id=source_id,
        status="succeeded",
        quality_level="full",
        feature_flags={**FEATURE_FLAGS, "hasText": True},
        block_count=1,
    )
    block_id = uuid4()
    asset_id = uuid4()
    connection.execute(
        text(
            """
            INSERT INTO parsed_blocks (
                id, parsed_source_version_id, block_type, order_index,
                text_content, content_hash
            ) VALUES (
                :id, :version_id, 'paragraph', 0, 'enterprise knowledge', :hash
            )
            """
        ),
        {"id": block_id, "version_id": version_id, "hash": "d" * 64},
    )
    connection.execute(
        text(
            """
            INSERT INTO parsed_assets (
                id, parsed_source_version_id, asset_type, mime_type,
                storage_key, sha256, size_bytes, order_index
            ) VALUES (
                :id, :version_id, 'image', 'image/png', :storage_key,
                :hash, 10, 0
            )
            """
        ),
        {
            "id": asset_id,
            "version_id": version_id,
            "storage_key": f"assets/{asset_id}",
            "hash": "e" * 64,
        },
    )

    kb_id = uuid4()
    build_revision_id = uuid4()
    retrieval_revision_id = uuid4()
    generation_id = uuid4()
    item_id = uuid4()
    chunk_id = uuid4()
    connection.execute(
        text(
            """
            INSERT INTO knowledge_bases (id, name)
            VALUES (:id, :name)
            """
        ),
        {"id": kb_id, "name": f"Schema fixture {fixture_key}"},
    )
    connection.execute(
        text(
            """
            INSERT INTO kb_build_config_revisions (
                id, knowledge_base_id, revision_number, embedding_model_id,
                embedding_model_snapshot, embedding_params, vector_store_code,
                vector_store_version, vector_index_code, vector_index_version,
                vector_index_params, keyword_store_code, keyword_store_version,
                index_structure, chunk_strategy_code, chunk_strategy_version,
                chunk_params, token_counter_snapshot, config_hash
            ) VALUES (
                :id, :kb_id, 1, :model_id, '{}'::jsonb, '{}'::jsonb,
                'chroma', '1', 'hnsw', '1', CAST(:vector_params AS jsonb),
                'postgres_trigram', '1', 'chunk', 'token', '1',
                CAST(:chunk_params AS jsonb), CAST(:token_counter AS jsonb), :hash
            )
            """
        ),
        {
            "id": build_revision_id,
            "kb_id": kb_id,
            "model_id": model_id,
            "hash": "a" * 64,
            "vector_params": json.dumps({"metric": "cosine"}),
            "chunk_params": json.dumps({"chunkSize": 512, "chunkOverlap": 64}),
            "token_counter": json.dumps({"code": "cl100k_base", "version": "1"}),
        },
    )
    connection.execute(
        text(
            """
            INSERT INTO kb_build_config_sources (
                config_revision_id, parsed_source_version_id, order_index
            ) VALUES (:config_id, :version_id, 0)
            """
        ),
        {"config_id": build_revision_id, "version_id": version_id},
    )
    connection.execute(
        text(
            """
            INSERT INTO kb_retrieval_revisions (
                id, knowledge_base_id, revision_number, retrieval_type,
                vector_config, keyword_config, fusion_config,
                query_rewrite_code, query_rewrite_version, query_rewrite_params,
                rerank_code, rerank_version, rerank_params,
                context_window, final_top_k, config_hash
            ) VALUES (
                :id, :kb_id, 1, 'hybrid', CAST(:vector_config AS jsonb),
                CAST(:keyword_config AS jsonb), CAST(:fusion_config AS jsonb),
                'off', '1', '{}'::jsonb, 'off', '1', '{}'::jsonb,
                0, 10, :hash
            )
            """
        ),
        {
            "id": retrieval_revision_id,
            "kb_id": kb_id,
            "hash": "b" * 64,
            "vector_config": json.dumps({"topK": 20}),
            "keyword_config": json.dumps({"topK": 20}),
            "fusion_config": json.dumps({"strategy": "rrf"}),
        },
    )
    connection.execute(
        text(
            """
            INSERT INTO index_generations (
                id, knowledge_base_id, generation_number, build_config_revision_id,
                retrieval_revision_id, status, collection_name, keyword_namespace,
                source_count
            ) VALUES (
                :id, :kb_id, 1, :build_id, :retrieval_id, 'building',
                :collection_name, :keyword_namespace, 1
            )
            """
        ),
        {
            "id": generation_id,
            "kb_id": kb_id,
            "build_id": build_revision_id,
            "retrieval_id": retrieval_revision_id,
            "collection_name": f"kb_{kb_id}_gen_1",
            "keyword_namespace": uuid4(),
        },
    )
    connection.execute(
        text(
            """
            INSERT INTO index_generation_items (
                id, index_generation_id, parsed_source_version_id, status
            ) VALUES (:id, :generation_id, :version_id, 'succeeded')
            """
        ),
        {"id": item_id, "generation_id": generation_id, "version_id": version_id},
    )
    connection.execute(
        text(
            """
            INSERT INTO chunks (
                id, index_generation_id, generation_item_id,
                parsed_source_version_id, chunk_kind, order_index,
                text_content, searchable_text, normalized_text_hash,
                token_count, token_counter_code, token_counter_version
            ) VALUES (
                :id, :generation_id, :item_id, :version_id, 'chunk', 0,
                'enterprise knowledge', 'enterprise knowledge', :hash,
                2, 'cl100k_base', '1'
            )
            """
        ),
        {
            "id": chunk_id,
            "generation_id": generation_id,
            "item_id": item_id,
            "version_id": version_id,
            "hash": "c" * 64,
        },
    )
    connection.execute(
        text(
            """
            INSERT INTO chunk_source_blocks (chunk_id, parsed_block_id, order_index)
            VALUES (:chunk_id, :block_id, 0)
            """
        ),
        {"chunk_id": chunk_id, "block_id": block_id},
    )
    return {
        "kb_id": kb_id,
        "build_revision_id": build_revision_id,
        "retrieval_revision_id": retrieval_revision_id,
        "generation_id": generation_id,
        "item_id": item_id,
        "chunk_id": chunk_id,
        "asset_id": asset_id,
    }


def test_knowledge_retrieval_tables_and_indexes_exist(database_engine: Engine) -> None:
    inspector = inspect(database_engine)

    assert KNOWLEDGE_TABLES <= set(inspector.get_table_names())
    chunk_indexes = {item["name"] for item in inspector.get_indexes("chunks")}
    assert {
        "chunks_generation_kind_idx",
        "chunks_searchable_trgm_idx",
        "chunks_source_idx",
    } <= chunk_indexes

    with database_engine.connect() as connection:
        index_definition = connection.scalar(
            text(
                """
                SELECT indexdef FROM pg_indexes
                WHERE schemaname = current_schema()
                  AND indexname = 'chunks_searchable_trgm_idx'
                """
            )
        )
    assert index_definition is not None
    assert "USING gin" in index_definition
    assert "gin_trgm_ops" in index_definition


def test_valid_graph_supports_atomic_active_pointers(database_engine: Engine) -> None:
    with database_engine.begin() as connection:
        graph = _insert_graph(connection)
        connection.execute(
            text(
                """
                UPDATE index_generations
                SET status = 'succeeded', completeness = 'full',
                    is_frozen = true, activated_at = now()
                WHERE id = :generation_id
                """
            ),
            graph,
        )
        connection.execute(
            text(
                """
                UPDATE knowledge_bases
                SET active_generation_id = :generation_id,
                    active_retrieval_revision_id = :retrieval_revision_id,
                    revision = revision + 1
                WHERE id = :kb_id
                """
            ),
            graph,
        )


@pytest.mark.parametrize(
    ("statement", "value"),
    [
        ("UPDATE index_generations SET status = :value WHERE id = :generation_id", "unknown"),
        ("UPDATE index_generations SET source_count = :value WHERE id = :generation_id", -1),
        ("UPDATE index_generations SET generation_number = :value WHERE id = :generation_id", 0),
    ],
)
def test_generation_rejects_invalid_status_or_counts(
    database_engine: Engine,
    statement: str,
    value: object,
) -> None:
    with pytest.raises(IntegrityError):
        with database_engine.begin() as connection:
            graph = _insert_graph(connection)
            connection.execute(
                text(statement),
                {**graph, "value": value},
            )


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE index_generation_items SET status = 'validating' WHERE id = :item_id",
        "UPDATE chunks SET searchable_text = 'changed' WHERE id = :chunk_id",
        "DELETE FROM chunk_source_blocks WHERE chunk_id = :chunk_id",
        """
        INSERT INTO chunk_assets (chunk_id, parsed_asset_id)
        VALUES (:chunk_id, :asset_id)
        """,
    ],
)
def test_frozen_generation_rejects_item_chunk_and_mapping_mutation(
    database_engine: Engine,
    statement: str,
) -> None:
    with pytest.raises(DBAPIError, match="frozen generation"):
        with database_engine.begin() as connection:
            graph = _insert_graph(connection)
            connection.execute(
                text(
                    """
                    UPDATE index_generations
                    SET status = 'succeeded', completeness = 'full',
                        is_frozen = true, activated_at = now()
                    WHERE id = :generation_id
                    """
                ),
                graph,
            )
            connection.execute(text(statement), graph)
