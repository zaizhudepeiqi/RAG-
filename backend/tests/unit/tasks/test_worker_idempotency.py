from dataclasses import dataclass
from uuid import uuid4

import pytest
from app.modules.tasks.ports import ClaimKind, OperationClaim
from app.modules.tasks.worker import execute_operation


class Operations:
    def __init__(self, kind: ClaimKind) -> None:
        self.kind = kind
        self.completed = 0
        self.failed = 0

    def claim(self, operation_id, expected_task_type):  # type: ignore[no-untyped-def]
        return OperationClaim(kind=self.kind, operation_id=operation_id)

    def complete(self, operation_id, result):  # type: ignore[no-untyped-def]
        self.completed += 1

    def fail(self, operation_id, code, *, retryable):  # type: ignore[no-untyped-def]
        self.failed += 1


class Handler:
    def __init__(self) -> None:
        self.side_effects = 0

    def run(self, _operation_id):  # type: ignore[no-untyped-def]
        self.side_effects += 1
        return {"ok": True}


class FailingHandler:
    def run(self, _operation_id):  # type: ignore[no-untyped-def]
        raise RuntimeError("provider payload must not escape the worker")


@dataclass
class Dependencies:
    operations: Operations


def test_duplicate_delivery_of_running_or_terminal_operation_has_no_side_effect() -> None:
    for kind in (ClaimKind.ALREADY_RUNNING, ClaimKind.TERMINAL):
        operations = Operations(kind)
        handler = Handler()

        execute_operation(uuid4(), "test_task", handler, Dependencies(operations))

        assert handler.side_effects == 0
        assert operations.completed == 0


def test_worker_claim_is_atomic_for_same_operation() -> None:
    operations = Operations(ClaimKind.CLAIMED)
    handler = Handler()

    execute_operation(uuid4(), "test_task", handler, Dependencies(operations))

    assert handler.side_effects == 1
    assert operations.completed == 1


def test_unexpected_worker_failure_does_not_leave_operation_running() -> None:
    operations = Operations(ClaimKind.CLAIMED)

    with pytest.raises(RuntimeError):
        execute_operation(
            uuid4(),
            "test_task",
            FailingHandler(),
            Dependencies(operations),
        )

    assert operations.failed == 1
    assert operations.completed == 0
