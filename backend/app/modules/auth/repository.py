from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.auth.domain import Administrator


class AdministratorRepository(Protocol):
    def count(self, session: Session) -> int: ...

    def find_by_username(self, session: Session, username: str) -> Administrator | None: ...

    def get_by_id(
        self,
        session: Session,
        administrator_id: UUID,
    ) -> Administrator | None: ...

    def add(self, session: Session, administrator: Administrator) -> None: ...

    def save(self, session: Session, administrator: Administrator) -> None: ...
