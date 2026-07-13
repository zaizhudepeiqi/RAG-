from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal, Protocol
from uuid import UUID


class TaskSchemaUnsupportedError(LookupError):
    code = "TASK_SCHEMA_UNSUPPORTED"


@dataclass(frozen=True)
class TaskDispatchDefinition:
    event_type: str
    schema_version: str
    celery_task_name: str
    queue: Literal["parsing", "indexing", "chat", "maintenance"]


class TaskDispatchRegistry:
    def __init__(self) -> None:
        self._definitions: dict[tuple[str, str], TaskDispatchDefinition] = {}

    def register(self, definition: TaskDispatchDefinition) -> None:
        key = (definition.event_type, definition.schema_version)
        if key in self._definitions:
            raise ValueError("task dispatch definition already registered")
        self._definitions[key] = definition

    def resolve(self, event_type: str, schema_version: str) -> TaskDispatchDefinition:
        try:
            return self._definitions[(event_type, schema_version)]
        except KeyError as error:
            raise TaskSchemaUnsupportedError from error


@dataclass(frozen=True)
class ClaimedOutboxEvent:
    id: UUID
    operation_id: UUID
    event_type: str
    schema_version: str
    publish_attempts: int


class OutboxDispatchStore(Protocol):
    def claim_batch(self, now: datetime, limit: int) -> list[ClaimedOutboxEvent]: ...
    def mark_published(self, event_id: UUID, now: datetime) -> None: ...
    def mark_retry(
        self,
        event_id: UUID,
        delay_seconds: int,
        error: str,
        now: datetime,
    ) -> None: ...
    def mark_schema_failed(self, event: ClaimedOutboxEvent, now: datetime) -> None: ...
    def reconcile(self, now: datetime) -> int: ...


class TaskPublisher(Protocol):
    def publish(self, task_name: str, queue: str, kwargs: dict[str, str]) -> None: ...


class ClaimKind(StrEnum):
    CLAIMED = "claimed"
    ALREADY_RUNNING = "already_running"
    TERMINAL = "terminal"


@dataclass(frozen=True)
class OperationClaim:
    kind: ClaimKind
    operation_id: UUID


class OperationExecutionStore(Protocol):
    def claim(self, operation_id: UUID, expected_task_type: str) -> OperationClaim: ...
    def complete(self, operation_id: UUID, result: dict[str, object]) -> None: ...
    def fail(self, operation_id: UUID, code: str, *, retryable: bool) -> None: ...


class OperationHandler(Protocol):
    def run(self, operation_id: UUID) -> dict[str, object]: ...


class WorkerDependencies(Protocol):
    operations: OperationExecutionStore
