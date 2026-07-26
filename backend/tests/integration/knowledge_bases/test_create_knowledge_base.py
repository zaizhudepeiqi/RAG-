from uuid import UUID, uuid4

import pytest
from app.infrastructure.database.models.knowledge_bases import (
    IndexGenerationItemModel,
    IndexGenerationModel,
    KnowledgeBaseBuildConfigRevisionModel,
    KnowledgeBaseBuildConfigSourceModel,
    KnowledgeBaseModel,
    KnowledgeBaseRetrievalRevisionModel,
)
from app.infrastructure.database.models.tasks import OperationModel, TaskOutboxModel
from app.infrastructure.database.repositories.knowledge_bases import (
    SqlAlchemyKnowledgeBaseRepository,
)
from app.infrastructure.database.repositories.tasks import (
    SqlAlchemyOperationRepository,
    SqlAlchemyOutboxRepository,
)
from app.infrastructure.database.session import create_session_factory, transaction
from app.modules.capabilities.registry import build_capability_registry
from app.modules.knowledge_bases.domain import (
    BuildConfig,
    FusionConfig,
    KeywordConfig,
    ModelSelectionSnapshot,
    QueryRewriteConfig,
    RerankConfig,
    RetrievalConfig,
    SelectedKnowledgeModel,
    VectorConfig,
)
from app.modules.knowledge_bases.errors import KnowledgeBaseConfigError
from app.modules.knowledge_bases.service import KnowledgeBaseService
from app.modules.tasks.service import TaskService
from sqlalchemy import Engine, func, select
from tests.integration.database.test_models_schema import insert_model, insert_provider
from tests.integration.database.test_parsing_schema import (
    FEATURE_FLAGS,
    insert_blob,
    insert_source,
    insert_version,
)

pytestmark = pytest.mark.integration


class FakeModelSelector:
    def __init__(self, model_id: UUID) -> None:
        self.model_id = model_id

    def require(
        self,
        _session: object,
        model_id: UUID,
        expected_type: str,
    ) -> SelectedKnowledgeModel:
        assert model_id == self.model_id
        assert expected_type == "embedding"
        return SelectedKnowledgeModel(
            selection=ModelSelectionSnapshot(
                id=model_id,
                model_type="embedding",
                enabled=True,
                verification_status="passed",
                embedding_dimension=1536,
            ),
            immutable_snapshot={
                "modelId": str(model_id),
                "modelType": "embedding",
                "embeddingDimension": 1536,
                "modelRevision": 1,
            },
        )


def build_config(model_id: UUID) -> BuildConfig:
    return BuildConfig(
        embedding_model_id=model_id,
        embedding_params={},
        vector_store_code="chroma",
        vector_store_version="1",
        vector_index_code="hnsw",
        vector_index_version="1",
        vector_index_params={"metric": "cosine"},
        keyword_store_code="postgres_trigram",
        keyword_store_version="1",
        index_structure="chunk",
        index_structure_params={},
        chunk_strategy_code="token",
        chunk_strategy_version="1",
        chunk_params={"chunkSize": 512, "chunkOverlap": 64},
    )


def retrieval_config() -> RetrievalConfig:
    return RetrievalConfig(
        retrieval_type="hybrid",
        vector=VectorConfig(20, 0.3),
        keyword=KeywordConfig(20, 0.1),
        fusion=FusionConfig("rrf", 60, None, None, 0),
        query_rewrite=QueryRewriteConfig("off", None, {}),
        rerank=RerankConfig("off", None, {}),
        context_window=0,
        final_top_k=10,
    )


def prepare_inputs(database_engine: Engine) -> tuple[UUID, tuple[UUID, UUID]]:
    with database_engine.begin() as connection:
        provider_id = insert_provider(connection, display_name=f"KB provider {uuid4().hex}")
        model_id = insert_model(
            connection,
            provider_id=provider_id,
            model_name=f"embedding-{uuid4().hex}",
            verification_status="passed",
        )
        versions = []
        for index in range(2):
            blob_id = insert_blob(connection)
            source_id = insert_source(connection, blob_id=blob_id)
            versions.append(
                insert_version(
                    connection,
                    source_id=source_id,
                    status="succeeded",
                    quality_level="full",
                    feature_flags={**FEATURE_FLAGS, "hasText": True},
                    block_count=index + 1,
                )
            )
    return model_id, (versions[0], versions[1])


def service(model_id: UUID) -> KnowledgeBaseService:
    return KnowledgeBaseService(
        SqlAlchemyKnowledgeBaseRepository(),
        FakeModelSelector(model_id),
        build_capability_registry(),
        TaskService(SqlAlchemyOperationRepository(), SqlAlchemyOutboxRepository()),
        operation_retention_days=90,
    )


class FailingTaskService:
    def create_operation(self, *_args: object, **_kwargs: object) -> object:
        raise RuntimeError("simulated outbox failure")


def test_create_writes_complete_initial_graph_in_one_transaction(
    database_engine: Engine,
) -> None:
    model_id, source_ids = prepare_inputs(database_engine)
    session_factory = create_session_factory(database_engine)
    name = f"Enterprise KB {uuid4().hex}"

    with transaction(session_factory) as session:
        created = service(model_id).create(
            session,
            name=name,
            description="Internal policies",
            source_ids=source_ids,
            build_config=build_config(model_id),
            retrieval_config=retrieval_config(),
            idempotency_key=uuid4().hex,
        )

    with transaction(session_factory) as session:
        knowledge_base = session.get(KnowledgeBaseModel, created.knowledge_base.id)
        generation = session.get(IndexGenerationModel, created.generation_id)
        assert knowledge_base is not None
        assert generation is not None
        assert knowledge_base.active_generation_id is None
        assert (
            knowledge_base.pending_build_config_revision_id == generation.build_config_revision_id
        )
        assert knowledge_base.pending_retrieval_revision_id == generation.retrieval_revision_id
        assert knowledge_base.latest_build_operation_id == created.operation_id
        assert generation.status == "queued"
        assert generation.operation_id == created.operation_id
        assert generation.source_count == 2
        assert (
            session.scalar(
                select(func.count())
                .select_from(KnowledgeBaseBuildConfigRevisionModel)
                .where(KnowledgeBaseBuildConfigRevisionModel.knowledge_base_id == knowledge_base.id)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(KnowledgeBaseRetrievalRevisionModel)
                .where(KnowledgeBaseRetrievalRevisionModel.knowledge_base_id == knowledge_base.id)
            )
            == 1
        )
        bound_sources = tuple(
            session.scalars(
                select(KnowledgeBaseBuildConfigSourceModel.parsed_source_version_id)
                .where(
                    KnowledgeBaseBuildConfigSourceModel.config_revision_id
                    == generation.build_config_revision_id
                )
                .order_by(KnowledgeBaseBuildConfigSourceModel.order_index)
            ).all()
        )
        assert bound_sources == source_ids
        assert (
            session.scalar(
                select(func.count())
                .select_from(IndexGenerationItemModel)
                .where(IndexGenerationItemModel.index_generation_id == generation.id)
            )
            == 2
        )
        assert session.get(OperationModel, created.operation_id) is not None
        outbox = session.scalar(
            select(TaskOutboxModel).where(TaskOutboxModel.operation_id == created.operation_id)
        )
        assert outbox is not None
        assert outbox.event_type == "knowledge_base.generation.requested"


def test_create_rolls_back_the_complete_graph_when_operation_creation_fails(
    database_engine: Engine,
) -> None:
    model_id, source_ids = prepare_inputs(database_engine)
    session_factory = create_session_factory(database_engine)
    name = f"Rollback KB {uuid4().hex}"
    failing_service = KnowledgeBaseService(
        SqlAlchemyKnowledgeBaseRepository(),
        FakeModelSelector(model_id),
        build_capability_registry(),
        FailingTaskService(),  # type: ignore[arg-type]
        operation_retention_days=90,
    )

    with pytest.raises(RuntimeError, match="simulated outbox failure"):
        with transaction(session_factory) as session:
            failing_service.create(
                session,
                name=name,
                description=None,
                source_ids=source_ids,
                build_config=build_config(model_id),
                retrieval_config=retrieval_config(),
                idempotency_key=uuid4().hex,
            )

    with transaction(session_factory) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(KnowledgeBaseModel)
                .where(KnowledgeBaseModel.name == name)
            )
            == 0
        )


def test_create_rejects_a_request_containing_an_unknown_parsed_version(
    database_engine: Engine,
) -> None:
    model_id, source_ids = prepare_inputs(database_engine)
    session_factory = create_session_factory(database_engine)

    with pytest.raises(KnowledgeBaseConfigError) as caught:
        with transaction(session_factory) as session:
            service(model_id).create(
                session,
                name=f"Invalid source KB {uuid4().hex}",
                description=None,
                source_ids=(source_ids[0], uuid4()),
                build_config=build_config(model_id),
                retrieval_config=retrieval_config(),
                idempotency_key=uuid4().hex,
            )

    assert caught.value.code == "BUILD_CONFIG_INVALID"
    assert "parsedSourceVersionIds" in caught.value.field_errors
