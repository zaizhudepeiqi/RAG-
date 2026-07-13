from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.modules.tasks.dispatcher import OutboxDispatcher
from app.modules.tasks.ports import (
    ClaimedOutboxEvent,
    TaskDispatchDefinition,
    TaskDispatchRegistry,
    TaskSchemaUnsupportedError,
)


class MemoryOutbox:
    def __init__(self, event: ClaimedOutboxEvent) -> None:
        self.event = event
        self.published = 0
        self.retry_delays: list[int] = []
        self.schema_failures = 0

    def claim_batch(self, _now: datetime, _limit: int) -> list[ClaimedOutboxEvent]:
        return [self.event]

    def mark_published(self, _event_id, _now: datetime) -> None:  # type: ignore[no-untyped-def]
        self.published += 1

    def mark_retry(self, _event_id, delay_seconds: int, _error: str, _now: datetime) -> None:  # type: ignore[no-untyped-def]
        self.retry_delays.append(delay_seconds)

    def mark_schema_failed(self, _event, _now: datetime) -> None:  # type: ignore[no-untyped-def]
        self.schema_failures += 1

    def reconcile(self, _now: datetime) -> int:
        return 0


class RecordingPublisher:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, str, dict[str, str]]] = []

    def publish(self, task_name: str, queue: str, kwargs: dict[str, str]) -> None:
        self.calls.append((task_name, queue, kwargs))
        if self.fail:
            raise ConnectionError("broker unavailable")


def event(*, attempt: int = 1, event_type: str = "source.parse") -> ClaimedOutboxEvent:
    return ClaimedOutboxEvent(
        id=uuid4(),
        operation_id=uuid4(),
        event_type=event_type,
        schema_version="1",
        publish_attempts=attempt,
    )


def registry() -> TaskDispatchRegistry:
    value = TaskDispatchRegistry()
    value.register(
        TaskDispatchDefinition(
            event_type="source.parse",
            schema_version="1",
            celery_task_name="app.tasks.parsing.source",
            queue="parsing",
        )
    )
    return value


def test_publish_failure_returns_outbox_to_pending_with_backoff() -> None:
    outbox = MemoryOutbox(event(attempt=3))
    dispatcher = OutboxDispatcher(outbox, RecordingPublisher(fail=True), registry())

    dispatcher.dispatch_once(datetime.now(UTC))

    assert outbox.published == 0
    assert outbox.retry_delays == [8]


def test_crash_after_publish_before_mark_allows_duplicate_delivery() -> None:
    outbox = MemoryOutbox(event())
    publisher = RecordingPublisher()
    dispatcher = OutboxDispatcher(outbox, publisher, registry())
    original_mark = outbox.mark_published

    def crash(_event_id, _now):  # type: ignore[no-untyped-def]
        raise RuntimeError("process crashed after publish")

    outbox.mark_published = crash  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        dispatcher.dispatch_once(datetime.now(UTC))
    outbox.mark_published = original_mark  # type: ignore[method-assign]
    dispatcher.dispatch_once(datetime.now(UTC))

    assert len(publisher.calls) == 2


def test_payload_contains_ids_and_revisions_but_no_secret_or_document_body() -> None:
    claimed = event()
    outbox = MemoryOutbox(claimed)
    publisher = RecordingPublisher()

    OutboxDispatcher(outbox, publisher, registry()).dispatch_once(datetime.now(UTC))

    assert publisher.calls[0][2] == {
        "operationId": str(claimed.operation_id),
        "eventType": claimed.event_type,
        "schemaVersion": claimed.schema_version,
    }


def test_unknown_schema_is_failed_without_dynamic_task_execution() -> None:
    outbox = MemoryOutbox(event(event_type="unknown"))
    dispatcher = OutboxDispatcher(outbox, RecordingPublisher(), registry())

    dispatcher.dispatch_once(datetime.now(UTC))

    assert outbox.schema_failures == 1


def test_registry_rejects_unknown_event_and_schema() -> None:
    with pytest.raises(TaskSchemaUnsupportedError):
        registry().resolve("source.parse", "999")
