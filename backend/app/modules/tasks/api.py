from datetime import UTC, datetime
from enum import IntEnum
from typing import Annotated, Literal, Protocol, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path, Query, Request
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import AppError
from app.infrastructure.database.session import transaction
from app.modules.auth.dependencies import require_admin, require_csrf
from app.modules.auth.domain import Administrator
from app.modules.tasks.errors import (
    IdempotencyKeyReusedError,
    InvalidStateTransitionError,
    OperationNotFoundError,
    OperationNotRetryableError,
)
from app.modules.tasks.idempotency import AdminIdempotencyService
from app.modules.tasks.repository import OperationListQuery
from app.modules.tasks.schemas import OperationDetail, OperationPage, operation_detail
from app.modules.tasks.service import TaskService


class TaskDependencies(Protocol):
    session_factory: sessionmaker[Session]
    task_service: TaskService
    admin_idempotency_service: AdminIdempotencyService


class OperationPageSize(IntEnum):
    DEFAULT = 20
    MEDIUM = 50
    LARGE = 100


router = APIRouter(
    prefix="/api/v1/operations",
    tags=["异步任务"],
    dependencies=[Depends(require_admin)],
)


def get_task_dependencies(request: Request) -> TaskDependencies:
    return cast(TaskDependencies, request.app.state.dependencies)


@router.get("", response_model=OperationPage, operation_id="operationsList")
def list_operations(
    dependencies: Annotated[TaskDependencies, Depends(get_task_dependencies)],
    status: str | None = None,
    task_type: Annotated[str | None, Query(alias="taskType")] = None,
    target_type: Annotated[str | None, Query(alias="targetType")] = None,
    target_id: Annotated[UUID | None, Query(alias="targetId")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[OperationPageSize, Query(alias="pageSize")] = OperationPageSize.DEFAULT,
    sort: Literal["queued_at", "-queued_at", "created_at", "-created_at"] = "-queued_at",
) -> OperationPage:
    query = OperationListQuery(
        status=tuple(item for item in (status or "").split(",") if item),
        task_type=task_type,
        target_type=target_type,
        target_id=target_id,
        page=page,
        page_size=page_size,
        sort=sort,
    )
    with transaction(dependencies.session_factory) as session:
        result = dependencies.task_service.list(session, query)
    return OperationPage(
        items=[operation_detail(item) for item in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.get("/{operationId}", response_model=OperationDetail, operation_id="operationsGet")
def get_operation(
    operation_id: Annotated[UUID, Path(alias="operationId")],
    dependencies: Annotated[TaskDependencies, Depends(get_task_dependencies)],
) -> OperationDetail:
    try:
        with transaction(dependencies.session_factory) as session:
            operation = dependencies.task_service.get(session, operation_id)
    except OperationNotFoundError as error:
        raise AppError(code="OPERATION_NOT_FOUND", message="任务不存在", status_code=404) from error
    return operation_detail(operation)


@router.post(
    "/{operationId}:cancel",
    response_model=OperationDetail,
    operation_id="operationsCancel",
    dependencies=[Depends(require_csrf)],
)
def cancel_operation(
    operation_id: Annotated[UUID, Path(alias="operationId")],
    dependencies: Annotated[TaskDependencies, Depends(get_task_dependencies)],
) -> OperationDetail:
    try:
        with transaction(dependencies.session_factory) as session:
            operation = dependencies.task_service.cancel(session, operation_id, datetime.now(UTC))
    except OperationNotFoundError as error:
        raise AppError(code="OPERATION_NOT_FOUND", message="任务不存在", status_code=404) from error
    except InvalidStateTransitionError as error:
        raise AppError(
            code="OPERATION_NOT_CANCELLABLE",
            message="当前任务状态不可取消",
            status_code=409,
            details=error.details,
        ) from error
    return operation_detail(operation)


@router.post(
    "/{operationId}:retry",
    response_model=OperationDetail,
    operation_id="operationsRetry",
    dependencies=[Depends(require_csrf)],
)
def retry_operation(
    operation_id: Annotated[UUID, Path(alias="operationId")],
    dependencies: Annotated[TaskDependencies, Depends(get_task_dependencies)],
    administrator: Annotated[Administrator, Depends(require_admin)],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=8, max_length=128),
    ],
) -> OperationDetail:
    try:
        with transaction(dependencies.session_factory) as session:
            operation = dependencies.task_service.retry(
                session,
                operation_id,
                business_key=(f"admin:{administrator.id}:operation.retry:{idempotency_key}"),
                now=datetime.now(UTC),
            )
            dependencies.admin_idempotency_service.reserve(
                session,
                administrator_id=administrator.id,
                endpoint_code="operation.retry",
                idempotency_key=idempotency_key,
                request_body={"operationId": str(operation_id)},
                operation_id=operation.id,
                now=datetime.now(UTC),
            )
    except OperationNotRetryableError as error:
        raise AppError(
            code="OPERATION_NOT_RETRYABLE",
            message="当前任务不支持重试",
            status_code=409,
        ) from error
    except IdempotencyKeyReusedError as error:
        raise AppError(
            code="IDEMPOTENCY_KEY_REUSED",
            message="幂等键已用于不同请求",
            status_code=409,
        ) from error
    return operation_detail(operation)
