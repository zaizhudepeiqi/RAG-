from enum import IntEnum
from typing import Annotated, Literal, Protocol, TypedDict, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import AppError
from app.core.network_security import OutboundUrlPolicyError
from app.infrastructure.database.session import transaction
from app.modules.auth.dependencies import require_admin, require_csrf
from app.modules.auth.domain import Administrator
from app.modules.models.repository import ModelProviderListQuery
from app.modules.models.schemas import (
    CreateModelProviderRequest,
    ModelProviderPageView,
    ModelProviderView,
    UpdateModelProviderRequest,
    model_provider_view,
)
from app.modules.models.service import (
    ModelProviderCapabilityError,
    ModelProviderInUseError,
    ModelProviderNameConflictError,
    ModelProviderNotFoundError,
    ModelProviderRevisionConflictError,
    ModelProviderService,
)


class ModelDependencies(Protocol):
    session_factory: sessionmaker[Session]
    model_provider_service: ModelProviderService


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


def _audit_arguments(request: Request, administrator: Administrator) -> AuditArguments:
    trace_id = getattr(request.state, "trace_id", None)
    return {
        "actor_id": administrator.id,
        "trace_id": trace_id if isinstance(trace_id, UUID) else None,
        "source_ip": request.client.host if request.client is not None else None,
        "user_agent": request.headers.get("User-Agent"),
    }


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
