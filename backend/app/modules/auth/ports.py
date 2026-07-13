from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session


@dataclass(frozen=True)
class RateLimitDecision:
    limited: bool
    retry_after_seconds: int = 0


class LoginRateLimiter(Protocol):
    def check(self, username: str, source_ip: str, now: datetime) -> RateLimitDecision: ...

    def record_failure(
        self,
        username: str,
        source_ip: str,
        now: datetime,
    ) -> RateLimitDecision: ...

    def clear(self, username: str, source_ip: str) -> None: ...


class AuditRepository(Protocol):
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
    ) -> None: ...
