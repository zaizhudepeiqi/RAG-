from collections.abc import Mapping


class TaskError(Exception):
    code: str
    details: dict[str, object]

    def __init__(self, code: str, details: Mapping[str, object] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.details = dict(details or {})


class InvalidStateTransitionError(TaskError):
    pass


class IdempotencyKeyReusedError(TaskError):
    def __init__(self) -> None:
        super().__init__("IDEMPOTENCY_KEY_REUSED")


class OperationNotFoundError(TaskError):
    def __init__(self) -> None:
        super().__init__("OPERATION_NOT_FOUND")


class OperationNotRetryableError(TaskError):
    def __init__(self) -> None:
        super().__init__("OPERATION_NOT_RETRYABLE")
