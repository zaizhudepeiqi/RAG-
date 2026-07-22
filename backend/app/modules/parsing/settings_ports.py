from collections.abc import Mapping
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session


class MinerUSettingsAuditRepository(Protocol):
    def record(
        self,
        session: Session,
        *,
        occurred_at: datetime,
        actor_id: UUID,
        target_id: UUID,
        change_summary: Mapping[str, object],
        trace_id: UUID | None,
        source_ip: str | None,
        user_agent: str | None,
    ) -> None: ...
