import ipaddress
from collections.abc import Mapping
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Select, asc, desc, func, select, update
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.infrastructure.database.models.auth import AuditLogModel
from app.infrastructure.database.models.models import ModelConfigModel, ModelProviderModel
from app.modules.models.domain import ModelProvider, ModelType, VerificationStatus
from app.modules.models.repository import (
    ModelProviderListQuery,
    ModelProviderPage,
)


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
