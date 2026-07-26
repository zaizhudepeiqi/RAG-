from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.modules.capabilities.registry import CapabilityRegistry
from app.modules.knowledge_bases.domain import (
    BuildConfig,
    BuildConfigRevision,
    CreatedKnowledgeBase,
    GenerationDetails,
    GenerationRecord,
    InitialKnowledgeBaseGraph,
    KnowledgeBase,
    KnowledgeBaseDetails,
    ModelSelectionSnapshot,
    NewGenerationGraph,
    RetrievalConfig,
    RetrievalConfigRevision,
    SavedBuildConfig,
    SelectedKnowledgeModel,
    SourceSelectionSnapshot,
    canonical_config_hash,
    derive_allowed_actions,
    derive_display_status,
)
from app.modules.knowledge_bases.errors import KnowledgeBaseConfigError
from app.modules.knowledge_bases.repository import (
    KnowledgeBaseListQuery,
    KnowledgeBasePage,
    KnowledgeBaseRepository,
)
from app.modules.knowledge_bases.validation import validate_configs
from app.modules.models.domain import ModelType, SelectableModel
from app.modules.models.service import ModelSelectionService
from app.modules.tasks.domain import Operation
from app.modules.tasks.idempotency import AdminIdempotencyService
from app.modules.tasks.service import TaskService


class KnowledgeBaseNotFoundError(LookupError):
    pass


class KnowledgeBaseNameConflictError(ValueError):
    pass


class KnowledgeBaseRevisionConflictError(ValueError):
    pass


class KnowledgeBaseDeleteBlockedError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class KnowledgeBaseConfigLockedError(ValueError):
    pass


class KnowledgeBaseGenerationConflictError(ValueError):
    pass


class KnowledgeBaseGenerationNotFoundError(LookupError):
    pass


class KnowledgeModelSelector(Protocol):
    def require(
        self,
        session: Session,
        model_id: UUID,
        expected_type: str,
    ) -> SelectedKnowledgeModel: ...


class RegistryKnowledgeModelSelector:
    def __init__(self, selection: ModelSelectionService) -> None:
        self._selection = selection

    def require(
        self,
        session: Session,
        model_id: UUID,
        expected_type: str,
    ) -> SelectedKnowledgeModel:
        selected = self._selection.require_selectable(
            session,
            model_id,
            ModelType(expected_type),
        )
        return _selected_model(selected)


class KnowledgeBaseService:
    def __init__(
        self,
        repository: KnowledgeBaseRepository,
        model_selector: KnowledgeModelSelector,
        capabilities: CapabilityRegistry,
        tasks: TaskService,
        *,
        operation_retention_days: int,
        idempotency: AdminIdempotencyService | None = None,
    ) -> None:
        self._repository = repository
        self._model_selector = model_selector
        self._capabilities = capabilities
        self._tasks = tasks
        self._operation_retention_days = operation_retention_days
        self._idempotency = idempotency

    def create(
        self,
        session: Session,
        *,
        name: str,
        description: str | None,
        source_ids: tuple[UUID, ...],
        build_config: BuildConfig,
        retrieval_config: RetrievalConfig,
        idempotency_key: str,
        administrator_id: UUID | None = None,
        now: datetime | None = None,
    ) -> CreatedKnowledgeBase:
        now = now or datetime.now(UTC)
        normalized_name = name.strip()
        if not normalized_name or len(normalized_name) > 100:
            raise KnowledgeBaseConfigError(
                "BUILD_CONFIG_INVALID",
                {"name": ["知识库名称长度必须在 1 到 100 个字符之间"]},
            )
        normalized_description = (
            description.strip() if description and description.strip() else None
        )
        request_body: dict[str, object] = {
            "name": normalized_name,
            "description": normalized_description,
            "parsedSourceVersionIds": [str(source_id) for source_id in source_ids],
            "buildConfigHash": canonical_config_hash(build_config),
            "retrievalConfigHash": canonical_config_hash(retrieval_config),
        }
        if self._idempotency is not None and administrator_id is not None:
            existing = self._idempotency.find(
                session,
                administrator_id=administrator_id,
                endpoint_code="knowledge_bases.create",
                idempotency_key=idempotency_key,
                request_body=request_body,
            )
            if existing is not None and existing.operation_id is not None:
                operation = self._tasks.get(session, existing.operation_id)
                knowledge_base = self.get(session, operation.target_id)
                generation_id = self._repository.find_generation_id_by_operation(
                    session, operation.id
                )
                if generation_id is None:
                    raise RuntimeError("idempotent knowledge base operation is incomplete")
                return CreatedKnowledgeBase(knowledge_base, generation_id, operation.id)
        if self._repository.find_by_name(session, normalized_name) is not None:
            raise KnowledgeBaseNameConflictError
        sources = self._repository.load_source_snapshots(session, source_ids)
        loaded_source_ids = {source.parsed_source_version_id for source in sources}
        missing_source_ids = tuple(
            str(source_id) for source_id in source_ids if source_id not in loaded_source_ids
        )
        if missing_source_ids:
            raise KnowledgeBaseConfigError(
                "BUILD_CONFIG_INVALID",
                {
                    "parsedSourceVersionIds": [
                        "包含不存在的解析版本: " + ", ".join(missing_source_ids)
                    ]
                },
            )
        embedding = self._model_selector.require(
            session,
            build_config.embedding_model_id,
            "embedding",
        )
        referenced_models = self._load_retrieval_models(session, retrieval_config)
        validate_configs(
            build_config,
            retrieval_config,
            sources,
            embedding.selection,
            {model.selection.id: model.selection for model in referenced_models.values()},
            self._capabilities,
        )
        knowledge_base_id = uuid4()
        build_revision_id = uuid4()
        retrieval_revision_id = uuid4()
        generation_id = uuid4()
        knowledge_base = KnowledgeBase(
            id=knowledge_base_id,
            name=normalized_name,
            description=normalized_description,
            enabled=True,
            active_generation_id=None,
            active_retrieval_revision_id=None,
            pending_build_config_revision_id=build_revision_id,
            pending_retrieval_revision_id=retrieval_revision_id,
            latest_build_operation_id=None,
            revision=1,
            created_at=now,
            updated_at=now,
            deleted_at=None,
        )
        graph = InitialKnowledgeBaseGraph(
            knowledge_base=knowledge_base,
            build_config_revision_id=build_revision_id,
            build_config_hash=canonical_config_hash(
                {"sources": source_ids, "config": build_config}
            ),
            build_config=build_config,
            embedding_model_snapshot=embedding.immutable_snapshot,
            retrieval_revision_id=retrieval_revision_id,
            retrieval_config_hash=canonical_config_hash(retrieval_config),
            retrieval_config=retrieval_config,
            generation_id=generation_id,
            collection_name=f"kb_{knowledge_base_id.hex}_gen_1",
            keyword_namespace=uuid4(),
            source_ids=source_ids,
            item_ids=tuple(uuid4() for _ in source_ids),
        )
        self._repository.add_initial_graph(session, graph)
        operation = self._tasks.create_operation(
            session,
            task_type="knowledge_base_build",
            target_type="knowledge_base",
            target_id=knowledge_base_id,
            target_revision=1,
            business_key=(
                f"admin:{administrator_id}:knowledge_bases.create:{idempotency_key}"
                if administrator_id is not None
                else f"knowledge-base.create:{idempotency_key}"
            ),
            event_type="knowledge_base.generation.requested",
            payload={
                "knowledgeBaseId": str(knowledge_base_id),
                "generationId": str(generation_id),
                "expectedRevision": 1,
            },
            now=now,
            expires_at=now + timedelta(days=self._operation_retention_days),
        )
        self._repository.attach_operation(
            session,
            knowledge_base_id=knowledge_base_id,
            generation_id=generation_id,
            operation_id=operation.id,
        )
        if self._idempotency is not None and administrator_id is not None:
            self._idempotency.reserve(
                session,
                administrator_id=administrator_id,
                endpoint_code="knowledge_bases.create",
                idempotency_key=idempotency_key,
                request_body=request_body,
                operation_id=operation.id,
                now=now,
            )
        knowledge_base.latest_build_operation_id = operation.id
        return CreatedKnowledgeBase(knowledge_base, generation_id, operation.id)

    def get(self, session: Session, knowledge_base_id: UUID) -> KnowledgeBase:
        result = self._repository.get(session, knowledge_base_id)
        if result is None:
            raise KnowledgeBaseNotFoundError
        return result

    def list(self, session: Session, query: KnowledgeBaseListQuery) -> KnowledgeBasePage:
        return self._repository.list(session, query)

    def details(self, session: Session, knowledge_base: KnowledgeBase) -> KnowledgeBaseDetails:
        runtime = self._repository.runtime_snapshot(session, knowledge_base)
        has_pending_build_config = knowledge_base.pending_build_config_revision_id is not None
        return KnowledgeBaseDetails(
            knowledge_base=knowledge_base,
            runtime=runtime,
            derived_display_status=derive_display_status(
                knowledge_base.enabled,
                runtime.active_completeness,
                runtime.latest_generation_status,
                has_pending_build_config,
            ),
            allowed_actions=derive_allowed_actions(
                enabled=knowledge_base.enabled,
                active_completeness=runtime.active_completeness,
                latest_build_status=runtime.latest_generation_status,
                has_pending_build_config=has_pending_build_config,
                bot_reference_count=runtime.bot_reference_count,
            ),
        )

    def get_details(self, session: Session, knowledge_base_id: UUID) -> KnowledgeBaseDetails:
        return self.details(session, self.get(session, knowledge_base_id))

    def update_metadata(
        self,
        session: Session,
        knowledge_base_id: UUID,
        *,
        expected_revision: int,
        name: str,
        description: str | None,
        now: datetime | None = None,
    ) -> KnowledgeBase:
        knowledge_base = self._require_for_update(session, knowledge_base_id, expected_revision)
        normalized_name = name.strip()
        if not normalized_name or len(normalized_name) > 100:
            raise KnowledgeBaseConfigError(
                "BUILD_CONFIG_INVALID",
                {"name": ["知识库名称长度必须在 1 到 100 个字符之间"]},
            )
        existing = self._repository.find_by_name(session, normalized_name)
        if existing is not None and existing.id != knowledge_base.id:
            raise KnowledgeBaseNameConflictError
        knowledge_base.name = normalized_name
        knowledge_base.description = (
            description.strip() if description and description.strip() else None
        )
        knowledge_base.revision += 1
        knowledge_base.updated_at = now or datetime.now(UTC)
        self._repository.save(session, knowledge_base)
        return knowledge_base

    def set_enabled(
        self,
        session: Session,
        knowledge_base_id: UUID,
        *,
        expected_revision: int,
        enabled: bool,
        now: datetime | None = None,
    ) -> KnowledgeBase:
        knowledge_base = self._require_for_update(session, knowledge_base_id, expected_revision)
        if knowledge_base.enabled == enabled:
            return knowledge_base
        knowledge_base.enabled = enabled
        knowledge_base.revision += 1
        knowledge_base.updated_at = now or datetime.now(UTC)
        self._repository.save(session, knowledge_base)
        return knowledge_base

    def request_delete(
        self,
        session: Session,
        knowledge_base_id: UUID,
        *,
        expected_revision: int,
        administrator_id: UUID,
        idempotency_key: str,
        now: datetime | None = None,
    ) -> Operation:
        now = now or datetime.now(UTC)
        request_body: dict[str, object] = {
            "knowledgeBaseId": str(knowledge_base_id),
            "expectedRevision": expected_revision,
        }
        if self._idempotency is not None:
            existing = self._idempotency.find(
                session,
                administrator_id=administrator_id,
                endpoint_code="knowledge_bases.delete",
                idempotency_key=idempotency_key,
                request_body=request_body,
            )
            if existing is not None and existing.operation_id is not None:
                return self._tasks.get(session, existing.operation_id)
        knowledge_base = self._require_for_update(session, knowledge_base_id, expected_revision)
        runtime = self._repository.runtime_snapshot(session, knowledge_base)
        if runtime.bot_reference_count > 0:
            raise KnowledgeBaseDeleteBlockedError("BOT_REFERENCES_EXIST")
        if runtime.latest_generation_status in {"queued", "building", "validating"}:
            raise KnowledgeBaseDeleteBlockedError("BUILD_RUNNING")
        operation = self._tasks.create_operation(
            session,
            task_type="knowledge_base_cleanup",
            target_type="knowledge_base",
            target_id=knowledge_base.id,
            target_revision=knowledge_base.revision,
            business_key=(f"admin:{administrator_id}:knowledge_bases.delete:{idempotency_key}"),
            event_type="knowledge_base.cleanup.requested",
            payload={
                "knowledgeBaseId": str(knowledge_base.id),
                "expectedRevision": knowledge_base.revision,
            },
            now=now,
            expires_at=now + timedelta(days=self._operation_retention_days),
        )
        if self._idempotency is not None:
            self._idempotency.reserve(
                session,
                administrator_id=administrator_id,
                endpoint_code="knowledge_bases.delete",
                idempotency_key=idempotency_key,
                request_body=request_body,
                operation_id=operation.id,
                now=now,
            )
        knowledge_base.enabled = False
        knowledge_base.deleted_at = now
        knowledge_base.updated_at = now
        knowledge_base.revision += 1
        self._repository.save(session, knowledge_base)
        return operation

    def get_build_configs(
        self, session: Session, knowledge_base_id: UUID
    ) -> tuple[BuildConfigRevision | None, BuildConfigRevision | None]:
        knowledge_base = self.get(session, knowledge_base_id)
        runtime = self._repository.runtime_snapshot(session, knowledge_base)
        active_id = (
            runtime.selected_build_config_revision_id
            if knowledge_base.active_generation_id is not None
            else None
        )
        active = (
            self._repository.get_build_config_revision(session, active_id)
            if active_id is not None
            else None
        )
        pending = (
            self._repository.get_build_config_revision(
                session, knowledge_base.pending_build_config_revision_id
            )
            if knowledge_base.pending_build_config_revision_id is not None
            else None
        )
        return active, pending

    def save_pending_build_config(
        self,
        session: Session,
        knowledge_base_id: UUID,
        *,
        expected_revision: int,
        source_ids: tuple[UUID, ...],
        config: BuildConfig,
        now: datetime | None = None,
    ) -> SavedBuildConfig:
        now = now or datetime.now(UTC)
        knowledge_base = self._require_for_update(session, knowledge_base_id, expected_revision)
        sources = self._validated_sources(session, source_ids)
        embedding = self._model_selector.require(session, config.embedding_model_id, "embedding")
        retrieval = self._current_retrieval_revision(session, knowledge_base)
        referenced_models = self._load_retrieval_models(session, retrieval.config)
        warnings = validate_configs(
            config,
            retrieval.config,
            sources,
            embedding.selection,
            {model.selection.id: model.selection for model in referenced_models.values()},
            self._capabilities,
        )
        config_hash = canonical_config_hash({"sources": source_ids, "config": config})
        revision = self._repository.find_build_config_revision_by_hash(
            session, knowledge_base.id, config_hash
        )
        if revision is None:
            revision = BuildConfigRevision(
                id=uuid4(),
                knowledge_base_id=knowledge_base.id,
                revision_number=self._repository.next_build_revision_number(
                    session, knowledge_base.id
                ),
                config_hash=config_hash,
                config=config,
                embedding_model_snapshot=embedding.immutable_snapshot,
                source_ids=source_ids,
                created_at=now,
            )
            self._repository.add_build_config_revision(session, revision)
        if knowledge_base.pending_build_config_revision_id != revision.id:
            knowledge_base.pending_build_config_revision_id = revision.id
            knowledge_base.revision += 1
            knowledge_base.updated_at = now
            self._repository.save(session, knowledge_base)
        return SavedBuildConfig(revision, warnings)

    def discard_pending_build_config(
        self,
        session: Session,
        knowledge_base_id: UUID,
        *,
        expected_revision: int,
        now: datetime | None = None,
    ) -> KnowledgeBase:
        knowledge_base = self._require_for_update(session, knowledge_base_id, expected_revision)
        runtime = self._repository.runtime_snapshot(session, knowledge_base)
        if runtime.latest_generation_status in {"queued", "building", "validating"}:
            raise KnowledgeBaseConfigLockedError
        if knowledge_base.pending_build_config_revision_id is None:
            return knowledge_base
        knowledge_base.pending_build_config_revision_id = None
        knowledge_base.pending_retrieval_revision_id = None
        knowledge_base.revision += 1
        knowledge_base.updated_at = now or datetime.now(UTC)
        self._repository.save(session, knowledge_base)
        return knowledge_base

    def get_retrieval_configs(
        self, session: Session, knowledge_base_id: UUID
    ) -> tuple[RetrievalConfigRevision | None, RetrievalConfigRevision | None]:
        knowledge_base = self.get(session, knowledge_base_id)
        active = (
            self._repository.get_retrieval_config_revision(
                session, knowledge_base.active_retrieval_revision_id
            )
            if knowledge_base.active_retrieval_revision_id is not None
            else None
        )
        pending = (
            self._repository.get_retrieval_config_revision(
                session, knowledge_base.pending_retrieval_revision_id
            )
            if knowledge_base.pending_retrieval_revision_id is not None
            else None
        )
        return active, pending

    def save_retrieval_config(
        self,
        session: Session,
        knowledge_base_id: UUID,
        *,
        expected_revision: int,
        config: RetrievalConfig,
        activation_mode: str,
        now: datetime | None = None,
    ) -> tuple[RetrievalConfigRevision, Literal["active", "pending_generation"]]:
        now = now or datetime.now(UTC)
        knowledge_base = self._require_for_update(session, knowledge_base_id, expected_revision)
        runtime = self._repository.runtime_snapshot(session, knowledge_base)
        build_revision_id = runtime.selected_build_config_revision_id
        if build_revision_id is None:
            raise KnowledgeBaseConfigError(
                "BUILD_CONFIG_INVALID", {"buildConfig": ["知识库缺少构建配置"]}
            )
        build = self._repository.get_build_config_revision(session, build_revision_id)
        if build is None:
            raise RuntimeError("selected build config revision is missing")
        sources = self._validated_sources(session, build.source_ids)
        embedding = self._model_selector.require(
            session, build.config.embedding_model_id, "embedding"
        )
        referenced_models = self._load_retrieval_models(session, config)
        validate_configs(
            build.config,
            config,
            sources,
            embedding.selection,
            {model.selection.id: model.selection for model in referenced_models.values()},
            self._capabilities,
        )
        config_hash = canonical_config_hash(config)
        revision = self._repository.find_retrieval_config_revision_by_hash(
            session, knowledge_base.id, config_hash
        )
        if revision is None:
            revision = RetrievalConfigRevision(
                id=uuid4(),
                knowledge_base_id=knowledge_base.id,
                revision_number=self._repository.next_retrieval_revision_number(
                    session, knowledge_base.id
                ),
                config_hash=config_hash,
                config=config,
                created_at=now,
            )
            self._repository.add_retrieval_config_revision(session, revision)
        has_pending_build = knowledge_base.pending_build_config_revision_id is not None
        activation_status: Literal["active", "pending_generation"]
        if has_pending_build or activation_mode == "with_pending_generation":
            knowledge_base.pending_retrieval_revision_id = revision.id
            activation_status = "pending_generation"
        else:
            knowledge_base.active_retrieval_revision_id = revision.id
            knowledge_base.pending_retrieval_revision_id = None
            activation_status = "active"
        knowledge_base.revision += 1
        knowledge_base.updated_at = now
        self._repository.save(session, knowledge_base)
        return revision, activation_status

    def create_generation(
        self,
        session: Session,
        knowledge_base_id: UUID,
        *,
        expected_revision: int,
        pending_build_config_revision_id: UUID,
        pending_retrieval_revision_id: UUID | None,
        administrator_id: UUID,
        idempotency_key: str,
        now: datetime | None = None,
    ) -> tuple[GenerationRecord, Operation]:
        now = now or datetime.now(UTC)
        request_body: dict[str, object] = {
            "knowledgeBaseId": str(knowledge_base_id),
            "expectedRevision": expected_revision,
            "pendingBuildConfigRevisionId": str(pending_build_config_revision_id),
            "pendingRetrievalRevisionId": (
                str(pending_retrieval_revision_id)
                if pending_retrieval_revision_id is not None
                else None
            ),
        }
        if self._idempotency is not None:
            existing = self._idempotency.find(
                session,
                administrator_id=administrator_id,
                endpoint_code="knowledge_bases.generations.create",
                idempotency_key=idempotency_key,
                request_body=request_body,
            )
            if existing is not None and existing.operation_id is not None:
                operation = self._tasks.get(session, existing.operation_id)
                generation_id = self._repository.find_generation_id_by_operation(
                    session, operation.id
                )
                if generation_id is None:
                    raise RuntimeError("idempotent generation operation is incomplete")
                details = self._repository.get_generation(session, knowledge_base_id, generation_id)
                if details is None:
                    raise RuntimeError("idempotent generation is missing")
                return details.generation, operation
        knowledge_base = self._require_for_update(session, knowledge_base_id, expected_revision)
        runtime = self._repository.runtime_snapshot(session, knowledge_base)
        if runtime.latest_generation_status in {"queued", "building", "validating"}:
            raise KnowledgeBaseGenerationConflictError
        if knowledge_base.pending_build_config_revision_id != pending_build_config_revision_id:
            raise KnowledgeBaseRevisionConflictError
        retrieval_revision_id = (
            pending_retrieval_revision_id
            or knowledge_base.pending_retrieval_revision_id
            or knowledge_base.active_retrieval_revision_id
        )
        if retrieval_revision_id is None or (
            pending_retrieval_revision_id is not None
            and knowledge_base.pending_retrieval_revision_id != pending_retrieval_revision_id
        ):
            raise KnowledgeBaseRevisionConflictError
        build = self._repository.get_build_config_revision(
            session, pending_build_config_revision_id
        )
        if build is None or build.knowledge_base_id != knowledge_base.id:
            raise KnowledgeBaseRevisionConflictError
        generation_number = runtime.generation_count + 1
        generation_id = uuid4()
        graph = NewGenerationGraph(
            generation_id=generation_id,
            knowledge_base_id=knowledge_base.id,
            generation_number=generation_number,
            build_config_revision_id=build.id,
            retrieval_revision_id=retrieval_revision_id,
            collection_name=f"kb_{knowledge_base.id.hex}_gen_{generation_number}",
            keyword_namespace=uuid4(),
            source_ids=build.source_ids,
            item_ids=tuple(uuid4() for _ in build.source_ids),
            created_at=now,
        )
        self._repository.add_generation(session, graph)
        operation = self._tasks.create_operation(
            session,
            task_type="knowledge_base_build",
            target_type="knowledge_base",
            target_id=knowledge_base.id,
            target_revision=knowledge_base.revision,
            business_key=(
                f"admin:{administrator_id}:knowledge_bases.generations.create:{idempotency_key}"
            ),
            event_type="knowledge_base.generation.requested",
            payload={
                "knowledgeBaseId": str(knowledge_base.id),
                "generationId": str(generation_id),
                "expectedRevision": knowledge_base.revision,
            },
            now=now,
            expires_at=now + timedelta(days=self._operation_retention_days),
        )
        self._repository.attach_generation_operation(session, generation_id, operation.id)
        if self._idempotency is not None:
            self._idempotency.reserve(
                session,
                administrator_id=administrator_id,
                endpoint_code="knowledge_bases.generations.create",
                idempotency_key=idempotency_key,
                request_body=request_body,
                operation_id=operation.id,
                now=now,
            )
        knowledge_base.latest_build_operation_id = operation.id
        knowledge_base.revision += 1
        knowledge_base.updated_at = now
        self._repository.save(session, knowledge_base)
        details = self._repository.get_generation(session, knowledge_base.id, generation_id)
        if details is None:
            raise RuntimeError("new generation is missing")
        return details.generation, operation

    def list_generations(
        self, session: Session, knowledge_base_id: UUID
    ) -> Sequence[GenerationRecord]:
        self.get(session, knowledge_base_id)
        return self._repository.list_generations(session, knowledge_base_id)

    def get_generation(
        self, session: Session, knowledge_base_id: UUID, generation_id: UUID
    ) -> GenerationDetails:
        self.get(session, knowledge_base_id)
        details = self._repository.get_generation(session, knowledge_base_id, generation_id)
        if details is None:
            raise KnowledgeBaseGenerationNotFoundError
        return details

    def request_generation_retry(
        self,
        session: Session,
        knowledge_base_id: UUID,
        generation_id: UUID,
        *,
        administrator_id: UUID,
        idempotency_key: str,
        now: datetime | None = None,
    ) -> Operation:
        now = now or datetime.now(UTC)
        request_body: dict[str, object] = {
            "knowledgeBaseId": str(knowledge_base_id),
            "generationId": str(generation_id),
        }
        if self._idempotency is not None:
            existing = self._idempotency.find(
                session,
                administrator_id=administrator_id,
                endpoint_code="knowledge_bases.generations.retry_failed",
                idempotency_key=idempotency_key,
                request_body=request_body,
            )
            if existing is not None and existing.operation_id is not None:
                return self._tasks.get(session, existing.operation_id)
        knowledge_base = self.get(session, knowledge_base_id)
        generation = self.get_generation(session, knowledge_base_id, generation_id).generation
        if generation.status not in {"failed", "partial_failed", "partial_ready"}:
            raise KnowledgeBaseGenerationConflictError
        operation = self._tasks.create_operation(
            session,
            task_type="knowledge_base_build_retry",
            target_type="index_generation",
            target_id=generation.id,
            target_revision=knowledge_base.revision,
            business_key=(
                f"admin:{administrator_id}:knowledge_bases.generations.retry_failed:"
                f"{idempotency_key}"
            ),
            event_type="knowledge_base.generation.retry_failed_requested",
            payload={
                "knowledgeBaseId": str(knowledge_base.id),
                "generationId": str(generation.id),
            },
            now=now,
            expires_at=now + timedelta(days=self._operation_retention_days),
        )
        if self._idempotency is not None:
            self._idempotency.reserve(
                session,
                administrator_id=administrator_id,
                endpoint_code="knowledge_bases.generations.retry_failed",
                idempotency_key=idempotency_key,
                request_body=request_body,
                operation_id=operation.id,
                now=now,
            )
        return operation

    def discard_generation(
        self,
        session: Session,
        knowledge_base_id: UUID,
        generation_id: UUID,
        *,
        expected_revision: int,
        now: datetime | None = None,
    ) -> GenerationRecord:
        knowledge_base = self._require_for_update(session, knowledge_base_id, expected_revision)
        generation = self.get_generation(session, knowledge_base_id, generation_id).generation
        if (
            generation.id == knowledge_base.active_generation_id
            or generation.is_frozen
            or generation.status not in {"failed", "partial_failed"}
        ):
            raise KnowledgeBaseGenerationConflictError
        discarded = self._repository.set_generation_status(session, generation.id, "discarded")
        knowledge_base.revision += 1
        knowledge_base.updated_at = now or datetime.now(UTC)
        self._repository.save(session, knowledge_base)
        return discarded

    def _current_retrieval_revision(
        self, session: Session, knowledge_base: KnowledgeBase
    ) -> RetrievalConfigRevision:
        revision_id = (
            knowledge_base.pending_retrieval_revision_id
            or knowledge_base.active_retrieval_revision_id
        )
        if revision_id is None:
            raise KnowledgeBaseConfigError(
                "RETRIEVAL_CONFIG_INVALID", {"retrievalConfig": ["知识库缺少检索配置"]}
            )
        revision = self._repository.get_retrieval_config_revision(session, revision_id)
        if revision is None:
            raise RuntimeError("selected retrieval config revision is missing")
        return revision

    def _validated_sources(
        self, session: Session, source_ids: tuple[UUID, ...]
    ) -> tuple[SourceSelectionSnapshot, ...]:
        sources = self._repository.load_source_snapshots(session, source_ids)
        loaded_ids = {source.parsed_source_version_id for source in sources}
        missing = [str(source_id) for source_id in source_ids if source_id not in loaded_ids]
        if missing:
            raise KnowledgeBaseConfigError(
                "BUILD_CONFIG_INVALID",
                {"parsedSourceVersionIds": ["包含不存在的解析版本: " + ", ".join(missing)]},
            )
        return sources

    def _require_for_update(
        self,
        session: Session,
        knowledge_base_id: UUID,
        expected_revision: int,
    ) -> KnowledgeBase:
        knowledge_base = self._repository.get(session, knowledge_base_id, for_update=True)
        if knowledge_base is None:
            raise KnowledgeBaseNotFoundError
        if knowledge_base.revision != expected_revision:
            raise KnowledgeBaseRevisionConflictError
        return knowledge_base

    def _load_retrieval_models(
        self,
        session: Session,
        config: RetrievalConfig,
    ) -> dict[UUID, SelectedKnowledgeModel]:
        selections: dict[UUID, SelectedKnowledgeModel] = {}
        if config.query_rewrite.code != "off" and config.query_rewrite.model_id is not None:
            model_id = config.query_rewrite.model_id
            selections[model_id] = self._model_selector.require(session, model_id, "llm")
        if config.rerank.code != "off" and config.rerank.model_id is not None:
            model_id = config.rerank.model_id
            expected_type = "rerank" if config.rerank.code == "rerank_model" else "llm"
            selections[model_id] = self._model_selector.require(session, model_id, expected_type)
        return selections


def _selected_model(selected: SelectableModel) -> SelectedKnowledgeModel:
    model = selected.model
    provider = selected.provider
    return SelectedKnowledgeModel(
        selection=ModelSelectionSnapshot(
            id=model.id,
            model_type=model.model_type.value,
            enabled=model.enabled,
            verification_status=model.verification_status.value,
            embedding_dimension=model.embedding_dimension,
        ),
        immutable_snapshot={
            "modelId": str(model.id),
            "modelName": model.model_name,
            "displayName": model.display_name,
            "modelType": model.model_type.value,
            "embeddingDimension": model.embedding_dimension,
            "capabilityVersion": model.capability_version,
            "modelRevision": model.revision,
            "providerId": str(provider.id),
            "providerType": provider.provider_type,
            "providerRevision": provider.revision,
            "credentialRevision": provider.credential_revision,
        },
    )
