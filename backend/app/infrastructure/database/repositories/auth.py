from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.infrastructure.database.models.auth import AdministratorModel
from app.modules.auth.domain import Administrator


class SqlAlchemyAdministratorRepository:
    def count(self, session: Session) -> int:
        session.execute(text("LOCK TABLE administrators IN SHARE ROW EXCLUSIVE MODE"))
        return session.scalar(select(func.count()).select_from(AdministratorModel)) or 0

    def find_by_username(self, session: Session, username: str) -> Administrator | None:
        model = session.scalar(
            select(AdministratorModel).where(
                func.lower(AdministratorModel.username) == username.casefold()
            )
        )
        return self._to_domain(model) if model is not None else None

    def get_by_id(self, session: Session, administrator_id: UUID) -> Administrator | None:
        model = session.get(AdministratorModel, administrator_id)
        return self._to_domain(model) if model is not None else None

    def add(self, session: Session, administrator: Administrator) -> None:
        session.add(
            AdministratorModel(
                id=administrator.id,
                username=administrator.username,
                password_hash=administrator.password_hash,
                first_login_required=administrator.first_login_required,
                auth_version=administrator.auth_version,
                revision=administrator.revision,
                last_login_at=administrator.last_login_at,
                created_at=administrator.created_at,
                updated_at=administrator.updated_at,
            )
        )

    def save(self, session: Session, administrator: Administrator) -> None:
        model = session.get(AdministratorModel, administrator.id)
        if model is None:
            raise LookupError("administrator no longer exists")
        model.username = administrator.username
        model.password_hash = administrator.password_hash
        model.first_login_required = administrator.first_login_required
        model.auth_version = administrator.auth_version
        model.revision = administrator.revision
        model.last_login_at = administrator.last_login_at
        model.updated_at = administrator.updated_at

    @staticmethod
    def _to_domain(model: AdministratorModel) -> Administrator:
        return Administrator(
            id=model.id,
            username=model.username,
            password_hash=model.password_hash,
            first_login_required=model.first_login_required,
            auth_version=model.auth_version,
            revision=model.revision,
            last_login_at=model.last_login_at,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
