import ipaddress
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.infrastructure.database.models.auth import AuditLogModel


class SqlAlchemyAuditRepository:
    def record(
        self,
        session: Session,
        *,
        occurred_at: datetime,
        actor_id: UUID | None,
        event_code: str,
        result_status: str,
        trace_id: UUID | None,
        source_ip: str | None,
        user_agent: str | None,
        error_code: str | None = None,
    ) -> None:
        session.add(
            AuditLogModel(
                id=uuid4(),
                occurred_at=occurred_at,
                actor_type="administrator",
                actor_id=actor_id,
                event_code=event_code,
                target_type="administrator",
                target_id=actor_id,
                trace_id=trace_id,
                source_ip=self._valid_ip(source_ip),
                user_agent=user_agent,
                change_summary={},
                result_status=result_status,
                error_code=error_code,
            )
        )

    @staticmethod
    def _valid_ip(source_ip: str | None) -> str | None:
        if source_ip is None:
            return None
        try:
            return ipaddress.ip_address(source_ip).compressed
        except ValueError:
            return None
