from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.tasks.domain import AdminIdempotencyRecord, Operation, OutboxEvent


@dataclass(frozen=True)
class Page[T]:
    items: list[T]
    total: int
    page: int
    page_size: int


@dataclass(frozen=True)
class OperationListQuery:
    status: tuple[str, ...] = ()
    task_type: str | None = None
    target_type: str | None = None
    target_id: UUID | None = None
    page: int = 1
    page_size: int = 20
    sort: str = "-queued_at"


class OperationRepository(Protocol):
    def add(self, session: Session, operation: Operation) -> None: ...
    def get(
        self, session: Session, operation_id: UUID, *, for_update: bool = False
    ) -> Operation | None: ...
    def find_by_business_key(self, session: Session, key: str) -> Operation | None: ...
    def list(self, session: Session, query: OperationListQuery) -> Page[Operation]: ...
    def save(self, session: Session, operation: Operation) -> None: ...


class OutboxRepository(Protocol):
    def add(self, session: Session, event: OutboxEvent) -> None: ...


class AdminIdempotencyRepository(Protocol):
    def find(
        self,
        session: Session,
        administrator_id: UUID,
        endpoint_code: str,
        key_hash: str,
    ) -> AdminIdempotencyRecord | None: ...
    def add(self, session: Session, record: AdminIdempotencyRecord) -> None: ...
