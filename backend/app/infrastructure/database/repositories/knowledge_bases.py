from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.infrastructure.database.models.knowledge_bases import (
    IndexGenerationItemModel,
    IndexGenerationModel,
    KnowledgeBaseBuildConfigRevisionModel,
    KnowledgeBaseBuildConfigSourceModel,
    KnowledgeBaseModel,
    KnowledgeBaseRetrievalRevisionModel,
)
from app.infrastructure.database.models.parsing import ParsedSourceVersionModel
from app.modules.knowledge_bases.domain import (
    InitialKnowledgeBaseGraph,
    KnowledgeBase,
    KnowledgeBaseRuntimeSnapshot,
    SourceSelectionSnapshot,
)
from app.modules.knowledge_bases.repository import KnowledgeBaseListQuery, KnowledgeBasePage


class SqlAlchemyKnowledgeBaseRepository:
    def find_by_name(self, session: Session, name: str) -> KnowledgeBase | None:
        model = session.scalar(
            select(KnowledgeBaseModel).where(
                func.lower(KnowledgeBaseModel.name) == name.casefold(),
                KnowledgeBaseModel.deleted_at.is_(None),
            )
        )
        return self._to_domain(model) if model is not None else None

    def get(
        self,
        session: Session,
        knowledge_base_id: UUID,
        *,
        for_update: bool = False,
    ) -> KnowledgeBase | None:
        statement = select(KnowledgeBaseModel).where(
            KnowledgeBaseModel.id == knowledge_base_id,
            KnowledgeBaseModel.deleted_at.is_(None),
        )
        if for_update:
            statement = statement.with_for_update()
        model = session.scalar(statement)
        return self._to_domain(model) if model is not None else None

    def list(self, session: Session, query: KnowledgeBaseListQuery) -> KnowledgeBasePage:
        conditions = [KnowledgeBaseModel.deleted_at.is_(None)]
        if query.search:
            conditions.append(KnowledgeBaseModel.name.ilike(f"%{query.search.strip()}%"))
        models = session.scalars(
            select(KnowledgeBaseModel)
            .where(*conditions)
            .order_by(KnowledgeBaseModel.updated_at.desc(), KnowledgeBaseModel.id)
            .offset((query.page - 1) * query.page_size)
            .limit(query.page_size)
        ).all()
        total = (
            session.scalar(select(func.count()).select_from(KnowledgeBaseModel).where(*conditions))
            or 0
        )
        return KnowledgeBasePage(
            items=[self._to_domain(model) for model in models],
            total=total,
            page=query.page,
            page_size=query.page_size,
        )

    def load_source_snapshots(
        self,
        session: Session,
        source_ids: tuple[UUID, ...],
    ) -> tuple[SourceSelectionSnapshot, ...]:
        if not source_ids:
            return ()
        models = session.scalars(
            select(ParsedSourceVersionModel)
            .where(ParsedSourceVersionModel.id.in_(source_ids))
            .with_for_update(key_share=True)
        ).all()
        by_id = {model.id: model for model in models}
        return tuple(
            SourceSelectionSnapshot(
                parsed_source_version_id=source_id,
                status=by_id[source_id].status,
                feature_flags=dict(by_id[source_id].feature_flags),
            )
            for source_id in source_ids
            if source_id in by_id
        )

    def add_initial_graph(self, session: Session, graph: InitialKnowledgeBaseGraph) -> None:
        knowledge_base = graph.knowledge_base
        session.add(
            KnowledgeBaseModel(
                id=knowledge_base.id,
                name=knowledge_base.name,
                description=knowledge_base.description,
                enabled=knowledge_base.enabled,
                pending_build_config_revision_id=None,
                pending_retrieval_revision_id=None,
                revision=knowledge_base.revision,
                created_at=knowledge_base.created_at,
                updated_at=knowledge_base.updated_at,
            )
        )
        session.flush()
        build = graph.build_config
        session.add(
            KnowledgeBaseBuildConfigRevisionModel(
                id=graph.build_config_revision_id,
                knowledge_base_id=knowledge_base.id,
                revision_number=1,
                embedding_model_id=build.embedding_model_id,
                embedding_model_snapshot=graph.embedding_model_snapshot,
                embedding_params=build.embedding_params,
                vector_store_code=build.vector_store_code,
                vector_store_version=build.vector_store_version,
                vector_index_code=build.vector_index_code,
                vector_index_version=build.vector_index_version,
                vector_index_params=build.vector_index_params,
                keyword_store_code=build.keyword_store_code,
                keyword_store_version=build.keyword_store_version,
                index_structure=build.index_structure,
                index_structure_params=build.index_structure_params,
                chunk_strategy_code=build.chunk_strategy_code,
                chunk_strategy_version=build.chunk_strategy_version,
                chunk_params=build.chunk_params,
                token_counter_snapshot={
                    "code": "tiktoken_cl100k_base",
                    "version": "1",
                    "estimated": True,
                },
                config_hash=graph.build_config_hash,
                created_at=knowledge_base.created_at,
            )
        )
        retrieval = graph.retrieval_config
        session.add(
            KnowledgeBaseRetrievalRevisionModel(
                id=graph.retrieval_revision_id,
                knowledge_base_id=knowledge_base.id,
                revision_number=1,
                retrieval_type=retrieval.retrieval_type,
                vector_config=retrieval.vector.as_capability_params(),
                keyword_config=retrieval.keyword.as_capability_params(),
                fusion_config={
                    "strategy": retrieval.fusion.strategy,
                    **retrieval.fusion.as_capability_params(),
                    "finalScoreThreshold": retrieval.fusion.final_score_threshold,
                },
                query_rewrite_code=retrieval.query_rewrite.code,
                query_rewrite_version="1",
                query_rewrite_model_id=retrieval.query_rewrite.model_id,
                query_rewrite_params=retrieval.query_rewrite.params,
                rerank_code=retrieval.rerank.code,
                rerank_version="1",
                rerank_model_id=retrieval.rerank.model_id,
                rerank_params=retrieval.rerank.params,
                context_window=retrieval.context_window,
                final_top_k=retrieval.final_top_k,
                config_hash=graph.retrieval_config_hash,
                created_at=knowledge_base.created_at,
            )
        )
        session.flush()
        for index, source_id in enumerate(graph.source_ids):
            session.add(
                KnowledgeBaseBuildConfigSourceModel(
                    config_revision_id=graph.build_config_revision_id,
                    parsed_source_version_id=source_id,
                    order_index=index,
                    created_at=knowledge_base.created_at,
                )
            )
        session.add(
            IndexGenerationModel(
                id=graph.generation_id,
                knowledge_base_id=knowledge_base.id,
                generation_number=1,
                build_config_revision_id=graph.build_config_revision_id,
                retrieval_revision_id=graph.retrieval_revision_id,
                status="queued",
                collection_name=graph.collection_name,
                keyword_namespace=graph.keyword_namespace,
                source_count=len(graph.source_ids),
                created_at=knowledge_base.created_at,
            )
        )
        session.flush()
        for item_id, source_id in zip(graph.item_ids, graph.source_ids, strict=True):
            session.add(
                IndexGenerationItemModel(
                    id=item_id,
                    index_generation_id=graph.generation_id,
                    parsed_source_version_id=source_id,
                    status="queued",
                    created_at=knowledge_base.created_at,
                )
            )
        model = session.get(KnowledgeBaseModel, knowledge_base.id)
        if model is None:
            raise RuntimeError("knowledge base disappeared during creation")
        model.pending_build_config_revision_id = graph.build_config_revision_id
        model.pending_retrieval_revision_id = graph.retrieval_revision_id

    def attach_operation(
        self,
        session: Session,
        *,
        knowledge_base_id: UUID,
        generation_id: UUID,
        operation_id: UUID,
    ) -> None:
        knowledge_base = session.get(KnowledgeBaseModel, knowledge_base_id)
        generation = session.get(IndexGenerationModel, generation_id)
        if knowledge_base is None or generation is None:
            raise RuntimeError("initial knowledge base graph is incomplete")
        knowledge_base.latest_build_operation_id = operation_id
        generation.operation_id = operation_id

    def find_generation_id_by_operation(
        self,
        session: Session,
        operation_id: UUID,
    ) -> UUID | None:
        return session.scalar(
            select(IndexGenerationModel.id).where(IndexGenerationModel.operation_id == operation_id)
        )

    def runtime_snapshot(
        self,
        session: Session,
        knowledge_base: KnowledgeBase,
    ) -> KnowledgeBaseRuntimeSnapshot:
        latest = session.scalar(
            select(IndexGenerationModel)
            .where(IndexGenerationModel.knowledge_base_id == knowledge_base.id)
            .order_by(IndexGenerationModel.generation_number.desc())
            .limit(1)
        )
        active = (
            session.get(IndexGenerationModel, knowledge_base.active_generation_id)
            if knowledge_base.active_generation_id is not None
            else None
        )
        selected_generation = active or latest
        build = (
            session.get(
                KnowledgeBaseBuildConfigRevisionModel,
                selected_generation.build_config_revision_id,
            )
            if selected_generation is not None
            else None
        )
        retrieval_revision_id = (
            knowledge_base.active_retrieval_revision_id
            or knowledge_base.pending_retrieval_revision_id
        )
        retrieval = (
            session.get(KnowledgeBaseRetrievalRevisionModel, retrieval_revision_id)
            if retrieval_revision_id is not None
            else None
        )
        generation_count = session.scalar(
            select(func.count())
            .select_from(IndexGenerationModel)
            .where(IndexGenerationModel.knowledge_base_id == knowledge_base.id)
        )
        return KnowledgeBaseRuntimeSnapshot(
            latest_generation_id=latest.id if latest is not None else None,
            latest_generation_status=latest.status if latest is not None else None,
            latest_generation_created_at=latest.created_at if latest is not None else None,
            active_completeness=active.completeness if active is not None else None,
            source_count=selected_generation.source_count if selected_generation else 0,
            successful_source_count=(
                selected_generation.successful_source_count if selected_generation else 0
            ),
            chunk_count=selected_generation.chunk_count if selected_generation else 0,
            embedding_model_id=build.embedding_model_id if build is not None else None,
            index_structure=build.index_structure if build is not None else None,
            retrieval_type=retrieval.retrieval_type if retrieval is not None else None,
            bot_reference_count=0,
            generation_count=generation_count or 0,
        )

    def save(self, session: Session, knowledge_base: KnowledgeBase) -> None:
        model = session.get(KnowledgeBaseModel, knowledge_base.id)
        if model is None:
            raise RuntimeError("knowledge base disappeared during update")
        model.name = knowledge_base.name
        model.description = knowledge_base.description
        model.enabled = knowledge_base.enabled
        model.revision = knowledge_base.revision
        model.updated_at = knowledge_base.updated_at
        model.deleted_at = knowledge_base.deleted_at

    @staticmethod
    def _to_domain(model: KnowledgeBaseModel) -> KnowledgeBase:
        return KnowledgeBase(
            id=model.id,
            name=model.name,
            description=model.description,
            enabled=model.enabled,
            active_generation_id=model.active_generation_id,
            active_retrieval_revision_id=model.active_retrieval_revision_id,
            pending_build_config_revision_id=model.pending_build_config_revision_id,
            pending_retrieval_revision_id=model.pending_retrieval_revision_id,
            latest_build_operation_id=model.latest_build_operation_id,
            revision=model.revision,
            created_at=model.created_at,
            updated_at=model.updated_at,
            deleted_at=model.deleted_at,
        )
