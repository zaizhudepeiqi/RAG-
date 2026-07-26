from uuid import uuid4

import pytest
from app.infrastructure.keyword.postgres_trigram import (
    PostgreSQLTrigramKeywordStoreAdapter,
    build_candidate_statement,
    normalize_keyword_query,
)
from sqlalchemy import Engine, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session
from tests.integration.database.test_knowledge_retrieval_schema import _insert_graph

pytestmark = pytest.mark.integration


def _insert_chunk(
    session: Session,
    graph: dict[str, object],
    *,
    order_index: int,
    content: str,
    heading_path: list[str] | None = None,
):
    chunk_id = uuid4()
    session.execute(
        text(
            """
            INSERT INTO chunks (
                id, index_generation_id, generation_item_id,
                parsed_source_version_id, chunk_kind, order_index,
                text_content, searchable_text, normalized_text_hash,
                token_count, token_counter_code, token_counter_version,
                heading_path
            ) VALUES (
                :id, :generation_id, :item_id,
                (SELECT parsed_source_version_id FROM index_generation_items WHERE id = :item_id),
                'chunk', :order_index,
                :content, :content, :hash, 3, 'test', '1', :heading_path
            )
            """
        ),
        {
            **graph,
            "id": chunk_id,
            "order_index": order_index,
            "content": content,
            "hash": f"{order_index + 1:064x}",
            "heading_path": heading_path,
        },
    )
    return chunk_id


def _insert_noise(session: Session, graph: dict[str, object], count: int = 500) -> None:
    session.execute(
        text(
            """
            INSERT INTO chunks (
                id, index_generation_id, generation_item_id,
                parsed_source_version_id, chunk_kind, order_index,
                text_content, searchable_text, normalized_text_hash,
                token_count, token_counter_code, token_counter_version
            )
            SELECT
                gen_random_uuid(), :generation_id, :item_id,
                (SELECT parsed_source_version_id FROM index_generation_items WHERE id = :item_id),
                'chunk', 100 + value,
                'unrelated record ' || value, 'unrelated record ' || value,
                md5(value::text) || md5(value::text), 3, 'test', '1'
            FROM generate_series(1, :count) AS value
            """
        ),
        {**graph, "count": count},
    )


def test_trigram_query_ranks_phrase_filters_generation_and_uses_gin(
    database_engine: Engine,
) -> None:
    with Session(database_engine) as session, session.begin():
        graph = _insert_graph(session.connection())
        exact_id = _insert_chunk(
            session,
            graph,
            order_index=1,
            content="enterprise policy handbook",
            heading_path=["Policy"],
        )
        _insert_chunk(
            session,
            graph,
            order_index=2,
            content="enterprise handbook policy",
        )
        _insert_noise(session, graph)
        other_graph = _insert_graph(session.connection())
        other_id = _insert_chunk(
            session,
            other_graph,
            order_index=1,
            content="enterprise policy handbook",
        )
        adapter = PostgreSQLTrigramKeywordStoreAdapter()

        hits = adapter.query(
            session,
            generation_id=graph["generation_id"],
            query="enterprise policy",
            top_k=10,
            score_threshold=0,
            candidate_limit=20,
        )

        assert hits[0].chunk_id == exact_id
        assert hits[0].phrase_match is True
        assert other_id not in {hit.chunk_id for hit in hits}
        statement = build_candidate_statement(
            graph["generation_id"],
            normalize_keyword_query("enterprise policy"),
            candidate_limit=20,
        )
        compiled = statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
        explain_sql = str(compiled).replace("%%", "%")
        session.execute(text("ANALYZE chunks"))
        session.execute(text("SET LOCAL enable_seqscan = off"))
        plan = "\n".join(str(row[0]) for row in session.execute(text(f"EXPLAIN {explain_sql}")))
        assert "Seq Scan on chunks" not in plan
        assert "Index Cond: (index_generation_id =" in plan
        trigram_plan = "\n".join(
            str(row[0])
            for row in session.execute(
                text("EXPLAIN SELECT id FROM chunks WHERE searchable_text % 'enterprise policy'")
            )
        )
        assert "chunks_searchable_trgm_idx" in trigram_plan


def test_short_query_fallback_is_generation_scoped(database_engine: Engine) -> None:
    with Session(database_engine) as session, session.begin():
        graph = _insert_graph(session.connection())
        chunk_id = _insert_chunk(session, graph, order_index=1, content="企业制度")

        hits = PostgreSQLTrigramKeywordStoreAdapter().query(
            session,
            generation_id=graph["generation_id"],
            query="企",
            top_k=5,
            score_threshold=0,
            candidate_limit=10,
        )

        assert [hit.chunk_id for hit in hits] == [chunk_id]
        assert hits[0].short_query_fallback is True
