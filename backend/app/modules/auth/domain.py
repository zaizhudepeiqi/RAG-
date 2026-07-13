from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class Administrator:
    id: UUID
    username: str
    password_hash: str
    first_login_required: bool
    auth_version: int
    revision: int
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime

    def record_login(self, now: datetime) -> None:
        self.last_login_at = now
        self.updated_at = now
        self.revision += 1

    def invalidate_sessions(self, now: datetime) -> None:
        self.auth_version += 1
        self.revision += 1
        self.updated_at = now

    def change_password(self, password_hash: str, now: datetime) -> None:
        self.password_hash = password_hash
        self.first_login_required = False
        self.invalidate_sessions(now)
