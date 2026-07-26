from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.infrastructure.database.models.knowledge_bases import (
    ChunkAssetModel,
    ChunkModel,
    ChunkSourceBlockModel,
    IndexGenerationItemModel,
    IndexGenerationModel,
    KnowledgeBaseModel,
)
from app.infrastructure.database.models.tasks import OperationModel
from app.infrastructure.database.repositories.knowledge_bases import (
    SqlAlchemyKnowledgeBaseRepository,
)
from app.infrastructure.database.session import transaction
from app.modules.knowledge_bases.tasks import (
    GenerationBuildItem,
    GenerationBuildSnapshot,
    GenerationFinalization,
    GenerationValidationSummary,
)


class SqlAlchemyGenerationBuildStore:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        retention_days: int = 7,
    ) -> None:
        self._session_factory = session_factory
        self._retention = timedelta(days=retention_days)
        self._knowledge_bases = SqlAlchemyKnowledgeBaseRepository()

    def load(self, operation_id: UUID) -> GenerationBuildSnapshot | None:
        with transaction(self._session_factory) as session:
            generation = session.scalar(
                select(IndexGenerationModel).where(
                    IndexGenerationModel.operation_id == operation_id
                )
            )
            if generation is None:
                return None
            knowledge_base = session.get(KnowledgeBaseModel, generation.knowledge_base_id)
            build = self._knowledge_bases.get_build_config_revision(
                session, generation.build_config_revision_id
            )
            operation = session.get(OperationModel, operation_id)
            if knowledge_base is None or build is None or operation is None:
                return None
            dimension = build.embedding_model_snapshot.get("embeddingDimension")
            if isinstance(dimension, bool) or not isinstance(dimension, int) or dimension <= 0:
                return None
            return GenerationBuildSnapshot(
                operation_id=operation_id,
                generation_id=generation.id,
                knowledge_base_id=generation.knowledge_base_id,
                status=generation.status,
                collection_name=generation.collection_name,
                active_generation_id=knowledge_base.active_generation_id,
                build_config=build.config,
                embedding_model_snapshot=dict(build.embedding_model_snapshot),
                embedding_dimension=dimension,
            )

    def claim(self, generation_id: UUID, started_at: datetime) -> bool:
        with transaction(self._session_factory) as session:
            generation = self._locked_generation(session, generation_id)
            if generation is None or generation.is_frozen:
                return False
            if generation.status == "building":
                return True
            if generation.status != "queued":
                return False
            generation.status = "building"
            generation.started_at = started_at
            return True

    def list_items(self, generation_id: UUID) -> tuple[GenerationBuildItem, ...]:
        with transaction(self._session_factory) as session:
            items = session.scalars(
                select(IndexGenerationItemModel)
                .where(IndexGenerationItemModel.index_generation_id == generation_id)
                .order_by(IndexGenerationItemModel.created_at, IndexGenerationItemModel.id)
            ).all()
            return tuple(
                GenerationBuildItem(
                    id=item.id,
                    parsed_source_version_id=item.parsed_source_version_id,
                    status=item.status,
                    stage_progress=dict(item.stage_progress),
                )
                for item in items
            )

    def fail_item(
        self,
        item_id: UUID,
        *,
        error_code: str,
        retryable: bool,
        finished_at: datetime,
    ) -> None:
        with transaction(self._session_factory) as session:
            item = session.scalar(
                select(IndexGenerationItemModel)
                .where(IndexGenerationItemModel.id == item_id)
                .with_for_update()
            )
            if item is None or item.status in {"succeeded", "failed"}:
                return
            generation = session.get(IndexGenerationModel, item.index_generation_id)
            if generation is None or generation.is_frozen:
                return
            chunk_ids = select(ChunkModel.id).where(ChunkModel.generation_item_id == item.id)
            session.execute(delete(ChunkAssetModel).where(ChunkAssetModel.chunk_id.in_(chunk_ids)))
            session.execute(
                delete(ChunkSourceBlockModel).where(ChunkSourceBlockModel.chunk_id.in_(chunk_ids))
            )
            session.execute(delete(ChunkModel).where(ChunkModel.generation_item_id == item.id))
            item.status = "failed"
            item.chunk_count = 0
            item.vector_count = 0
            item.error_code = error_code
            item.error_message = "索引构建失败"
            item.retryable = retryable
            item.finished_at = finished_at

    def prepare_validation(
        self, generation_id: UUID, started_at: datetime
    ) -> GenerationValidationSummary:
        with transaction(self._session_factory) as session:
            generation = self._locked_generation(session, generation_id)
            if generation is None:
                raise RuntimeError("generation does not exist")
            items = session.scalars(
                select(IndexGenerationItemModel).where(
                    IndexGenerationItemModel.index_generation_id == generation_id
                )
            ).all()
            if any(item.status not in {"succeeded", "failed"} for item in items):
                raise RuntimeError("generation items are not terminal")
            if generation.status == "building":
                generation.status = "validating"
            elif generation.status != "validating":
                raise RuntimeError("generation is not ready for validation")

            successful_ids = tuple(item.id for item in items if item.status == "succeeded")
            successful = len(successful_ids)
            failed = len(items) - successful
            chunk_count = self._chunk_count(session, generation_id, successful_ids)
            vector_count = self._indexable_count(session, generation_id, successful_ids)
            source_mapping_count = self._mapped_chunk_count(session, generation_id, successful_ids)
            item_counts_valid = all(
                item.chunk_count > 0 and item.vector_count > 0
                for item in items
                if item.status == "succeeded"
            )
            report: dict[str, object] = {
                "validatedAt": started_at.isoformat(),
                "checks": {
                    "successfulItemCounts": item_counts_valid,
                    "sourceMappingsComplete": source_mapping_count == chunk_count,
                    "keywordRowCount": vector_count,
                    "vectorRecordCount": vector_count,
                    "generationIsolation": True,
                },
            }
            report["passed"] = bool(
                successful
                and item_counts_valid
                and chunk_count > 0
                and vector_count > 0
                and source_mapping_count == chunk_count
            )
            generation.successful_source_count = successful
            generation.failed_source_count = failed
            generation.chunk_count = chunk_count
            generation.vector_count = vector_count
            generation.validation_report = report
            return GenerationValidationSummary(
                source_count=generation.source_count,
                successful_source_count=successful,
                failed_source_count=failed,
                chunk_count=chunk_count,
                vector_count=vector_count,
                report=report,
            )

    def fail_validation(
        self,
        generation_id: UUID,
        *,
        error_code: str,
        finished_at: datetime,
    ) -> None:
        with transaction(self._session_factory) as session:
            generation = self._locked_generation(session, generation_id)
            if generation is None or generation.status != "validating":
                return
            generation.status = "failed"
            generation.finished_at = finished_at
            generation.retain_until = finished_at + self._retention
            generation.validation_report = {
                **generation.validation_report,
                "passed": False,
                "errorCode": error_code,
            }

    def finalize(
        self,
        snapshot: GenerationBuildSnapshot,
        summary: GenerationValidationSummary,
        finished_at: datetime,
    ) -> GenerationFinalization:
        with transaction(self._session_factory) as session:
            generation = self._locked_generation(session, snapshot.generation_id)
            knowledge_base = session.scalar(
                select(KnowledgeBaseModel)
                .where(KnowledgeBaseModel.id == snapshot.knowledge_base_id)
                .with_for_update()
            )
            if generation is None or knowledge_base is None:
                raise RuntimeError("generation aggregate does not exist")
            if generation.status in {"succeeded", "partial_ready"}:
                return GenerationFinalization(generation.status, activated=True)
            if generation.status != "validating":
                return GenerationFinalization(generation.status, activated=False)

            if summary.successful_source_count == 0 or not summary.report.get("passed"):
                generation.status = "failed"
                generation.finished_at = finished_at
                generation.retain_until = finished_at + self._retention
                return GenerationFinalization("failed", activated=False)

            is_partial = summary.failed_source_count > 0
            if is_partial and knowledge_base.active_generation_id is not None:
                generation.status = "partial_failed"
                generation.finished_at = finished_at
                generation.retain_until = finished_at + self._retention
                return GenerationFinalization("partial_failed", activated=False)

            activation_matches = (
                knowledge_base.latest_build_operation_id == snapshot.operation_id
                and knowledge_base.pending_build_config_revision_id
                == generation.build_config_revision_id
                and knowledge_base.pending_retrieval_revision_id == generation.retrieval_revision_id
            )
            if not activation_matches:
                generation.validation_report = {
                    **generation.validation_report,
                    "activationErrorCode": "GENERATION_ACTIVATION_CONFLICT",
                }
                return GenerationFinalization("validating", activated=False, conflict=True)

            previous_generation_id = knowledge_base.active_generation_id
            if previous_generation_id is not None:
                previous = session.get(IndexGenerationModel, previous_generation_id)
                if previous is not None:
                    previous.retain_until = finished_at + self._retention

            generation.status = "partial_ready" if is_partial else "succeeded"
            generation.completeness = "partial" if is_partial else "full"
            generation.is_frozen = True
            generation.finished_at = finished_at
            generation.activated_at = finished_at
            generation.retain_until = None
            knowledge_base.active_generation_id = generation.id
            knowledge_base.active_retrieval_revision_id = generation.retrieval_revision_id
            knowledge_base.pending_build_config_revision_id = None
            knowledge_base.pending_retrieval_revision_id = None
            knowledge_base.revision += 1
            knowledge_base.updated_at = finished_at
            return GenerationFinalization(generation.status, activated=True)

    @staticmethod
    def _locked_generation(session: Session, generation_id: UUID) -> IndexGenerationModel | None:
        return session.scalar(
            select(IndexGenerationModel)
            .where(IndexGenerationModel.id == generation_id)
            .with_for_update()
        )

    @staticmethod
    def _chunk_count(
        session: Session, generation_id: UUID, successful_ids: tuple[UUID, ...]
    ) -> int:
        if not successful_ids:
            return 0
        return int(
            session.scalar(
                select(func.count())
                .select_from(ChunkModel)
                .where(
                    ChunkModel.index_generation_id == generation_id,
                    ChunkModel.generation_item_id.in_(successful_ids),
                )
            )
            or 0
        )

    @staticmethod
    def _indexable_count(
        session: Session, generation_id: UUID, successful_ids: tuple[UUID, ...]
    ) -> int:
        if not successful_ids:
            return 0
        return int(
            session.scalar(
                select(func.count())
                .select_from(ChunkModel)
                .where(
                    ChunkModel.index_generation_id == generation_id,
                    ChunkModel.generation_item_id.in_(successful_ids),
                    ChunkModel.chunk_kind.in_(("chunk", "child")),
                )
            )
            or 0
        )

    @staticmethod
    def _mapped_chunk_count(
        session: Session, generation_id: UUID, successful_ids: tuple[UUID, ...]
    ) -> int:
        if not successful_ids:
            return 0
        return int(
            session.scalar(
                select(func.count(func.distinct(ChunkSourceBlockModel.chunk_id)))
                .select_from(ChunkSourceBlockModel)
                .join(ChunkModel, ChunkModel.id == ChunkSourceBlockModel.chunk_id)
                .where(
                    ChunkModel.index_generation_id == generation_id,
                    ChunkModel.generation_item_id.in_(successful_ids),
                )
            )
            or 0
        )
