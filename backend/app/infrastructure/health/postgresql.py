from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.modules.observability.ports import DependencyCode, DependencyStatus


class PostgreSQLHealthProbe:
    code: DependencyCode = "postgresql"
    required_for_readiness = True

    def __init__(self, engine: Engine, alembic_ini: Path) -> None:
        self._engine = engine
        self._alembic_ini = alembic_ini

    def check(self) -> DependencyStatus:
        try:
            with self._engine.connect() as connection:
                connection.execute(text("SELECT 1"))
                current = MigrationContext.configure(connection).get_current_revision()
            expected = ScriptDirectory.from_config(Config(self._alembic_ini)).get_current_head()
            if current != expected:
                return DependencyStatus(self.code, "unhealthy", "migration is not at head")
            return DependencyStatus(self.code, "healthy", "available")
        except SQLAlchemyError:
            return DependencyStatus(self.code, "unhealthy", "database unavailable")
