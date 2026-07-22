from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.core.network_security import AddressResolver, validate_outbound_base_url
from app.core.security import encrypt_secret
from app.modules.capabilities.errors import CapabilityNotFoundError
from app.modules.capabilities.service import CapabilityService
from app.modules.models.domain import (
    DiscoveredModelCandidate,
    ModelConfig,
    ModelConfigDetails,
    ModelProvider,
    ModelReference,
    ModelType,
    ModelVerificationSnapshot,
    SelectableModel,
    VerificationStatus,
    mask_credential,
    provider_credential_aad,
)
from app.modules.models.ports import ModelAuditRepository
from app.modules.models.repository import (
    ModelConfigListQuery,
    ModelConfigRepository,
    ModelProviderListQuery,
    ModelProviderPage,
    ModelProviderRepository,
)
from app.modules.models.tasks import (
    MODEL_PROVIDER_DISCOVERY_TASK,
    MODEL_PROVIDER_TEST_TASK,
)
from app.modules.tasks.domain import Operation
from app.modules.tasks.idempotency import AdminIdempotencyService
from app.modules.tasks.service import TaskService


class ModelProviderNotFoundError(LookupError):
    pass


class ModelProviderNameConflictError(ValueError):
    pass


class ModelProviderRevisionConflictError(ValueError):
    pass


class ModelProviderInUseError(ValueError):
    pass


class ModelProviderCapabilityError(ValueError):
    pass


class ModelConfigNotFoundError(LookupError):
    pass


class ModelIdentityConflictError(ValueError):
    pass


class ModelProviderDisabledError(ValueError):
    pass


class ModelConfigRevisionConflictError(ValueError):
    pass


class ModelInUseError(ValueError):
    def __init__(self, references: tuple[ModelReference, ...]) -> None:
        super().__init__("model config is in use")
        self.references = references


class ModelNotSelectableError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ModelConfigDetailsPage:
    items: list[ModelConfigDetails]
    total: int
    page: int
    page_size: int


class ModelProviderService:
    def __init__(
        self,
        *,
        providers: ModelProviderRepository,
        audits: ModelAuditRepository,
        capabilities: CapabilityService,
        encryption_key: bytes,
        app_env: Literal["development", "test", "production"],
        allow_local_http: bool,
        tasks: TaskService,
        idempotency: AdminIdempotencyService,
        operation_retention_days: int,
        url_resolver: AddressResolver | None = None,
    ) -> None:
        self._providers = providers
        self._audits = audits
        self._capabilities = capabilities
        self._encryption_key = encryption_key
        self._app_env = app_env
        self._allow_local_http = allow_local_http
        self._tasks = tasks
        self._idempotency = idempotency
        self._operation_retention_days = operation_retention_days
        self._url_resolver = url_resolver

    def create(
        self,
        session: Session,
        *,
        provider_type: str,
        display_name: str,
        base_url: str,
        credential: str,
        supported_model_types: Sequence[ModelType] | None,
        actor_id: UUID,
        trace_id: UUID | None,
        source_ip: str | None,
        user_agent: str | None,
        now: datetime | None = None,
    ) -> ModelProvider:
        now = now or datetime.now(UTC)
        display_name = display_name.strip()
        self._ensure_name_available(session, display_name)
        model_types = self._provider_model_types(provider_type, supported_model_types)
        if self._url_resolver is None:
            normalized_url = validate_outbound_base_url(
                base_url,
                app_env=self._app_env,
                allow_local_http=self._allow_local_http,
            )
        else:
            normalized_url = validate_outbound_base_url(
                base_url,
                app_env=self._app_env,
                allow_local_http=self._allow_local_http,
                resolver=self._url_resolver,
            )
        provider_id = uuid4()
        encrypted = encrypt_secret(
            credential.encode("utf-8"),
            self._encryption_key,
            associated_data=provider_credential_aad(provider_id),
            key_version="v1",
        )
        provider = ModelProvider(
            id=provider_id,
            provider_type=provider_type,
            display_name=display_name,
            base_url=normalized_url,
            supported_model_types=model_types,
            credential_ciphertext=encrypted.ciphertext,
            credential_nonce=encrypted.nonce,
            credential_key_version=encrypted.key_version,
            credential_prefix=mask_credential(credential),
            credential_revision=1,
            enabled=True,
            revision=1,
            created_at=now,
            updated_at=now,
            deleted_at=None,
            model_count=0,
        )
        self._providers.add(session, provider)
        self._record_audit(
            session,
            provider=provider,
            event_code="model_provider.created",
            changed_fields=("providerType", "displayName", "baseUrl", "supportedModelTypes"),
            actor_id=actor_id,
            trace_id=trace_id,
            source_ip=source_ip,
            user_agent=user_agent,
            now=now,
        )
        return provider

    def get(self, session: Session, provider_id: UUID) -> ModelProvider:
        provider = self._providers.get(session, provider_id)
        if provider is None:
            raise ModelProviderNotFoundError
        return provider

    def list(
        self,
        session: Session,
        query: ModelProviderListQuery,
    ) -> ModelProviderPage:
        return self._providers.list(session, query)

    def request_provider_test(
        self,
        session: Session,
        provider_id: UUID,
        *,
        expected_revision: int,
        administrator_id: UUID,
        idempotency_key: str,
        now: datetime,
    ) -> Operation:
        return self._request_operation(
            session,
            provider_id,
            expected_revision=expected_revision,
            administrator_id=administrator_id,
            idempotency_key=idempotency_key,
            endpoint_code="model_provider.test",
            task_type=MODEL_PROVIDER_TEST_TASK,
            event_type="model.provider.test.requested",
            now=now,
        )

    def request_provider_discovery(
        self,
        session: Session,
        provider_id: UUID,
        *,
        expected_revision: int,
        administrator_id: UUID,
        idempotency_key: str,
        now: datetime,
    ) -> Operation:
        return self._request_operation(
            session,
            provider_id,
            expected_revision=expected_revision,
            administrator_id=administrator_id,
            idempotency_key=idempotency_key,
            endpoint_code="model_provider.discover",
            task_type=MODEL_PROVIDER_DISCOVERY_TASK,
            event_type="model.provider.discovery.requested",
            now=now,
        )

    def list_discovered_candidates(
        self,
        session: Session,
        provider_id: UUID,
        *,
        model_type: ModelType | None,
        provider_status: str | None,
    ) -> Sequence[DiscoveredModelCandidate]:
        self.get(session, provider_id)
        return self._providers.list_discovered_candidates(
            session,
            provider_id,
            model_type=model_type,
            provider_status=provider_status,
        )

    def update(
        self,
        session: Session,
        provider_id: UUID,
        *,
        expected_revision: int,
        display_name: str | None,
        credential: str | None,
        actor_id: UUID,
        trace_id: UUID | None,
        source_ip: str | None,
        user_agent: str | None,
        now: datetime | None = None,
    ) -> ModelProvider:
        now = now or datetime.now(UTC)
        provider = self._providers.get(session, provider_id, for_update=True)
        if provider is None:
            raise ModelProviderNotFoundError
        if provider.revision != expected_revision:
            raise ModelProviderRevisionConflictError

        changed_fields: list[str] = []
        if display_name is not None:
            normalized_name = display_name.strip()
            if normalized_name.casefold() != provider.display_name.casefold():
                self._ensure_name_available(session, normalized_name)
            if normalized_name != provider.display_name:
                provider.display_name = normalized_name
                changed_fields.append("displayName")
        if credential is not None:
            encrypted = encrypt_secret(
                credential.encode("utf-8"),
                self._encryption_key,
                associated_data=provider_credential_aad(provider.id),
                key_version="v1",
            )
            provider.credential_ciphertext = encrypted.ciphertext
            provider.credential_nonce = encrypted.nonce
            provider.credential_key_version = encrypted.key_version
            provider.credential_prefix = mask_credential(credential)
            provider.credential_revision += 1
            self._providers.mark_models_stale(session, provider.id)
            changed_fields.append("credential")

        if changed_fields:
            provider.revision += 1
            provider.updated_at = now
            self._providers.save(session, provider)
            self._record_audit(
                session,
                provider=provider,
                event_code="model_provider.updated",
                changed_fields=tuple(changed_fields),
                actor_id=actor_id,
                trace_id=trace_id,
                source_ip=source_ip,
                user_agent=user_agent,
                now=now,
            )
        return provider

    def delete(
        self,
        session: Session,
        provider_id: UUID,
        *,
        expected_revision: int,
        actor_id: UUID,
        trace_id: UUID | None,
        source_ip: str | None,
        user_agent: str | None,
        now: datetime | None = None,
    ) -> None:
        now = now or datetime.now(UTC)
        provider = self._providers.get(session, provider_id, for_update=True)
        if provider is None:
            raise ModelProviderNotFoundError
        if provider.revision != expected_revision:
            raise ModelProviderRevisionConflictError
        if self._providers.has_models(session, provider.id):
            raise ModelProviderInUseError
        provider.deleted_at = now
        provider.updated_at = now
        provider.revision += 1
        self._providers.save(session, provider)
        self._record_audit(
            session,
            provider=provider,
            event_code="model_provider.deleted",
            changed_fields=("deletedAt",),
            actor_id=actor_id,
            trace_id=trace_id,
            source_ip=source_ip,
            user_agent=user_agent,
            now=now,
        )

    def _ensure_name_available(self, session: Session, display_name: str) -> None:
        if self._providers.find_by_display_name(session, display_name) is not None:
            raise ModelProviderNameConflictError

    def _request_operation(
        self,
        session: Session,
        provider_id: UUID,
        *,
        expected_revision: int,
        administrator_id: UUID,
        idempotency_key: str,
        endpoint_code: str,
        task_type: str,
        event_type: str,
        now: datetime,
    ) -> Operation:
        request_body: dict[str, object] = {
            "providerId": str(provider_id),
            "expectedRevision": expected_revision,
        }
        existing = self._idempotency.find(
            session,
            administrator_id=administrator_id,
            endpoint_code=endpoint_code,
            idempotency_key=idempotency_key,
            request_body=request_body,
        )
        if existing is not None and existing.operation_id is not None:
            return self._tasks.get(session, existing.operation_id)

        provider = self.get(session, provider_id)
        if provider.revision != expected_revision:
            raise ModelProviderRevisionConflictError
        operation = self._tasks.create_operation(
            session,
            task_type=task_type,
            target_type="model_provider",
            target_id=provider.id,
            target_revision=provider.revision,
            business_key=(f"admin:{administrator_id}:{endpoint_code}:{idempotency_key}"),
            event_type=event_type,
            payload={
                "providerId": str(provider.id),
                "providerRevision": provider.revision,
            },
            now=now,
            expires_at=now + timedelta(days=self._operation_retention_days),
        )
        self._idempotency.reserve(
            session,
            administrator_id=administrator_id,
            endpoint_code=endpoint_code,
            idempotency_key=idempotency_key,
            request_body=request_body,
            operation_id=operation.id,
            now=now,
        )
        return operation

    def _provider_model_types(
        self,
        provider_type: str,
        requested: Sequence[ModelType] | None,
    ) -> tuple[ModelType, ...]:
        try:
            capability = self._capabilities.get(provider_type, "1")
        except CapabilityNotFoundError as error:
            raise ModelProviderCapabilityError from error
        if not capability.enabled or capability.category != "model_provider":
            raise ModelProviderCapabilityError
        schema = capability.config_schema
        if not isinstance(schema, Mapping):
            raise ModelProviderCapabilityError
        properties = schema.get("properties")
        if not isinstance(properties, Mapping):
            raise ModelProviderCapabilityError
        type_schema = properties.get("supportedModelTypes")
        if not isinstance(type_schema, Mapping):
            raise ModelProviderCapabilityError
        default = type_schema.get("default")
        items = type_schema.get("items")
        allowed_values = items.get("enum") if isinstance(items, Mapping) else None
        if not isinstance(default, tuple) or not isinstance(allowed_values, tuple):
            raise ModelProviderCapabilityError
        configured = (
            tuple(ModelType(value) for value in default) if requested is None else tuple(requested)
        )
        if not configured or len(set(configured)) != len(configured):
            raise ModelProviderCapabilityError
        allowed = {ModelType(value) for value in allowed_values}
        if not set(configured).issubset(allowed):
            raise ModelProviderCapabilityError
        if type_schema.get("readOnly") is True and configured != tuple(
            ModelType(v) for v in default
        ):
            raise ModelProviderCapabilityError
        return configured

    def _record_audit(
        self,
        session: Session,
        *,
        provider: ModelProvider,
        event_code: str,
        changed_fields: tuple[str, ...],
        actor_id: UUID,
        trace_id: UUID | None,
        source_ip: str | None,
        user_agent: str | None,
        now: datetime,
    ) -> None:
        safe_fields = [field for field in changed_fields if field != "credential"]
        if "credential" in changed_fields:
            safe_fields.append("credentialRotated")
        self._audits.record(
            session,
            occurred_at=now,
            actor_id=actor_id,
            event_code=event_code,
            target_id=provider.id,
            target_name=provider.display_name,
            change_summary={"changedFields": safe_fields, "revision": provider.revision},
            trace_id=trace_id,
            source_ip=source_ip,
            user_agent=user_agent,
        )


class ModelSelectionService:
    def __init__(
        self,
        models: ModelConfigRepository,
        providers: ModelProviderRepository,
    ) -> None:
        self._models = models
        self._providers = providers

    def require_selectable(
        self,
        session: Session,
        model_id: UUID,
        expected_type: ModelType,
    ) -> SelectableModel:
        model = self._models.get(session, model_id)
        if model is None:
            raise ModelNotSelectableError("MODEL_NOT_FOUND")
        if model.model_type is not expected_type:
            raise ModelNotSelectableError("MODEL_TYPE_MISMATCH")
        provider = self._providers.get(session, model.provider_id)
        verification = self._models.latest_verification(session, model.id)
        if (
            provider is None
            or verification is None
            or not _is_currently_verified(
                model,
                provider,
                verification,
                require_enabled=True,
            )
        ):
            raise ModelNotSelectableError("MODEL_VERIFICATION_REQUIRED")
        return SelectableModel(model=model, provider=provider, verification=verification)


class ModelConfigService:
    def __init__(
        self,
        models: ModelConfigRepository,
        providers: ModelProviderRepository,
        capabilities: CapabilityService | None,
    ) -> None:
        self._models = models
        self._providers = providers
        self._capabilities = capabilities

    def create(
        self,
        session: Session,
        *,
        provider_id: UUID,
        model_name: str,
        display_name: str,
        model_type: ModelType,
        context_window: int | None,
        max_output_tokens: int | None,
        embedding_dimension: int | None,
        default_params: dict[str, object],
        now: datetime | None = None,
    ) -> ModelConfigDetails:
        now = now or datetime.now(UTC)
        provider = self._required_provider(session, provider_id, require_enabled=True)
        self._ensure_provider_accepts(provider, model_type)
        if self._models.find_identity(session, provider_id, model_name, model_type) is not None:
            raise ModelIdentityConflictError
        capability_schema = self._capability_schema(model_type, "1")
        model = ModelConfig(
            id=uuid4(),
            provider_id=provider.id,
            model_name=model_name.strip(),
            display_name=display_name.strip(),
            model_type=model_type,
            enabled=False,
            verification_status=VerificationStatus.UNTESTED,
            context_window=context_window,
            max_output_tokens=max_output_tokens,
            embedding_dimension=embedding_dimension,
            capability_version="1",
            default_params=dict(default_params),
            config_schema=capability_schema,
            revision=1,
            created_at=now,
            updated_at=now,
            deleted_at=None,
        )
        self._models.add(session, model)
        return ModelConfigDetails(model, provider, None, ())

    def get(self, session: Session, model_id: UUID) -> ModelConfigDetails:
        model = self._required_model(session, model_id)
        return self._details(session, model)

    def list(
        self,
        session: Session,
        query: ModelConfigListQuery,
    ) -> ModelConfigDetailsPage:
        page = self._models.list(session, query)
        return ModelConfigDetailsPage(
            items=[self._details(session, model) for model in page.items],
            total=page.total,
            page=page.page,
            page_size=page.page_size,
        )

    def update(
        self,
        session: Session,
        model_id: UUID,
        *,
        expected_revision: int,
        model_name: str | None,
        display_name: str | None,
        model_type: ModelType | None,
        context_window: int | None,
        max_output_tokens: int | None,
        embedding_dimension: int | None,
        capability_version: str | None,
        default_params: dict[str, object] | None,
        config_schema: dict[str, object] | None,
        now: datetime | None = None,
    ) -> ModelConfigDetails:
        now = now or datetime.now(UTC)
        model = self._required_model(session, model_id, for_update=True)
        if model.revision != expected_revision:
            raise ModelConfigRevisionConflictError
        next_name = model_name.strip() if model_name is not None else model.model_name
        next_type = model_type or model.model_type
        next_capability = capability_version or model.capability_version
        identity_changed = (
            next_name != model.model_name
            or next_type is not model.model_type
            or next_capability != model.capability_version
        )
        if identity_changed:
            self._ensure_not_referenced(session, model.id)
            provider = self._required_provider(
                session,
                model.provider_id,
                require_enabled=True,
            )
            self._ensure_provider_accepts(provider, next_type)
            self._capability_schema(next_type, next_capability)
            existing = self._models.find_identity(
                session,
                model.provider_id,
                next_name,
                next_type,
            )
            if existing is not None and existing.id != model.id:
                raise ModelIdentityConflictError

        call_changes = {
            "model_name": next_name,
            "model_type": next_type,
            "context_window": context_window,
            "max_output_tokens": max_output_tokens,
            "embedding_dimension": embedding_dimension,
            "capability_version": next_capability,
            "default_params": default_params,
            "config_schema": config_schema,
        }
        changed_call = False
        for field_name, value in call_changes.items():
            if value is not None and getattr(model, field_name) != value:
                setattr(model, field_name, value)
                changed_call = True
        if display_name is not None:
            model.display_name = display_name.strip()
        if changed_call:
            model.revision += 1
            model.verification_status = VerificationStatus.STALE
        model.updated_at = now
        self._models.save(session, model)
        return self._details(session, model)

    def enable(
        self,
        session: Session,
        model_id: UUID,
        *,
        expected_revision: int,
        now: datetime | None = None,
    ) -> ModelConfigDetails:
        now = now or datetime.now(UTC)
        model = self._required_model(session, model_id, for_update=True)
        if model.revision != expected_revision:
            raise ModelConfigRevisionConflictError
        provider = self._required_provider(session, model.provider_id)
        verification = self._models.latest_verification(session, model.id)
        if verification is None or not _is_currently_verified(
            model,
            provider,
            verification,
            require_enabled=False,
        ):
            raise ModelNotSelectableError("MODEL_VERIFICATION_REQUIRED")
        model.enabled = True
        model.updated_at = now
        self._models.save(session, model)
        return self._details(session, model)

    def disable(
        self,
        session: Session,
        model_id: UUID,
        *,
        expected_revision: int,
        now: datetime | None = None,
    ) -> ModelConfigDetails:
        now = now or datetime.now(UTC)
        model = self._required_model(session, model_id, for_update=True)
        if model.revision != expected_revision:
            raise ModelConfigRevisionConflictError
        self._ensure_not_referenced(session, model.id)
        model.enabled = False
        model.updated_at = now
        self._models.save(session, model)
        return self._details(session, model)

    def delete(
        self,
        session: Session,
        model_id: UUID,
        *,
        expected_revision: int,
        now: datetime | None = None,
    ) -> None:
        now = now or datetime.now(UTC)
        model = self._required_model(session, model_id, for_update=True)
        if model.revision != expected_revision:
            raise ModelConfigRevisionConflictError
        self._ensure_not_referenced(session, model.id)
        model.enabled = False
        model.deleted_at = now
        model.updated_at = now
        self._models.save(session, model)

    def references(self, session: Session, model_id: UUID) -> tuple[ModelReference, ...]:
        self._required_model(session, model_id)
        return self._models.references(session, model_id)

    def _required_model(
        self,
        session: Session,
        model_id: UUID,
        *,
        for_update: bool = False,
    ) -> ModelConfig:
        model = self._models.get(session, model_id, for_update=for_update)
        if model is None:
            raise ModelConfigNotFoundError
        return model

    def _required_provider(
        self,
        session: Session,
        provider_id: UUID,
        *,
        require_enabled: bool = False,
    ) -> ModelProvider:
        provider = self._providers.get(session, provider_id)
        if provider is None:
            raise ModelProviderNotFoundError
        if require_enabled and not provider.enabled:
            raise ModelProviderDisabledError
        return provider

    def _details(self, session: Session, model: ModelConfig) -> ModelConfigDetails:
        provider = self._required_provider(session, model.provider_id)
        return ModelConfigDetails(
            model=model,
            provider=provider,
            verification=self._models.latest_verification(session, model.id),
            references=self._models.references(session, model.id),
        )

    def _ensure_provider_accepts(self, provider: ModelProvider, model_type: ModelType) -> None:
        if model_type not in provider.supported_model_types:
            raise ModelNotSelectableError("MODEL_TYPE_MISMATCH")

    def _capability_schema(self, model_type: ModelType, version: str) -> dict[str, object]:
        if self._capabilities is None:
            raise ModelNotSelectableError("MODEL_TYPE_MISMATCH")
        try:
            capability = self._capabilities.get(model_type.value, version)
        except CapabilityNotFoundError as error:
            raise ModelNotSelectableError("MODEL_TYPE_MISMATCH") from error
        if not capability.enabled or capability.category != "model_type":
            raise ModelNotSelectableError("MODEL_TYPE_MISMATCH")
        return _thaw_mapping(capability.config_schema)

    def _ensure_not_referenced(self, session: Session, model_id: UUID) -> None:
        references = self._models.references(session, model_id)
        if references:
            raise ModelInUseError(references)


def _is_currently_verified(
    model: ModelConfig,
    provider: ModelProvider,
    verification: ModelVerificationSnapshot,
    *,
    require_enabled: bool,
) -> bool:
    return (
        (model.enabled or not require_enabled)
        and provider.enabled
        and model.verification_status is VerificationStatus.PASSED
        and verification.status == "succeeded"
        and verification.tested_model_revision == model.revision
        and verification.tested_provider_revision == provider.revision
        and verification.tested_credential_revision == provider.credential_revision
    )


def _thaw_mapping(value: Mapping[str, object] | None) -> dict[str, object]:
    if value is None:
        return {}
    return {key: _thaw_json(item) for key, item in value.items()}


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value
