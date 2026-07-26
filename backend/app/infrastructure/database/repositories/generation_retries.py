from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.infrastructure.database.models.knowledge_bases import (
    IndexGenerationItemModel,
    IndexGenerationModel,
    KnowledgeBaseModel,
)
from app.infrastructure.database.models.tasks import OperationModel
from app.infrastructure.database.session import transaction
from app.modules.knowledge_bases.generation_retries import GenerationRetryPreparation
from app.modules.tasks.worker import NonRetryableTaskError


class SqlAlchemyGenerationRetryStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def prepare(self, operation_id: UUID) -> GenerationRetryPreparation:
        with transaction(self._session_factory) as session:
            operation = session.get(OperationModel, operation_id)
            if operation is None or operation.task_type != "knowledge_base_build_retry":
                raise NonRetryableTaskError("GENERATION_RETRY_NOT_FOUND")

            prepared = session.scalar(
                select(IndexGenerationModel).where(
                    IndexGenerationModel.operation_id == operation_id
                )
            )
            if prepared is not None:
                operation.target_id = prepared.id
                return GenerationRetryPreparation(
                    generation_id=prepared.id,
                    repair_created=prepared.generation_number > 1
                    and prepared.is_frozen is False
                    and any(
                        item.source_copy_from_item_id is not None
                        for item in self._items(session, prepared.id)
                    ),
                )

            source = session.scalar(
                select(IndexGenerationModel)
                .where(IndexGenerationModel.id == operation.target_id)
                .with_for_update()
            )
            if source is None:
                raise NonRetryableTaskError("GENERATION_NOT_FOUND")
            knowledge_base = session.scalar(
                select(KnowledgeBaseModel)
                .where(KnowledgeBaseModel.id == source.knowledge_base_id)
                .with_for_update()
            )
            if knowledge_base is None:
                raise NonRetryableTaskError("GENERATION_NOT_FOUND")
            self._guard_no_running_generation(session, source)
            source_items = self._items(session, source.id)
            if not any(item.status == "failed" for item in source_items):
                raise NonRetryableTaskError("GENERATION_NO_FAILED_ITEM")

            if source.status in {"failed", "partial_failed"} and not source.is_frozen:
                self._prepare_staged_retry(
                    source,
                    source_items,
                    knowledge_base,
                    operation,
                    datetime.now(UTC),
                )
                return GenerationRetryPreparation(source.id, repair_created=False)
            if (
                source.status == "partial_ready"
                and source.is_frozen
                and knowledge_base.active_generation_id == source.id
            ):
                repair = self._prepare_repair(
                    session,
                    source,
                    source_items,
                    knowledge_base,
                    operation,
                    datetime.now(UTC),
                )
                return GenerationRetryPreparation(repair.id, repair_created=True)
            raise NonRetryableTaskError("GENERATION_RETRY_CONFLICT")

    @staticmethod
    def _prepare_staged_retry(
        generation: IndexGenerationModel,
        items: tuple[IndexGenerationItemModel, ...],
        knowledge_base: KnowledgeBaseModel,
        operation: OperationModel,
        now: datetime,
    ) -> None:
        if knowledge_base.pending_build_config_revision_id not in {
            None,
            generation.build_config_revision_id,
        } or knowledge_base.pending_retrieval_revision_id not in {
            None,
            generation.retrieval_revision_id,
        }:
            raise NonRetryableTaskError("GENERATION_CONFIG_CHANGED")
        for item in items:
            if item.status != "failed":
                continue
            item.status = "queued"
            item.stage_progress = {"retry": "queued"}
            item.chunk_count = 0
            item.vector_count = 0
            item.error_code = None
            item.error_message = None
            item.retryable = False
            item.started_at = None
            item.finished_at = None
        generation.status = "queued"
        generation.finished_at = None
        generation.retain_until = None
        generation.failed_source_count = 0
        generation.validation_report = {
            "retryPreparedAt": now.isoformat(),
            "retryOperationId": str(operation.id),
        }
        knowledge_base.pending_build_config_revision_id = generation.build_config_revision_id
        knowledge_base.pending_retrieval_revision_id = generation.retrieval_revision_id
        knowledge_base.latest_build_operation_id = operation.id
        knowledge_base.revision += 1
        knowledge_base.updated_at = now

    def _prepare_repair(
        self,
        session: Session,
        source: IndexGenerationModel,
        source_items: tuple[IndexGenerationItemModel, ...],
        knowledge_base: KnowledgeBaseModel,
        operation: OperationModel,
        now: datetime,
    ) -> IndexGenerationModel:
        if (
            knowledge_base.pending_build_config_revision_id is not None
            or knowledge_base.pending_retrieval_revision_id is not None
        ):
            raise NonRetryableTaskError("GENERATION_CONFIG_CHANGED")
        generation_number = (
            int(
                session.scalar(
                    select(func.max(IndexGenerationModel.generation_number)).where(
                        IndexGenerationModel.knowledge_base_id == knowledge_base.id
                    )
                )
                or 0
            )
            + 1
        )
        retrieval_revision_id = (
            knowledge_base.active_retrieval_revision_id or source.retrieval_revision_id
        )
        repair = IndexGenerationModel(
            id=uuid4(),
            knowledge_base_id=knowledge_base.id,
            generation_number=generation_number,
            build_config_revision_id=source.build_config_revision_id,
            retrieval_revision_id=retrieval_revision_id,
            status="queued",
            collection_name=f"kb_{knowledge_base.id.hex}_gen_{generation_number}",
            keyword_namespace=uuid4(),
            source_count=len(source_items),
            operation_id=operation.id,
            validation_report={
                "repairSourceGenerationId": str(source.id),
                "retryPreparedAt": now.isoformat(),
            },
            created_at=now,
        )
        session.add(repair)
        session.flush()
        session.add_all(
            [
                IndexGenerationItemModel(
                    id=uuid4(),
                    index_generation_id=repair.id,
                    parsed_source_version_id=item.parsed_source_version_id,
                    status="queued",
                    source_copy_from_item_id=item.id if item.status == "succeeded" else None,
                    stage_progress={"copy": "queued"}
                    if item.status == "succeeded"
                    else {"retry": "queued"},
                    created_at=now,
                )
                for item in source_items
            ]
        )
        operation.target_id = repair.id
        knowledge_base.pending_build_config_revision_id = repair.build_config_revision_id
        knowledge_base.pending_retrieval_revision_id = repair.retrieval_revision_id
        knowledge_base.latest_build_operation_id = operation.id
        knowledge_base.revision += 1
        knowledge_base.updated_at = now
        return repair

    @staticmethod
    def _items(session: Session, generation_id: UUID) -> tuple[IndexGenerationItemModel, ...]:
        return tuple(
            session.scalars(
                select(IndexGenerationItemModel)
                .where(IndexGenerationItemModel.index_generation_id == generation_id)
                .order_by(IndexGenerationItemModel.created_at, IndexGenerationItemModel.id)
            ).all()
        )

    @staticmethod
    def _guard_no_running_generation(session: Session, source: IndexGenerationModel) -> None:
        running = session.scalar(
            select(IndexGenerationModel.id).where(
                IndexGenerationModel.knowledge_base_id == source.knowledge_base_id,
                IndexGenerationModel.id != source.id,
                IndexGenerationModel.status.in_(("queued", "building", "validating")),
            )
        )
        if running is not None:
            raise NonRetryableTaskError("GENERATION_RETRY_CONFLICT")
