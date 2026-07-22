from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.parsing.settings_domain import MinerUSettings


class MinerUSettingsRepository(Protocol):
    def get_or_create(
        self,
        session: Session,
        default: MinerUSettings,
    ) -> MinerUSettings: ...

    def get_for_update(
        self,
        session: Session,
        settings_id: UUID,
    ) -> MinerUSettings | None: ...

    def save(self, session: Session, settings: MinerUSettings) -> None: ...
