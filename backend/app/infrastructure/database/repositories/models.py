from __future__ import annotations

import ipaddress
from collections.abc import Mapping, Sequence
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Select, asc, desc, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from app.infrastructure.database.models.auth import AuditLogModel
from app.infrastructure.database.models.models import (
    ModelConfigModel,
    ModelDiscoveredCandidateModel,
    ModelProviderModel,
    ModelVerificationModel,
)
from app.infrastructure.database.models.tasks import OperationModel
from app.infrastructure.database.session import transaction
from app.modules.models.adapters import DiscoveredModel
from app.modules.models.domain import (
    DiscoveredModelCandidate,
    ModelConfig,
    ModelProvider,
    ModelReference,
    ModelType,
    ModelVerificationSnapshot,
    VerificationStatus,
)
from app.modules.models.repository import (
    ModelConfigListQuery,
    ModelConfigPage,
    ModelProviderListQuery,
    ModelProviderPage,
)
from app.modules.models.tasks import (
    MODEL_PROVIDER_DISCOVERY_TASK,
    ProviderTaskSnapshot,
)
from app.modules.tasks.domain import OperationStatus


class SqlAlchemyModelProviderRepository:
    def add(self, session: Session, provider: ModelProvider) -> None:
        session.add(self._to_model(provider))

    def get(
        self,
        session: Session,
        provider_id: UUID,
        *,
        for_update: bool = False,
    ) -> ModelProvider | None:
        statement = select(ModelProviderModel).where(
            ModelProviderModel.id == provider_id,
            ModelProviderModel.deleted_at.is_(None),
        )
        if for_update:
            statement = statement.with_for_update()
        model = session.scalar(statement)
        if model is None:
            return None
        return self._to_domain(model, self._model_count(session, model.id))

    def find_by_display_name(
        self,
        session: Session,
        display_name: str,
    ) -> ModelProvider | None:
        model = session.scalar(
            select(ModelProviderModel).where(
                func.lower(ModelProviderModel.display_name) == display_name.casefold(),
                ModelProviderModel.deleted_at.is_(None),
            )
        )
        if model is None:
            return None
        return self._to_domain(model, self._model_count(session, model.id))

    def list(
        self,
        session: Session,
        query: ModelProviderListQuery,
    ) -> ModelProviderPage:
        conditions: list[ColumnElement[bool]] = [ModelProviderModel.deleted_at.is_(None)]
        if query.search:
            conditions.append(ModelProviderModel.display_name.ilike(f"%{query.search.strip()}%"))
        if query.enabled is not None:
            conditions.append(ModelProviderModel.enabled == query.enabled)
        ordering = {
            "display_name": asc(func.lower(ModelProviderModel.display_name)),
            "-display_name": desc(func.lower(ModelProviderModel.display_name)),
            "created_at": asc(ModelProviderModel.created_at),
            "-created_at": desc(ModelProviderModel.created_at),
        }
        model_count = (
            select(func.count())
            .select_from(ModelConfigModel)
            .where(
                ModelConfigModel.provider_id == ModelProviderModel.id,
                ModelConfigModel.deleted_at.is_(None),
            )
            .correlate(ModelProviderModel)
            .scalar_subquery()
        )
        statement: Select[tuple[ModelProviderModel, int]] = (
            select(ModelProviderModel, model_count)
            .where(*conditions)
            .order_by(ordering[query.sort], ModelProviderModel.id)
            .offset((query.page - 1) * query.page_size)
            .limit(query.page_size)
        )
        rows = session.execute(statement).all()
        total = (
            session.scalar(select(func.count()).select_from(ModelProviderModel).where(*conditions))
            or 0
        )
        return ModelProviderPage(
            items=[self._to_domain(model, count) for model, count in rows],
            total=total,
            page=query.page,
            page_size=query.page_size,
        )

    def save(self, session: Session, provider: ModelProvider) -> None:
        model = session.get(ModelProviderModel, provider.id)
        if model is None:
            raise LookupError("model provider no longer exists")
        model.display_name = provider.display_name
        model.credential_ciphertext = provider.credential_ciphertext
        model.credential_nonce = provider.credential_nonce
        model.credential_key_version = provider.credential_key_version
        model.credential_prefix = provider.credential_prefix
        model.credential_revision = provider.credential_revision
        model.enabled = provider.enabled
        model.revision = provider.revision
        model.updated_at = provider.updated_at
        model.deleted_at = provider.deleted_at

    def has_models(self, session: Session, provider_id: UUID) -> bool:
        return self._model_count(session, provider_id) > 0

    def mark_models_stale(self, session: Session, provider_id: UUID) -> None:
        session.execute(
            update(ModelConfigModel)
            .where(
                ModelConfigModel.provider_id == provider_id,
                ModelConfigModel.deleted_at.is_(None),
            )
            .values(verification_status=VerificationStatus.STALE.value)
        )

    def list_discovered_candidates(
        self,
        session: Session,
        provider_id: UUID,
        *,
        model_type: ModelType | None,
        provider_status: str | None,
    ) -> Sequence[DiscoveredModelCandidate]:
        latest_operation_id = session.scalar(
            select(OperationModel.id)
            .where(
                OperationModel.task_type == MODEL_PROVIDER_DISCOVERY_TASK,
                OperationModel.target_type == "model_provider",
                OperationModel.target_id == provider_id,
                OperationModel.status == OperationStatus.SUCCEEDED.value,
            )
            .order_by(OperationModel.finished_at.desc(), OperationModel.created_at.desc())
            .limit(1)
        )
        if latest_operation_id is None:
            return []
        conditions = [
            ModelDiscoveredCandidateModel.provider_id == provider_id,
            ModelDiscoveredCandidateModel.discovery_operation_id == latest_operation_id,
        ]
        if model_type is not None:
            conditions.append(
                ModelDiscoveredCandidateModel.suggested_types.contains([model_type.value])
            )
        if provider_status is not None:
            conditions.append(ModelDiscoveredCandidateModel.provider_status == provider_status)
        models = session.scalars(
            select(ModelDiscoveredCandidateModel)
            .where(*conditions)
            .order_by(ModelDiscoveredCandidateModel.model_name)
        ).all()
        candidates = []
        for model in models:
            configured_ids = tuple(
                session.scalars(
                    select(ModelConfigModel.id)
                    .where(
                        ModelConfigModel.provider_id == provider_id,
                        ModelConfigModel.model_name == model.model_name,
                        ModelConfigModel.deleted_at.is_(None),
                    )
                    .order_by(ModelConfigModel.id)
                ).all()
            )
            candidates.append(
                DiscoveredModelCandidate(
                    model_name=model.model_name,
                    suggested_types=tuple(ModelType(item) for item in model.suggested_types),
                    provider_status=model.provider_status,
                    metadata_summary=dict(model.raw_metadata_summary),
                    configured_model_ids=configured_ids,
                )
            )
        return candidates

    @staticmethod
    def _model_count(session: Session, provider_id: UUID) -> int:
        return (
            session.scalar(
                select(func.count())
                .select_from(ModelConfigModel)
                .where(
                    ModelConfigModel.provider_id == provider_id,
                    ModelConfigModel.deleted_at.is_(None),
                )
            )
            or 0
        )

    @staticmethod
    def _to_model(provider: ModelProvider) -> ModelProviderModel:
        return ModelProviderModel(
            id=provider.id,
            provider_type=provider.provider_type,
            display_name=provider.display_name,
            base_url=provider.base_url,
            supported_model_types=[item.value for item in provider.supported_model_types],
            credential_ciphertext=provider.credential_ciphertext,
            credential_nonce=provider.credential_nonce,
            credential_key_version=provider.credential_key_version,
            credential_prefix=provider.credential_prefix,
            credential_revision=provider.credential_revision,
            enabled=provider.enabled,
            revision=provider.revision,
            created_at=provider.created_at,
            updated_at=provider.updated_at,
            deleted_at=provider.deleted_at,
        )

    @staticmethod
    def _to_domain(model: ModelProviderModel, model_count: int) -> ModelProvider:
        return ModelProvider(
            id=model.id,
            provider_type=model.provider_type,
            display_name=model.display_name,
            base_url=model.base_url,
            supported_model_types=tuple(ModelType(item) for item in model.supported_model_types),
            credential_ciphertext=model.credential_ciphertext,
            credential_nonce=model.credential_nonce,
            credential_key_version=model.credential_key_version,
            credential_prefix=model.credential_prefix,
            credential_revision=model.credential_revision,
            enabled=model.enabled,
            revision=model.revision,
            created_at=model.created_at,
            updated_at=model.updated_at,
            deleted_at=model.deleted_at,
            model_count=model_count,
        )


class SqlAlchemyModelRepository:
    def add(self, session: Session, model: ModelConfig) -> None:
        session.add(self._to_model(model))

    def get(
        self,
        session: Session,
        model_id: UUID,
        *,
        for_update: bool = False,
    ) -> ModelConfig | None:
        statement = select(ModelConfigModel).where(
            ModelConfigModel.id == model_id,
            ModelConfigModel.deleted_at.is_(None),
        )
        if for_update:
            statement = statement.with_for_update()
        model = session.scalar(statement)
        return self._to_domain(model) if model is not None else None

    def find_identity(
        self,
        session: Session,
        provider_id: UUID,
        model_name: str,
        model_type: ModelType,
    ) -> ModelConfig | None:
        model = session.scalar(
            select(ModelConfigModel).where(
                ModelConfigModel.provider_id == provider_id,
                ModelConfigModel.model_name == model_name,
                ModelConfigModel.model_type == model_type.value,
                ModelConfigModel.deleted_at.is_(None),
            )
        )
        return self._to_domain(model) if model is not None else None

    def list(self, session: Session, query: ModelConfigListQuery) -> ModelConfigPage:
        conditions: list[ColumnElement[bool]] = [ModelConfigModel.deleted_at.is_(None)]
        if query.provider_id is not None:
            conditions.append(ModelConfigModel.provider_id == query.provider_id)
        if query.model_type is not None:
            conditions.append(ModelConfigModel.model_type == query.model_type.value)
        if query.enabled is not None:
            conditions.append(ModelConfigModel.enabled == query.enabled)
        if query.verification_status is not None:
            conditions.append(ModelConfigModel.verification_status == query.verification_status)
        if query.search:
            pattern = f"%{query.search.strip()}%"
            conditions.append(
                or_(
                    ModelConfigModel.display_name.ilike(pattern),
                    ModelConfigModel.model_name.ilike(pattern),
                )
            )
        ordering = {
            "display_name": asc(func.lower(ModelConfigModel.display_name)),
            "-display_name": desc(func.lower(ModelConfigModel.display_name)),
            "created_at": asc(ModelConfigModel.created_at),
            "-created_at": desc(ModelConfigModel.created_at),
        }
        models = session.scalars(
            select(ModelConfigModel)
            .where(*conditions)
            .order_by(ordering[query.sort], ModelConfigModel.id)
            .offset((query.page - 1) * query.page_size)
            .limit(query.page_size)
        ).all()
        total = (
            session.scalar(select(func.count()).select_from(ModelConfigModel).where(*conditions))
            or 0
        )
        return ModelConfigPage(
            items=[self._to_domain(model) for model in models],
            total=total,
            page=query.page,
            page_size=query.page_size,
        )

    def save(self, session: Session, model: ModelConfig) -> None:
        stored = session.get(ModelConfigModel, model.id)
        if stored is None:
            raise LookupError("model config no longer exists")
        stored.model_name = model.model_name
        stored.display_name = model.display_name
        stored.model_type = model.model_type.value
        stored.enabled = model.enabled
        stored.verification_status = model.verification_status.value
        stored.context_window = model.context_window
        stored.max_output_tokens = model.max_output_tokens
        stored.embedding_dimension = model.embedding_dimension
        stored.capability_version = model.capability_version
        stored.default_params = model.default_params
        stored.config_schema = model.config_schema
        stored.revision = model.revision
        stored.updated_at = model.updated_at
        stored.deleted_at = model.deleted_at

    def latest_verification(
        self,
        session: Session,
        model_id: UUID,
    ) -> ModelVerificationSnapshot | None:
        verification = session.scalar(
            select(ModelVerificationModel)
            .where(ModelVerificationModel.model_id == model_id)
            .order_by(ModelVerificationModel.tested_at.desc(), ModelVerificationModel.id.desc())
            .limit(1)
        )
        if verification is None:
            return None
        return ModelVerificationSnapshot(
            model_id=verification.model_id,
            tested_model_revision=verification.tested_model_revision,
            tested_provider_revision=verification.tested_provider_revision,
            tested_credential_revision=verification.tested_credential_revision,
            status=verification.status,
            latency_ms=verification.latency_ms,
            error_code=verification.error_code,
            tested_at=verification.tested_at,
        )

    def references(self, session: Session, model_id: UUID) -> tuple[ModelReference, ...]:
        return ()

    @staticmethod
    def _to_model(model: ModelConfig) -> ModelConfigModel:
        return ModelConfigModel(
            id=model.id,
            provider_id=model.provider_id,
            model_name=model.model_name,
            display_name=model.display_name,
            model_type=model.model_type.value,
            enabled=model.enabled,
            verification_status=model.verification_status.value,
            context_window=model.context_window,
            max_output_tokens=model.max_output_tokens,
            embedding_dimension=model.embedding_dimension,
            capability_version=model.capability_version,
            default_params=model.default_params,
            config_schema=model.config_schema,
            revision=model.revision,
            created_at=model.created_at,
            updated_at=model.updated_at,
            deleted_at=model.deleted_at,
        )

    @staticmethod
    def _to_domain(model: ModelConfigModel) -> ModelConfig:
        return ModelConfig(
            id=model.id,
            provider_id=model.provider_id,
            model_name=model.model_name,
            display_name=model.display_name,
            model_type=ModelType(model.model_type),
            enabled=model.enabled,
            verification_status=VerificationStatus(model.verification_status),
            context_window=model.context_window,
            max_output_tokens=model.max_output_tokens,
            embedding_dimension=model.embedding_dimension,
            capability_version=model.capability_version,
            default_params=dict(model.default_params),
            config_schema=dict(model.config_schema),
            revision=model.revision,
            created_at=model.created_at,
            updated_at=model.updated_at,
            deleted_at=model.deleted_at,
        )


class SqlAlchemyModelAuditRepository:
    def record(
        self,
        session: Session,
        *,
        occurred_at: datetime,
        actor_id: UUID,
        event_code: str,
        target_id: UUID,
        target_name: str,
        change_summary: Mapping[str, object],
        trace_id: UUID | None,
        source_ip: str | None,
        user_agent: str | None,
    ) -> None:
        session.add(
            AuditLogModel(
                id=uuid4(),
                occurred_at=occurred_at,
                actor_type="administrator",
                actor_id=actor_id,
                event_code=event_code,
                target_type="model_provider",
                target_id=target_id,
                target_name_snapshot=target_name,
                trace_id=trace_id,
                source_ip=self._valid_ip(source_ip),
                user_agent=user_agent,
                change_summary=dict(change_summary),
                result_status="succeeded",
            )
        )

    @staticmethod
    def _valid_ip(source_ip: str | None) -> str | None:
        if source_ip is None:
            return None
        try:
            return ipaddress.ip_address(source_ip).compressed
        except ValueError:
            return None


class SqlAlchemyProviderTaskStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self._providers = SqlAlchemyModelProviderRepository()

    def load(
        self,
        operation_id: UUID,
        expected_task_type: str,
    ) -> ProviderTaskSnapshot | None:
        with transaction(self._session_factory) as session:
            operation = session.get(OperationModel, operation_id)
            if (
                operation is None
                or operation.task_type != expected_task_type
                or operation.target_type != "model_provider"
            ):
                return None
            provider = self._providers.get(session, operation.target_id)
            if provider is None:
                return None
            return ProviderTaskSnapshot(operation_id=operation.id, provider=provider)

    def provider_revision_matches(self, provider_id: UUID, revision: int) -> bool:
        with transaction(self._session_factory) as session:
            current = session.scalar(
                select(ModelProviderModel.revision).where(
                    ModelProviderModel.id == provider_id,
                    ModelProviderModel.deleted_at.is_(None),
                )
            )
        return current == revision

    def save_discovered_candidates(
        self,
        snapshot: ProviderTaskSnapshot,
        candidates: tuple[DiscoveredModel, ...],
        discovered_at: datetime,
    ) -> bool:
        with transaction(self._session_factory) as session:
            current_revision = session.scalar(
                select(ModelProviderModel.revision).where(
                    ModelProviderModel.id == snapshot.provider.id,
                    ModelProviderModel.deleted_at.is_(None),
                )
            )
            for candidate in candidates:
                statement = insert(ModelDiscoveredCandidateModel).values(
                    id=uuid4(),
                    provider_id=snapshot.provider.id,
                    discovery_operation_id=snapshot.operation_id,
                    model_name=candidate.model_name,
                    suggested_types=[item.value for item in candidate.suggested_types],
                    provider_status=candidate.provider_status,
                    raw_metadata_summary=dict(candidate.metadata_summary),
                    discovered_at=discovered_at,
                )
                session.execute(
                    statement.on_conflict_do_update(
                        constraint="model_discovered_candidates_operation_model_uq",
                        set_={
                            "suggested_types": statement.excluded.suggested_types,
                            "provider_status": statement.excluded.provider_status,
                            "raw_metadata_summary": statement.excluded.raw_metadata_summary,
                            "discovered_at": statement.excluded.discovered_at,
                        },
                    )
                )
        return current_revision != snapshot.provider.revision
