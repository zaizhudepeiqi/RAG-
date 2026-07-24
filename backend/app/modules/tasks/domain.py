from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from app.modules.tasks.errors import InvalidStateTransitionError


class OperationStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL_SUCCEEDED = "partial_succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class OperationEvent(StrEnum):
    WORKER_CLAIM = "worker_claim"
    CANCEL = "cancel"
    COMPLETE = "complete"
    COMPLETE_PARTIAL = "complete_partial"
    FAIL = "fail"
    DUPLICATE_DELIVERY = "duplicate_delivery"


TERMINAL_OPERATION_STATUSES = frozenset(
    {
        OperationStatus.SUCCEEDED,
        OperationStatus.PARTIAL_SUCCEEDED,
        OperationStatus.FAILED,
        OperationStatus.CANCELLED,
    }
)
NON_CANCELLABLE_TASK_TYPES = frozenset({"parsing_cleanup"})

ALLOWED_EVENTS: dict[OperationStatus, frozenset[OperationEvent]] = {
    OperationStatus.QUEUED: frozenset({OperationEvent.WORKER_CLAIM, OperationEvent.CANCEL}),
    OperationStatus.RUNNING: frozenset(
        {OperationEvent.COMPLETE, OperationEvent.COMPLETE_PARTIAL, OperationEvent.FAIL}
    ),
    OperationStatus.SUCCEEDED: frozenset({OperationEvent.DUPLICATE_DELIVERY}),
    OperationStatus.PARTIAL_SUCCEEDED: frozenset({OperationEvent.DUPLICATE_DELIVERY}),
    OperationStatus.FAILED: frozenset({OperationEvent.DUPLICATE_DELIVERY}),
    OperationStatus.CANCELLED: frozenset({OperationEvent.DUPLICATE_DELIVERY}),
}


@dataclass
class Operation:
    id: UUID
    task_type: str
    target_type: str
    target_id: UUID
    target_revision: int | None
    status: OperationStatus
    stage_code: str | None
    stage_label: str | None
    progress_current: int
    progress_total: int | None
    progress_unit: str | None
    attempt: int
    max_attempts: int
    celery_task_id: str | None
    business_idempotency_key: str
    retry_of_operation_id: UUID | None
    heartbeat_at: datetime | None
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    error_message: str | None
    retryable: bool
    result_summary: dict[str, object]
    warning_count: int
    created_at: datetime
    expires_at: datetime

    def is_stalled(self, now: datetime, threshold: timedelta) -> bool:
        if self.status is not OperationStatus.RUNNING:
            return False
        reference = self.heartbeat_at or self.started_at or self.queued_at
        return now - reference > threshold


@dataclass(frozen=True)
class OutboxEvent:
    id: UUID
    operation_id: UUID
    event_type: str
    schema_version: str
    payload: dict[str, object]
    created_at: datetime


@dataclass(frozen=True)
class AdminIdempotencyRecord:
    id: UUID
    administrator_id: UUID
    endpoint_code: str
    idempotency_key_hash: str
    request_hash: str
    operation_id: UUID | None
    response_status: int | None
    response_body: dict[str, object] | None
    expires_at: datetime
    created_at: datetime


def transition_operation(
    operation: Operation,
    event: OperationEvent,
    now: datetime,
) -> Operation:
    allowed = ALLOWED_EVENTS[operation.status]
    if event not in allowed:
        raise InvalidStateTransitionError(
            "INVALID_STATE_TRANSITION",
            {
                "current": operation.status.value,
                "event": event.value,
                "allowedEvents": sorted(item.value for item in allowed),
            },
        )
    if event is OperationEvent.DUPLICATE_DELIVERY:
        return operation
    if event is OperationEvent.WORKER_CLAIM:
        return replace(
            operation,
            status=OperationStatus.RUNNING,
            attempt=operation.attempt + 1,
            started_at=now,
            heartbeat_at=now,
        )
    status_by_event = {
        OperationEvent.CANCEL: OperationStatus.CANCELLED,
        OperationEvent.COMPLETE: OperationStatus.SUCCEEDED,
        OperationEvent.COMPLETE_PARTIAL: OperationStatus.PARTIAL_SUCCEEDED,
        OperationEvent.FAIL: OperationStatus.FAILED,
    }
    return replace(operation, status=status_by_event[event], finished_at=now)
