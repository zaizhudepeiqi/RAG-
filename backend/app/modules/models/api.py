from datetime import UTC, datetime
from enum import IntEnum
from typing import Annotated, Literal, Protocol, TypedDict, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import AppError
from app.core.network_security import OutboundUrlPolicyError
from app.infrastructure.database.session import transaction
from app.modules.auth.dependencies import require_admin, require_csrf
from app.modules.auth.domain import Administrator
from app.modules.models.domain import ModelType
from app.modules.models.repository import ModelConfigListQuery, ModelProviderListQuery
from app.modules.models.schemas import (
    CreateModelProviderRequest,
    CreateModelRequest,
    DiscoveredModelView,
    ModelPageView,
    ModelProviderPageView,
    ModelProviderView,
    ModelReferenceView,
    ModelStateRequest,
    ModelView,
    ProviderOperationRequest,
    UpdateModelProviderRequest,
    UpdateModelRequest,
    discovered_model_view,
    model_provider_view,
    model_reference_view,
    model_view,
)
from app.modules.models.service import (
    ModelConfigNotFoundError,
    ModelConfigRevisionConflictError,
    ModelConfigService,
    ModelIdentityConflictError,
    ModelInUseError,
    ModelNotSelectableError,
    ModelProviderCapabilityError,
    ModelProviderDisabledError,
    ModelProviderInUseError,
    ModelProviderNameConflictError,
    ModelProviderNotFoundError,
    ModelProviderRevisionConflictError,
    ModelProviderService,
)
from app.modules.tasks.domain import Operation
from app.modules.tasks.errors import IdempotencyKeyReusedError
from app.modules.tasks.schemas import OperationRef


class ModelDependencies(Protocol):
    session_factory: sessionmaker[Session]
    model_provider_service: ModelProviderService
    model_config_service: ModelConfigService


class ProviderPageSize(IntEnum):
    DEFAULT = 20
    MEDIUM = 50
    LARGE = 100


class AuditArguments(TypedDict):
    actor_id: UUID
    trace_id: UUID | None
    source_ip: str | None
    user_agent: str | None


router = APIRouter(
    prefix="/api/v1/model-providers",
    tags=["模型供应商"],
    dependencies=[Depends(require_admin)],
)

models_router = APIRouter(
    prefix="/api/v1/models",
    tags=["模型配置"],
    dependencies=[Depends(require_admin)],
)


def get_model_dependencies(request: Request) -> ModelDependencies:
    return cast(ModelDependencies, request.app.state.dependencies)


@router.get("", response_model=ModelProviderPageView, operation_id="modelProvidersList")
def list_model_providers(
    dependencies: Annotated[ModelDependencies, Depends(get_model_dependencies)],
    search: str | None = None,
    enabled: bool | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[ProviderPageSize, Query(alias="pageSize")] = ProviderPageSize.DEFAULT,
    sort: Literal["display_name", "-display_name", "created_at", "-created_at"] = "display_name",
) -> ModelProviderPageView:
    with transaction(dependencies.session_factory) as session:
        result = dependencies.model_provider_service.list(
            session,
            ModelProviderListQuery(
                search=search,
                enabled=enabled,
                page=page,
                page_size=page_size,
                sort=sort,
            ),
        )
    return ModelProviderPageView(
        items=[model_provider_view(item) for item in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.post(
    "",
    response_model=ModelProviderView,
    status_code=status.HTTP_201_CREATED,
    operation_id="modelProvidersCreate",
    dependencies=[Depends(require_csrf)],
)
def create_model_provider(
    payload: CreateModelProviderRequest,
    request: Request,
    administrator: Annotated[Administrator, Depends(require_admin)],
    dependencies: Annotated[ModelDependencies, Depends(get_model_dependencies)],
) -> ModelProviderView:
    try:
        with transaction(dependencies.session_factory) as session:
            provider = dependencies.model_provider_service.create(
                session,
                provider_type=payload.provider_type,
                display_name=payload.display_name,
                base_url=str(payload.base_url),
                credential=payload.credential.get_secret_value(),
                supported_model_types=payload.supported_model_types,
                **_audit_arguments(request, administrator),
            )
    except IntegrityError as error:
        raise _name_conflict() from error
    except ModelProviderNameConflictError as error:
        raise _name_conflict() from error
    except ModelProviderCapabilityError as error:
        raise AppError(
            code="MODEL_PROVIDER_TYPE_UNSUPPORTED",
            message="模型供应商类型或支持的模型类型无效",
            status_code=422,
        ) from error
    except OutboundUrlPolicyError as error:
        raise AppError(
            code=error.code,
            message="模型供应商地址不符合安全策略",
            status_code=422,
        ) from error
    return model_provider_view(provider)


@router.post(
    "/{providerId}:test",
    response_model=OperationRef,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="modelProvidersTest",
    dependencies=[Depends(require_csrf)],
)
def test_model_provider(
    payload: ProviderOperationRequest,
    provider_id: Annotated[UUID, Path(alias="providerId")],
    administrator: Annotated[Administrator, Depends(require_admin)],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=8, max_length=128),
    ],
    dependencies: Annotated[ModelDependencies, Depends(get_model_dependencies)],
) -> OperationRef:
    try:
        with transaction(dependencies.session_factory) as session:
            operation = dependencies.model_provider_service.request_provider_test(
                session,
                provider_id,
                expected_revision=payload.expected_revision,
                administrator_id=administrator.id,
                idempotency_key=idempotency_key,
                now=datetime.now(UTC),
            )
    except ModelProviderNotFoundError as error:
        raise _not_found() from error
    except ModelProviderRevisionConflictError as error:
        raise _revision_conflict() from error
    except IdempotencyKeyReusedError as error:
        raise _idempotency_reused() from error
    return _operation_ref(operation)


@router.post(
    "/{providerId}:discover-models",
    response_model=OperationRef,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="modelProvidersDiscover",
    dependencies=[Depends(require_csrf)],
)
def discover_provider_models(
    payload: ProviderOperationRequest,
    provider_id: Annotated[UUID, Path(alias="providerId")],
    administrator: Annotated[Administrator, Depends(require_admin)],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=8, max_length=128),
    ],
    dependencies: Annotated[ModelDependencies, Depends(get_model_dependencies)],
) -> OperationRef:
    try:
        with transaction(dependencies.session_factory) as session:
            operation = dependencies.model_provider_service.request_provider_discovery(
                session,
                provider_id,
                expected_revision=payload.expected_revision,
                administrator_id=administrator.id,
                idempotency_key=idempotency_key,
                now=datetime.now(UTC),
            )
    except ModelProviderNotFoundError as error:
        raise _not_found() from error
    except ModelProviderRevisionConflictError as error:
        raise _revision_conflict() from error
    except IdempotencyKeyReusedError as error:
        raise _idempotency_reused() from error
    return _operation_ref(operation)


@router.get(
    "/{providerId}",
    response_model=ModelProviderView,
    operation_id="modelProvidersGet",
)
def get_model_provider(
    provider_id: Annotated[UUID, Path(alias="providerId")],
    dependencies: Annotated[ModelDependencies, Depends(get_model_dependencies)],
) -> ModelProviderView:
    try:
        with transaction(dependencies.session_factory) as session:
            provider = dependencies.model_provider_service.get(session, provider_id)
    except ModelProviderNotFoundError as error:
        raise _not_found() from error
    return model_provider_view(provider)


@router.get(
    "/{providerId}/discovered-models",
    response_model=list[DiscoveredModelView],
    operation_id="modelProvidersDiscoveredModelsList",
)
def list_discovered_models(
    provider_id: Annotated[UUID, Path(alias="providerId")],
    dependencies: Annotated[ModelDependencies, Depends(get_model_dependencies)],
    model_type: Annotated[
        ModelType | None,
        Query(alias="modelType"),
    ] = None,
    provider_status: Annotated[
        Literal["available", "unavailable", "unknown"] | None,
        Query(alias="status"),
    ] = None,
) -> list[DiscoveredModelView]:
    try:
        with transaction(dependencies.session_factory) as session:
            candidates = dependencies.model_provider_service.list_discovered_candidates(
                session,
                provider_id,
                model_type=model_type,
                provider_status=provider_status,
            )
    except ModelProviderNotFoundError as error:
        raise _not_found() from error
    return [discovered_model_view(item) for item in candidates]


@router.patch(
    "/{providerId}",
    response_model=ModelProviderView,
    operation_id="modelProvidersUpdate",
    dependencies=[Depends(require_csrf)],
)
def update_model_provider(
    payload: UpdateModelProviderRequest,
    request: Request,
    provider_id: Annotated[UUID, Path(alias="providerId")],
    administrator: Annotated[Administrator, Depends(require_admin)],
    dependencies: Annotated[ModelDependencies, Depends(get_model_dependencies)],
) -> ModelProviderView:
    try:
        with transaction(dependencies.session_factory) as session:
            provider = dependencies.model_provider_service.update(
                session,
                provider_id,
                expected_revision=payload.expected_revision,
                display_name=payload.display_name,
                credential=(payload.credential.get_secret_value() if payload.credential else None),
                **_audit_arguments(request, administrator),
            )
    except IntegrityError as error:
        raise _name_conflict() from error
    except ModelProviderNameConflictError as error:
        raise _name_conflict() from error
    except ModelProviderNotFoundError as error:
        raise _not_found() from error
    except ModelProviderRevisionConflictError as error:
        raise _revision_conflict() from error
    return model_provider_view(provider)


@router.delete(
    "/{providerId}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="modelProvidersDelete",
    dependencies=[Depends(require_csrf)],
)
def delete_model_provider(
    request: Request,
    provider_id: Annotated[UUID, Path(alias="providerId")],
    expected_revision: Annotated[int, Query(alias="expectedRevision", ge=1)],
    administrator: Annotated[Administrator, Depends(require_admin)],
    dependencies: Annotated[ModelDependencies, Depends(get_model_dependencies)],
) -> Response:
    try:
        with transaction(dependencies.session_factory) as session:
            dependencies.model_provider_service.delete(
                session,
                provider_id,
                expected_revision=expected_revision,
                **_audit_arguments(request, administrator),
            )
    except ModelProviderNotFoundError as error:
        raise _not_found() from error
    except ModelProviderRevisionConflictError as error:
        raise _revision_conflict() from error
    except ModelProviderInUseError as error:
        raise AppError(
            code="MODEL_PROVIDER_IN_USE",
            message="模型供应商仍被模型配置引用",
            status_code=409,
        ) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@models_router.get("", response_model=ModelPageView, operation_id="modelsList")
def list_models(
    dependencies: Annotated[ModelDependencies, Depends(get_model_dependencies)],
    provider_id: Annotated[UUID | None, Query(alias="providerId")] = None,
    model_type: Annotated[ModelType | None, Query(alias="modelType")] = None,
    enabled: bool | None = None,
    verification_status: Annotated[
        Literal["untested", "passed", "failed", "stale"] | None,
        Query(alias="verificationStatus"),
    ] = None,
    search: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[ProviderPageSize, Query(alias="pageSize")] = ProviderPageSize.DEFAULT,
    sort: Literal["display_name", "-display_name", "created_at", "-created_at"] = "display_name",
) -> ModelPageView:
    with transaction(dependencies.session_factory) as session:
        result = dependencies.model_config_service.list(
            session,
            ModelConfigListQuery(
                provider_id=provider_id,
                model_type=model_type,
                enabled=enabled,
                verification_status=verification_status,
                search=search,
                page=page,
                page_size=page_size,
                sort=sort,
            ),
        )
    return ModelPageView(
        items=[model_view(item) for item in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@models_router.post(
    "",
    response_model=ModelView,
    status_code=status.HTTP_201_CREATED,
    operation_id="modelsCreate",
    dependencies=[Depends(require_csrf)],
)
def create_model(
    payload: CreateModelRequest,
    dependencies: Annotated[ModelDependencies, Depends(get_model_dependencies)],
) -> ModelView:
    try:
        with transaction(dependencies.session_factory) as session:
            details = dependencies.model_config_service.create(
                session,
                provider_id=payload.provider_id,
                model_name=payload.model_name,
                display_name=payload.display_name,
                model_type=payload.model_type,
                context_window=payload.context_window,
                max_output_tokens=payload.max_output_tokens,
                embedding_dimension=payload.embedding_dimension,
                default_params=payload.default_params,
            )
    except IntegrityError as error:
        raise _model_conflict() from error
    except ModelIdentityConflictError as error:
        raise _model_conflict() from error
    except ModelProviderNotFoundError as error:
        raise _not_found() from error
    except ModelProviderDisabledError as error:
        raise AppError(
            code="MODEL_PROVIDER_DISABLED",
            message="模型供应商已停用",
            status_code=409,
        ) from error
    except ModelNotSelectableError as error:
        raise _model_rule_error(error) from error
    return model_view(details)


@models_router.post(
    "/{modelId}:enable",
    response_model=ModelView,
    operation_id="modelsEnable",
    dependencies=[Depends(require_csrf)],
)
def enable_model(
    payload: ModelStateRequest,
    model_id: Annotated[UUID, Path(alias="modelId")],
    dependencies: Annotated[ModelDependencies, Depends(get_model_dependencies)],
) -> ModelView:
    try:
        with transaction(dependencies.session_factory) as session:
            details = dependencies.model_config_service.enable(
                session,
                model_id,
                expected_revision=payload.expected_revision,
            )
    except ModelConfigNotFoundError as error:
        raise _model_not_found() from error
    except ModelConfigRevisionConflictError as error:
        raise _revision_conflict() from error
    except ModelNotSelectableError as error:
        raise _model_rule_error(error) from error
    return model_view(details)


@models_router.post(
    "/{modelId}:disable",
    response_model=ModelView,
    operation_id="modelsDisable",
    dependencies=[Depends(require_csrf)],
)
def disable_model(
    payload: ModelStateRequest,
    model_id: Annotated[UUID, Path(alias="modelId")],
    dependencies: Annotated[ModelDependencies, Depends(get_model_dependencies)],
) -> ModelView:
    try:
        with transaction(dependencies.session_factory) as session:
            details = dependencies.model_config_service.disable(
                session,
                model_id,
                expected_revision=payload.expected_revision,
            )
    except ModelConfigNotFoundError as error:
        raise _model_not_found() from error
    except ModelConfigRevisionConflictError as error:
        raise _revision_conflict() from error
    except ModelInUseError as error:
        raise _model_in_use(error) from error
    return model_view(details)


@models_router.get(
    "/{modelId}/references",
    response_model=list[ModelReferenceView],
    operation_id="modelsReferences",
)
def model_references(
    model_id: Annotated[UUID, Path(alias="modelId")],
    dependencies: Annotated[ModelDependencies, Depends(get_model_dependencies)],
) -> list[ModelReferenceView]:
    try:
        with transaction(dependencies.session_factory) as session:
            references = dependencies.model_config_service.references(session, model_id)
    except ModelConfigNotFoundError as error:
        raise _model_not_found() from error
    return [model_reference_view(item) for item in references]


@models_router.get(
    "/{modelId}",
    response_model=ModelView,
    operation_id="modelsGet",
)
def get_model(
    model_id: Annotated[UUID, Path(alias="modelId")],
    dependencies: Annotated[ModelDependencies, Depends(get_model_dependencies)],
) -> ModelView:
    try:
        with transaction(dependencies.session_factory) as session:
            details = dependencies.model_config_service.get(session, model_id)
    except ModelConfigNotFoundError as error:
        raise _model_not_found() from error
    return model_view(details)


@models_router.patch(
    "/{modelId}",
    response_model=ModelView,
    operation_id="modelsUpdate",
    dependencies=[Depends(require_csrf)],
)
def update_model(
    payload: UpdateModelRequest,
    model_id: Annotated[UUID, Path(alias="modelId")],
    dependencies: Annotated[ModelDependencies, Depends(get_model_dependencies)],
) -> ModelView:
    try:
        with transaction(dependencies.session_factory) as session:
            details = dependencies.model_config_service.update(
                session,
                model_id,
                expected_revision=payload.expected_revision,
                model_name=payload.model_name,
                display_name=payload.display_name,
                model_type=payload.model_type,
                context_window=payload.context_window,
                max_output_tokens=payload.max_output_tokens,
                embedding_dimension=payload.embedding_dimension,
                capability_version=payload.capability_version,
                default_params=payload.default_params,
                config_schema=payload.config_schema,
            )
    except IntegrityError as error:
        raise _model_conflict() from error
    except ModelConfigNotFoundError as error:
        raise _model_not_found() from error
    except ModelConfigRevisionConflictError as error:
        raise _revision_conflict() from error
    except ModelIdentityConflictError as error:
        raise _model_conflict() from error
    except ModelInUseError as error:
        raise _model_in_use(error) from error
    except ModelNotSelectableError as error:
        raise _model_rule_error(error) from error
    return model_view(details)


@models_router.delete(
    "/{modelId}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="modelsDelete",
    dependencies=[Depends(require_csrf)],
)
def delete_model(
    model_id: Annotated[UUID, Path(alias="modelId")],
    expected_revision: Annotated[int, Query(alias="expectedRevision", ge=1)],
    dependencies: Annotated[ModelDependencies, Depends(get_model_dependencies)],
) -> Response:
    try:
        with transaction(dependencies.session_factory) as session:
            dependencies.model_config_service.delete(
                session,
                model_id,
                expected_revision=expected_revision,
            )
    except ModelConfigNotFoundError as error:
        raise _model_not_found() from error
    except ModelConfigRevisionConflictError as error:
        raise _revision_conflict() from error
    except ModelInUseError as error:
        raise _model_in_use(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _audit_arguments(request: Request, administrator: Administrator) -> AuditArguments:
    trace_id = getattr(request.state, "trace_id", None)
    return {
        "actor_id": administrator.id,
        "trace_id": trace_id if isinstance(trace_id, UUID) else None,
        "source_ip": request.client.host if request.client is not None else None,
        "user_agent": request.headers.get("User-Agent"),
    }


def _operation_ref(operation: Operation) -> OperationRef:
    return OperationRef(
        operation_id=operation.id,
        status=operation.status,
        status_url=f"/api/v1/operations/{operation.id}",
        target_type=operation.target_type,
        target_id=operation.target_id,
    )


def _name_conflict() -> AppError:
    return AppError(
        code="MODEL_PROVIDER_NAME_CONFLICT",
        message="模型供应商名称已存在",
        status_code=409,
    )


def _not_found() -> AppError:
    return AppError(
        code="MODEL_PROVIDER_NOT_FOUND",
        message="模型供应商不存在",
        status_code=404,
    )


def _revision_conflict() -> AppError:
    return AppError(
        code="REVISION_CONFLICT",
        message="资源已被其他请求更新",
        status_code=409,
    )


def _idempotency_reused() -> AppError:
    return AppError(
        code="IDEMPOTENCY_KEY_REUSED",
        message="幂等键已用于不同请求",
        status_code=409,
    )


def _model_not_found() -> AppError:
    return AppError(code="MODEL_NOT_FOUND", message="模型不存在", status_code=404)


def _model_conflict() -> AppError:
    return AppError(code="MODEL_CONFLICT", message="模型配置已存在", status_code=409)


def _model_rule_error(error: ModelNotSelectableError) -> AppError:
    return AppError(
        code=error.code,
        message=(
            "模型类型不匹配" if error.code == "MODEL_TYPE_MISMATCH" else "模型尚未通过当前配置验证"
        ),
        status_code=422 if error.code == "MODEL_TYPE_MISMATCH" else 409,
    )


def _model_in_use(error: ModelInUseError) -> AppError:
    references = [
        model_reference_view(item).model_dump(mode="json", by_alias=True)
        for item in error.references
    ]
    return AppError(
        code="MODEL_IN_USE",
        message="模型仍被业务配置引用",
        status_code=409,
        details={"references": references},
    )
