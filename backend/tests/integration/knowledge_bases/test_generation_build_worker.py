from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from app.infrastructure.database.models.knowledge_bases import (
    ChunkModel,
    IndexGenerationModel,
    KnowledgeBaseModel,
)
from app.infrastructure.database.models.parsing import ParsedBlockModel
from app.infrastructure.database.repositories.generation_builds import (
    SqlAlchemyGenerationBuildStore,
)
from app.infrastructure.database.repositories.generation_items import (
    SqlAlchemyGenerationItemStore,
)
from app.infrastructure.database.session import create_session_factory, transaction
from app.modules.knowledge_bases.generation_items import DefaultGenerationItemExecutor
from app.modules.knowledge_bases.tasks import GenerationBuildHandler
from app.modules.retrieval.vector_store import (
    VectorCollectionValidation,
    VectorHit,
    VectorRecord,
)
from app.modules.tasks.worker import NonRetryableTaskError
from sqlalchemy import Engine, func, select
from tests.integration.knowledge_bases.test_create_knowledge_base import (
    build_config,
    prepare_inputs,
    retrieval_config,
    service,
)

pytestmark = pytest.mark.integration


class FakeEmbedder:
    def embed_documents(
        self,
        *,
        model_id: UUID,
        model_snapshot: dict[str, object],
        params: dict[str, object],
        texts: object,
        expected_dimension: int,
    ) -> tuple[tuple[float, ...], ...]:
        del model_id, model_snapshot, params
        values = tuple(texts)  # type: ignore[arg-type]
        return tuple((1.0,) + (0.0,) * (expected_dimension - 1) for _ in values)


class InMemoryVectorStore:
    def __init__(self) -> None:
        self.collections: dict[str, dict[UUID, VectorRecord]] = {}

    def ensure_collection(self, name: str) -> None:
        self.collections.setdefault(name, {})

    def upsert(self, name: str, records: tuple[VectorRecord, ...]) -> None:
        self.collections.setdefault(name, {}).update(
            {record.chunk_id: record for record in records}
        )

    def query(
        self, name: str, query_embedding: tuple[float, ...], *, top_k: int
    ) -> tuple[VectorHit, ...]:
        del name, query_embedding, top_k
        return ()

    def copy_records(self, source_name: str, target_name: str, chunk_ids: tuple[UUID, ...]) -> int:
        records = self.collections[source_name]
        self.collections.setdefault(target_name, {}).update(
            {chunk_id: records[chunk_id] for chunk_id in chunk_ids}
        )
        return len(chunk_ids)

    def delete_records(self, name: str, chunk_ids: tuple[UUID, ...]) -> None:
        collection = self.collections.setdefault(name, {})
        for chunk_id in chunk_ids:
            collection.pop(chunk_id, None)

    def validate_collection(
        self,
        name: str,
        *,
        expected_count: int,
        expected_dimension: int,
    ) -> VectorCollectionValidation:
        records = self.collections[name]
        assert len(records) == expected_count
        assert all(len(record.embedding) == expected_dimension for record in records.values())
        return VectorCollectionValidation(name, "cosine", len(records), expected_dimension)

    def delete_collection(self, name: str) -> None:
        self.collections.pop(name, None)


def _add_blocks(engine: Engine, source_ids: tuple[UUID, ...], successful: int) -> None:
    with engine.begin() as connection:
        for index, source_id in enumerate(source_ids[:successful]):
            text = f"Enterprise policy source {index}"
            connection.execute(
                ParsedBlockModel.__table__.insert().values(
                    id=uuid4(),
                    parsed_source_version_id=source_id,
                    block_type="paragraph",
                    order_index=0,
                    text_content=text,
                    markdown_content=text,
                    heading_path=["Policy"],
                    page_number=1,
                    content_hash=hashlib.sha256(text.encode()).hexdigest(),
                )
            )


def _prepare_generation(
    engine: Engine,
    *,
    successful: int,
    rebuild: bool,
) -> tuple[UUID, UUID, UUID | None]:
    model_id, source_ids = prepare_inputs(engine)
    _add_blocks(engine, source_ids, successful)
    session_factory = create_session_factory(engine)
    kb_service = service(model_id)
    with transaction(session_factory) as session:
        created = kb_service.create(
            session,
            name=f"Worker KB {uuid4().hex}",
            description=None,
            source_ids=source_ids,
            build_config=build_config(model_id),
            retrieval_config=retrieval_config(),
            idempotency_key=uuid4().hex,
        )
    if not rebuild:
        return created.knowledge_base.id, created.generation_id, None

    now = datetime.now(UTC)
    with transaction(session_factory) as session:
        kb = session.get(KnowledgeBaseModel, created.knowledge_base.id)
        old = session.get(IndexGenerationModel, created.generation_id)
        assert kb is not None and old is not None
        old.status = "succeeded"
        old.completeness = "full"
        old.is_frozen = True
        old.activated_at = now
        old.finished_at = now
        kb.active_generation_id = old.id
        kb.active_retrieval_revision_id = old.retrieval_revision_id
        generation, _operation = kb_service.create_generation(
            session,
            kb.id,
            expected_revision=kb.revision,
            pending_build_config_revision_id=old.build_config_revision_id,
            pending_retrieval_revision_id=old.retrieval_revision_id,
            administrator_id=uuid4(),
            idempotency_key=uuid4().hex,
            now=now,
        )
    return created.knowledge_base.id, generation.id, created.generation_id


def _handler(engine: Engine) -> tuple[GenerationBuildHandler, InMemoryVectorStore]:
    session_factory = create_session_factory(engine)
    vectors = InMemoryVectorStore()
    items = DefaultGenerationItemExecutor(
        SqlAlchemyGenerationItemStore(session_factory), FakeEmbedder(), vectors
    )
    return GenerationBuildHandler(
        SqlAlchemyGenerationBuildStore(session_factory), items, vectors
    ), vectors


@pytest.mark.parametrize("rebuild", [False, True])
@pytest.mark.parametrize(
    ("successful", "expected_status", "activated", "raises"),
    [
        (2, "succeeded", True, False),
        (1, "partial_ready", True, False),
        (0, "failed", False, True),
    ],
)
def test_generation_worker_full_partial_and_no_success(
    database_engine: Engine,
    rebuild: bool,
    successful: int,
    expected_status: str,
    activated: bool,
    raises: bool,
) -> None:
    if rebuild and expected_status == "partial_ready":
        expected_status, activated = "partial_failed", False
    kb_id, generation_id, old_generation_id = _prepare_generation(
        database_engine, successful=successful, rebuild=rebuild
    )
    session_factory = create_session_factory(database_engine)
    with transaction(session_factory) as session:
        generation = session.get(IndexGenerationModel, generation_id)
        assert generation is not None and generation.operation_id is not None
        operation_id = generation.operation_id

    handler, _vectors = _handler(database_engine)
    if raises:
        with pytest.raises(NonRetryableTaskError, match="GENERATION_NO_SUCCESSFUL_SOURCE"):
            handler.run(operation_id)
    else:
        result = handler.run(operation_id)
        assert result["activated"] is activated

    with transaction(session_factory) as session:
        generation = session.get(IndexGenerationModel, generation_id)
        kb = session.get(KnowledgeBaseModel, kb_id)
        assert generation is not None and kb is not None
        assert generation.status == expected_status
        assert (
            session.scalar(
                select(func.count())
                .select_from(ChunkModel)
                .where(ChunkModel.index_generation_id == generation_id)
            )
            == successful
        )
        assert (kb.active_generation_id == generation_id) is activated
        if rebuild and not activated:
            assert kb.active_generation_id == old_generation_id


def test_late_worker_is_noop_and_previous_generation_gets_retention(
    database_engine: Engine,
) -> None:
    kb_id, generation_id, old_generation_id = _prepare_generation(
        database_engine, successful=2, rebuild=True
    )
    session_factory = create_session_factory(database_engine)
    with transaction(session_factory) as session:
        generation = session.get(IndexGenerationModel, generation_id)
        assert generation is not None and generation.operation_id is not None
        operation_id = generation.operation_id

    handler, _vectors = _handler(database_engine)
    handler.run(operation_id)
    duplicate = handler.run(operation_id)

    assert duplicate["duplicate"] is True
    with transaction(session_factory) as session:
        kb = session.get(KnowledgeBaseModel, kb_id)
        old = session.get(IndexGenerationModel, old_generation_id)
        assert kb is not None and old is not None
        assert kb.active_generation_id == generation_id
        assert old.retain_until is not None


def test_activation_conflict_keeps_old_generation_serving(database_engine: Engine) -> None:
    kb_id, generation_id, old_generation_id = _prepare_generation(
        database_engine, successful=2, rebuild=True
    )
    session_factory = create_session_factory(database_engine)
    with transaction(session_factory) as session:
        generation = session.get(IndexGenerationModel, generation_id)
        kb = session.get(KnowledgeBaseModel, kb_id)
        assert generation is not None and generation.operation_id is not None and kb is not None
        operation_id = generation.operation_id
        kb.latest_build_operation_id = session.scalar(
            select(IndexGenerationModel.operation_id).where(
                IndexGenerationModel.id == old_generation_id
            )
        )

    handler, _vectors = _handler(database_engine)
    with pytest.raises(NonRetryableTaskError, match="GENERATION_ACTIVATION_CONFLICT"):
        handler.run(operation_id)

    with transaction(session_factory) as session:
        kb = session.get(KnowledgeBaseModel, kb_id)
        generation = session.get(IndexGenerationModel, generation_id)
        assert kb is not None and generation is not None
        assert kb.active_generation_id == old_generation_id
        assert generation.status == "validating"
        assert generation.validation_report["activationErrorCode"] == (
            "GENERATION_ACTIVATION_CONFLICT"
        )
