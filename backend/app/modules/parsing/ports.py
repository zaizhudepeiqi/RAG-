from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import BinaryIO, Protocol
from uuid import UUID

from sqlalchemy.orm import Session


@dataclass(frozen=True)
class StoredBlob:
    storage_key: str
    sha256: str
    size_bytes: int


class SourceStorage(Protocol):
    def store_blob(self, source: BinaryIO, *, max_bytes: int) -> StoredBlob: ...

    def open_binary(self, storage_key: str) -> BinaryIO: ...

    def delete(self, storage_key: str) -> None: ...

    def exists(self, storage_key: str) -> bool: ...


class DataSourceAuditRepository(Protocol):
    def record(
        self,
        session: Session,
        *,
        occurred_at: datetime,
        actor_id: UUID,
        event_code: str,
        target_id: UUID,
        target_name: str,
        change_summary: Mapping[str, object],
        trace_id: UUID | None,
        source_ip: str | None,
        user_agent: str | None,
    ) -> None: ...
