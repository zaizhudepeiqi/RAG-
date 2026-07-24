from datetime import datetime
from typing import Literal
from uuid import UUID

from app.core.schemas import ApiModel
from app.modules.tasks.domain import (
    NON_CANCELLABLE_TASK_TYPES,
    TERMINAL_OPERATION_STATUSES,
    Operation,
    OperationStatus,
)


class OperationRef(ApiModel):
    operation_id: UUID
    status: OperationStatus
    status_url: str
    target_type: str
    target_id: UUID


class OperationDetail(OperationRef):
    task_type: str
    stage_code: str | None = None
    stage_label: str | None = None
    progress_current: int
    progress_total: int | None = None
    progress_unit: str | None = None
    attempt: int
    max_attempts: int
    warning_count: int
    error_code: str | None = None
    error_message: str | None = None
    retryable: bool
    result_summary: dict[str, object]
    queued_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    heartbeat_at: datetime | None = None
    allowed_actions: list[Literal["cancel", "retry"]]


class OperationPage(ApiModel):
    items: list[OperationDetail]
    total: int
    page: int
    page_size: int


def operation_detail(operation: Operation) -> OperationDetail:
    actions: list[Literal["cancel", "retry"]] = []
    if (
        operation.status is OperationStatus.QUEUED
        and operation.task_type not in NON_CANCELLABLE_TASK_TYPES
    ):
        actions.append("cancel")
    if operation.status in TERMINAL_OPERATION_STATUSES and operation.retryable:
        actions.append("retry")
    return OperationDetail(
        operation_id=operation.id,
        status=operation.status,
        status_url=f"/api/v1/operations/{operation.id}",
        target_type=operation.target_type,
        target_id=operation.target_id,
        task_type=operation.task_type,
        stage_code=operation.stage_code,
        stage_label=operation.stage_label,
        progress_current=operation.progress_current,
        progress_total=operation.progress_total,
        progress_unit=operation.progress_unit,
        attempt=operation.attempt,
        max_attempts=operation.max_attempts,
        warning_count=operation.warning_count,
        error_code=operation.error_code,
        error_message=operation.error_message,
        retryable=operation.retryable,
        result_summary=operation.result_summary,
        queued_at=operation.queued_at,
        started_at=operation.started_at,
        finished_at=operation.finished_at,
        heartbeat_at=operation.heartbeat_at,
        allowed_actions=actions,
    )
