from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from app.modules.tasks.domain import (
    Operation,
    OperationEvent,
    OperationStatus,
    transition_operation,
)
from app.modules.tasks.errors import InvalidStateTransitionError
from app.modules.tasks.service import RetryHandlerRegistry, TaskService
from sqlalchemy.orm import Session

NOW = datetime(2026, 7, 14, 8, 0, tzinfo=UTC)


def operation(status: OperationStatus) -> Operation:
    return Operation(
        id=uuid4(),
        task_type="test_task",
        target_type="test_target",
        target_id=uuid4(),
        target_revision=None,
        status=status,
        stage_code=None,
        stage_label=None,
        progress_current=0,
        progress_total=None,
        progress_unit=None,
        attempt=0,
        max_attempts=3,
        celery_task_id=None,
        business_idempotency_key="a" * 64,
        retry_of_operation_id=None,
        heartbeat_at=None,
        queued_at=NOW - timedelta(minutes=10),
        started_at=None,
        finished_at=None,
        error_code=None,
        error_message=None,
        retryable=False,
        result_summary={},
        warning_count=0,
        created_at=NOW - timedelta(minutes=10),
        expires_at=NOW + timedelta(days=90),
    )


@pytest.mark.parametrize(
    ("current", "event", "expected"),
    [
        (OperationStatus.QUEUED, OperationEvent.WORKER_CLAIM, OperationStatus.RUNNING),
        (OperationStatus.QUEUED, OperationEvent.CANCEL, OperationStatus.CANCELLED),
        (OperationStatus.RUNNING, OperationEvent.COMPLETE, OperationStatus.SUCCEEDED),
        (
            OperationStatus.RUNNING,
            OperationEvent.COMPLETE_PARTIAL,
            OperationStatus.PARTIAL_SUCCEEDED,
        ),
        (OperationStatus.RUNNING, OperationEvent.FAIL, OperationStatus.FAILED),
    ],
)
def test_allowed_operation_transition(
    current: OperationStatus,
    event: OperationEvent,
    expected: OperationStatus,
) -> None:
    result = transition_operation(operation(current), event, NOW)

    assert result.status is expected


def test_terminal_duplicate_delivery_is_noop() -> None:
    current = operation(OperationStatus.SUCCEEDED)

    result = transition_operation(current, OperationEvent.DUPLICATE_DELIVERY, NOW)

    assert result == current


def test_running_operation_cannot_be_cancelled() -> None:
    with pytest.raises(InvalidStateTransitionError) as error:
        transition_operation(operation(OperationStatus.RUNNING), OperationEvent.CANCEL, NOW)

    assert error.value.code == "INVALID_STATE_TRANSITION"
    assert error.value.details["current"] == "running"
    assert error.value.details["event"] == "cancel"
    assert "cancel" not in error.value.details["allowedEvents"]


def test_stalled_is_derived_without_changing_status() -> None:
    current = operation(OperationStatus.RUNNING)
    current.heartbeat_at = NOW - timedelta(minutes=6)

    assert current.is_stalled(NOW, timedelta(minutes=5)) is True
    assert current.status is OperationStatus.RUNNING


def test_retry_creates_new_operation_and_never_requeues_old_one() -> None:
    previous = operation(OperationStatus.FAILED)
    previous.retryable = True

    class Operations:
        def get(
            self,
            _session: Session,
            _operation_id: UUID,
            *,
            for_update: bool = False,
        ) -> Operation:
            assert for_update is True
            return previous

    class Outbox:
        pass

    registry = RetryHandlerRegistry()

    def handler(
        _session: Session,
        old: Operation,
        business_key: str,
        now: datetime,
    ) -> Operation:
        return replace(
            old,
            id=uuid4(),
            status=OperationStatus.QUEUED,
            business_idempotency_key=business_key,
            retry_of_operation_id=old.id,
            queued_at=now,
            finished_at=None,
        )

    registry.register(previous.task_type, handler)
    service = TaskService(Operations(), Outbox(), registry)  # type: ignore[arg-type]
    session = Session()
    try:
        retried = service.retry(session, previous.id, business_key="new-key", now=NOW)
    finally:
        session.close()

    assert retried.id != previous.id
    assert retried.retry_of_operation_id == previous.id
    assert retried.status is OperationStatus.QUEUED
    assert previous.status is OperationStatus.FAILED
