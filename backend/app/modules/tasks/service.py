import hashlib
from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.tasks.domain import (
    TERMINAL_OPERATION_STATUSES,
    Operation,
    OperationEvent,
    OperationStatus,
    OutboxEvent,
    transition_operation,
)
from app.modules.tasks.errors import OperationNotFoundError, OperationNotRetryableError
from app.modules.tasks.repository import (
    OperationListQuery,
    OperationRepository,
    OutboxRepository,
    Page,
)


def normalize_business_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class RetryHandler(Protocol):
    def __call__(
        self,
        session: Session,
        previous: Operation,
        business_key: str,
        now: datetime,
    ) -> Operation: ...


class RetryHandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, RetryHandler] = {}

    def register(self, task_type: str, handler: RetryHandler) -> None:
        self._handlers[task_type] = handler

    def get(self, task_type: str) -> RetryHandler | None:
        return self._handlers.get(task_type)


class TaskService:
    def __init__(
        self,
        operations: OperationRepository,
        outbox: OutboxRepository,
        retry_handlers: RetryHandlerRegistry | None = None,
    ) -> None:
        self._operations = operations
        self._outbox = outbox
        self._retry_handlers = retry_handlers or RetryHandlerRegistry()

    def create_operation(
        self,
        session: Session,
        *,
        task_type: str,
        target_type: str,
        target_id: UUID,
        target_revision: int | None,
        business_key: str,
        event_type: str,
        payload: dict[str, object],
        now: datetime,
        expires_at: datetime,
        retry_of_operation_id: UUID | None = None,
    ) -> Operation:
        normalized_key = normalize_business_key(business_key)
        existing = self._operations.find_by_business_key(session, normalized_key)
        if existing is not None:
            return existing
        operation = Operation(
            id=uuid4(),
            task_type=task_type,
            target_type=target_type,
            target_id=target_id,
            target_revision=target_revision,
            status=OperationStatus.QUEUED,
            stage_code=None,
            stage_label=None,
            progress_current=0,
            progress_total=None,
            progress_unit=None,
            attempt=0,
            max_attempts=3,
            celery_task_id=None,
            business_idempotency_key=normalized_key,
            retry_of_operation_id=retry_of_operation_id,
            heartbeat_at=None,
            queued_at=now,
            started_at=None,
            finished_at=None,
            error_code=None,
            error_message=None,
            retryable=False,
            result_summary={},
            warning_count=0,
            created_at=now,
            expires_at=expires_at,
        )
        try:
            with session.begin_nested():
                self._operations.add(session, operation)
                self._outbox.add(
                    session,
                    OutboxEvent(
                        id=uuid4(),
                        operation_id=operation.id,
                        event_type=event_type,
                        schema_version="1",
                        payload=payload,
                        created_at=now,
                    ),
                )
                session.flush()
        except IntegrityError:
            concurrent = self._operations.find_by_business_key(session, normalized_key)
            if concurrent is None:
                raise
            return concurrent
        return operation

    def get(self, session: Session, operation_id: UUID) -> Operation:
        operation = self._operations.get(session, operation_id)
        if operation is None:
            raise OperationNotFoundError
        return operation

    def list(self, session: Session, query: OperationListQuery) -> Page[Operation]:
        return self._operations.list(session, query)

    def cancel(self, session: Session, operation_id: UUID, now: datetime) -> Operation:
        operation = self._operations.get(session, operation_id, for_update=True)
        if operation is None:
            raise OperationNotFoundError
        cancelled = transition_operation(operation, OperationEvent.CANCEL, now)
        self._operations.save(session, cancelled)
        return cancelled

    def retry(
        self,
        session: Session,
        operation_id: UUID,
        *,
        business_key: str,
        now: datetime,
    ) -> Operation:
        operation = self._operations.get(session, operation_id, for_update=True)
        if (
            operation is None
            or operation.status not in TERMINAL_OPERATION_STATUSES
            or not operation.retryable
        ):
            raise OperationNotRetryableError
        handler = self._retry_handlers.get(operation.task_type)
        if handler is None:
            raise OperationNotRetryableError
        return handler(session, operation, business_key, now)
