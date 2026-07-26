from uuid import UUID

from app.modules.tasks.ports import (
    ClaimKind,
    OperationHandler,
    WorkerDependencies,
)


class RetryableTaskError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class NonRetryableTaskError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def execute_operation(
    operation_id: UUID,
    expected_task_type: str,
    handler: OperationHandler,
    dependencies: WorkerDependencies,
) -> None:
    claim = dependencies.operations.claim(operation_id, expected_task_type)
    if claim.kind in {ClaimKind.ALREADY_RUNNING, ClaimKind.TERMINAL}:
        return
    try:
        result = handler.run(claim.operation_id)
    except RetryableTaskError as error:
        dependencies.operations.fail(operation_id, error.code, retryable=True)
        raise
    except NonRetryableTaskError as error:
        dependencies.operations.fail(operation_id, error.code, retryable=False)
        return
    except Exception:
        dependencies.operations.fail(operation_id, "UNEXPECTED_TASK_ERROR", retryable=True)
        raise
    dependencies.operations.complete(operation_id, result)
