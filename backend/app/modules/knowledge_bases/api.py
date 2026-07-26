from typing import Annotated, Protocol, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path, Query, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import AppError
from app.infrastructure.database.session import transaction
from app.modules.auth.dependencies import require_admin, require_csrf
from app.modules.auth.domain import Administrator
from app.modules.knowledge_bases.errors import KnowledgeBaseConfigError
from app.modules.knowledge_bases.repository import KnowledgeBaseListQuery
from app.modules.knowledge_bases.schemas import (
    CreateKnowledgeBaseRequest,
    CreateKnowledgeBaseResponse,
    KnowledgeBaseDetailView,
    KnowledgeBasePageView,
    KnowledgeBaseStateRequest,
    UpdateKnowledgeBaseMetadataRequest,
    build_config_domain,
    knowledge_base_detail,
    knowledge_base_summary,
    retrieval_config_domain,
)
from app.modules.knowledge_bases.service import (
    KnowledgeBaseDeleteBlockedError,
    KnowledgeBaseNameConflictError,
    KnowledgeBaseNotFoundError,
    KnowledgeBaseRevisionConflictError,
    KnowledgeBaseService,
)
from app.modules.models.service import ModelNotSelectableError
from app.modules.tasks.domain import Operation
from app.modules.tasks.errors import IdempotencyKeyReusedError
from app.modules.tasks.schemas import OperationRef
from app.modules.tasks.service import TaskService


class KnowledgeBaseDependencies(Protocol):
    session_factory: sessionmaker[Session]
    knowledge_base_service: KnowledgeBaseService
    task_service: TaskService


router = APIRouter(
    prefix="/api/v1/knowledge-bases",
    tags=["知识库"],
    dependencies=[Depends(require_admin)],
)


def get_dependencies(request: Request) -> KnowledgeBaseDependencies:
    return cast(KnowledgeBaseDependencies, request.app.state.dependencies)


@router.post(
    "",
    response_model=CreateKnowledgeBaseResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="knowledgeBasesCreate",
    dependencies=[Depends(require_csrf)],
)
def create_knowledge_base(
    payload: CreateKnowledgeBaseRequest,
    administrator: Annotated[Administrator, Depends(require_admin)],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=8, max_length=128),
    ],
    dependencies: Annotated[KnowledgeBaseDependencies, Depends(get_dependencies)],
) -> CreateKnowledgeBaseResponse:
    try:
        with transaction(dependencies.session_factory) as session:
            created = dependencies.knowledge_base_service.create(
                session,
                name=payload.name,
                description=payload.description,
                source_ids=tuple(payload.parsed_source_version_ids),
                build_config=build_config_domain(payload.build_config),
                retrieval_config=retrieval_config_domain(payload.retrieval_config),
                idempotency_key=idempotency_key,
                administrator_id=administrator.id,
            )
            details = dependencies.knowledge_base_service.get_details(
                session, created.knowledge_base.id
            )
            operation = dependencies.task_service.get(session, created.operation_id)
            return CreateKnowledgeBaseResponse(
                knowledge_base=knowledge_base_detail(details),
                operation=_operation_ref(operation),
            )
    except IntegrityError as error:
        raise _name_conflict() from error
    except KnowledgeBaseNameConflictError as error:
        raise _name_conflict() from error
    except KnowledgeBaseConfigError as error:
        raise _config_error(error) from error
    except ModelNotSelectableError as error:
        raise AppError(
            code=error.args[0],
            message="所选模型不存在、类型不符或尚未验证通过",
            status_code=422,
        ) from error
    except IdempotencyKeyReusedError as error:
        raise AppError(
            code="IDEMPOTENCY_KEY_REUSED",
            message="同一幂等键不能用于不同请求",
            status_code=409,
        ) from error


@router.get("", response_model=KnowledgeBasePageView, operation_id="knowledgeBasesList")
def list_knowledge_bases(
    dependencies: Annotated[KnowledgeBaseDependencies, Depends(get_dependencies)],
    search: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 20,
) -> KnowledgeBasePageView:
    with transaction(dependencies.session_factory) as session:
        result = dependencies.knowledge_base_service.list(
            session,
            KnowledgeBaseListQuery(search=search, page=page, page_size=page_size),
        )
        items = [
            knowledge_base_summary(dependencies.knowledge_base_service.details(session, item))
            for item in result.items
        ]
        return KnowledgeBasePageView(
            items=items,
            total=result.total,
            page=result.page,
            page_size=result.page_size,
        )


@router.get(
    "/{knowledgeBaseId}",
    response_model=KnowledgeBaseDetailView,
    operation_id="knowledgeBasesGet",
)
def get_knowledge_base(
    knowledge_base_id: Annotated[UUID, Path(alias="knowledgeBaseId")],
    dependencies: Annotated[KnowledgeBaseDependencies, Depends(get_dependencies)],
) -> KnowledgeBaseDetailView:
    try:
        with transaction(dependencies.session_factory) as session:
            return knowledge_base_detail(
                dependencies.knowledge_base_service.get_details(session, knowledge_base_id)
            )
    except KnowledgeBaseNotFoundError as error:
        raise _not_found() from error


@router.patch(
    "/{knowledgeBaseId}/metadata",
    response_model=KnowledgeBaseDetailView,
    operation_id="knowledgeBasesUpdateMetadata",
    dependencies=[Depends(require_csrf)],
)
def update_knowledge_base_metadata(
    payload: UpdateKnowledgeBaseMetadataRequest,
    knowledge_base_id: Annotated[UUID, Path(alias="knowledgeBaseId")],
    dependencies: Annotated[KnowledgeBaseDependencies, Depends(get_dependencies)],
) -> KnowledgeBaseDetailView:
    try:
        with transaction(dependencies.session_factory) as session:
            knowledge_base = dependencies.knowledge_base_service.update_metadata(
                session,
                knowledge_base_id,
                expected_revision=payload.expected_revision,
                name=payload.name,
                description=payload.description,
            )
            return knowledge_base_detail(
                dependencies.knowledge_base_service.details(session, knowledge_base)
            )
    except IntegrityError as error:
        raise _name_conflict() from error
    except KnowledgeBaseNameConflictError as error:
        raise _name_conflict() from error
    except KnowledgeBaseConfigError as error:
        raise _config_error(error) from error
    except KnowledgeBaseNotFoundError as error:
        raise _not_found() from error
    except KnowledgeBaseRevisionConflictError as error:
        raise _revision_conflict() from error


@router.post(
    "/{knowledgeBaseId}:enable",
    response_model=KnowledgeBaseDetailView,
    operation_id="knowledgeBasesEnable",
    dependencies=[Depends(require_csrf)],
)
def enable_knowledge_base(
    payload: KnowledgeBaseStateRequest,
    knowledge_base_id: Annotated[UUID, Path(alias="knowledgeBaseId")],
    dependencies: Annotated[KnowledgeBaseDependencies, Depends(get_dependencies)],
) -> KnowledgeBaseDetailView:
    return _set_enabled(payload, knowledge_base_id, dependencies, enabled=True)


@router.post(
    "/{knowledgeBaseId}:disable",
    response_model=KnowledgeBaseDetailView,
    operation_id="knowledgeBasesDisable",
    dependencies=[Depends(require_csrf)],
)
def disable_knowledge_base(
    payload: KnowledgeBaseStateRequest,
    knowledge_base_id: Annotated[UUID, Path(alias="knowledgeBaseId")],
    dependencies: Annotated[KnowledgeBaseDependencies, Depends(get_dependencies)],
) -> KnowledgeBaseDetailView:
    return _set_enabled(payload, knowledge_base_id, dependencies, enabled=False)


@router.delete(
    "/{knowledgeBaseId}",
    response_model=OperationRef,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="knowledgeBasesDelete",
    dependencies=[Depends(require_csrf)],
)
def delete_knowledge_base(
    knowledge_base_id: Annotated[UUID, Path(alias="knowledgeBaseId")],
    expected_revision: Annotated[int, Query(alias="expectedRevision", ge=1)],
    administrator: Annotated[Administrator, Depends(require_admin)],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=8, max_length=128),
    ],
    dependencies: Annotated[KnowledgeBaseDependencies, Depends(get_dependencies)],
) -> OperationRef:
    try:
        with transaction(dependencies.session_factory) as session:
            operation = dependencies.knowledge_base_service.request_delete(
                session,
                knowledge_base_id,
                expected_revision=expected_revision,
                administrator_id=administrator.id,
                idempotency_key=idempotency_key,
            )
            return _operation_ref(operation)
    except KnowledgeBaseNotFoundError as error:
        raise _not_found() from error
    except KnowledgeBaseRevisionConflictError as error:
        raise _revision_conflict() from error
    except KnowledgeBaseDeleteBlockedError as error:
        raise AppError(
            code="KNOWLEDGE_BASE_DELETE_BLOCKED",
            message="知识库当前不能删除",
            status_code=409,
            details={"reason": error.reason},
        ) from error
    except IdempotencyKeyReusedError as error:
        raise AppError(
            code="IDEMPOTENCY_KEY_REUSED",
            message="同一幂等键不能用于不同请求",
            status_code=409,
        ) from error


def _set_enabled(
    payload: KnowledgeBaseStateRequest,
    knowledge_base_id: UUID,
    dependencies: KnowledgeBaseDependencies,
    *,
    enabled: bool,
) -> KnowledgeBaseDetailView:
    try:
        with transaction(dependencies.session_factory) as session:
            knowledge_base = dependencies.knowledge_base_service.set_enabled(
                session,
                knowledge_base_id,
                expected_revision=payload.expected_revision,
                enabled=enabled,
            )
            return knowledge_base_detail(
                dependencies.knowledge_base_service.details(session, knowledge_base)
            )
    except KnowledgeBaseNotFoundError as error:
        raise _not_found() from error
    except KnowledgeBaseRevisionConflictError as error:
        raise _revision_conflict() from error


def _operation_ref(operation: Operation) -> OperationRef:
    return OperationRef(
        operation_id=operation.id,
        status=operation.status,
        status_url=f"/api/v1/operations/{operation.id}",
        target_type=operation.target_type,
        target_id=operation.target_id,
    )


def _not_found() -> AppError:
    return AppError(
        code="KNOWLEDGE_BASE_NOT_FOUND",
        message="知识库不存在",
        status_code=404,
    )


def _name_conflict() -> AppError:
    return AppError(
        code="KNOWLEDGE_BASE_NAME_CONFLICT",
        message="知识库名称已存在",
        status_code=409,
    )


def _revision_conflict() -> AppError:
    return AppError(
        code="REVISION_CONFLICT",
        message="知识库已被其他操作修改, 请刷新后重试",
        status_code=409,
    )


def _config_error(error: KnowledgeBaseConfigError) -> AppError:
    return AppError(
        code=error.code,
        message="知识库配置校验失败",
        status_code=422,
        details={"fieldErrors": error.field_errors},
    )
