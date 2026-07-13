from contextvars import ContextVar
from uuid import UUID, uuid4

trace_id_context: ContextVar[UUID | None] = ContextVar("trace_id", default=None)


def new_uuid() -> UUID:
    return uuid4()


def parse_or_create_trace_id(value: str | None) -> UUID:
    if value is not None:
        try:
            return UUID(value)
        except (ValueError, AttributeError):
            pass
    return new_uuid()
