from collections.abc import Mapping
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session


class ModelAuditRepository(Protocol):
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
