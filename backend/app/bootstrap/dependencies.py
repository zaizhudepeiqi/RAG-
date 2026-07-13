from dataclasses import dataclass
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from redis import Redis
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.infrastructure.database.repositories.audit import SqlAlchemyAuditRepository
from app.infrastructure.database.repositories.auth import SqlAlchemyAdministratorRepository
from app.infrastructure.database.session import create_engine_from_settings, create_session_factory
from app.infrastructure.redis.login_rate_limit import RedisLoginRateLimiter
from app.modules.auth.service import AuthService

BACKEND_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class ApplicationDependencies:
    engine: Engine
    session_factory: sessionmaker[Session]
    redis_client: Redis
    auth_service: AuthService

    def assert_database_at_head(self) -> None:
        config = Config(BACKEND_ROOT / "alembic.ini")
        expected = ScriptDirectory.from_config(config).get_current_head()
        with self.engine.connect() as connection:
            current = MigrationContext.configure(connection).get_current_revision()
        if current != expected:
            raise RuntimeError(
                f"database migration mismatch: expected {expected!r}, found {current!r}"
            )

    def close(self) -> None:
        self.redis_client.close()
        self.engine.dispose()


def build_application_dependencies(settings: Settings) -> ApplicationDependencies:
    engine = create_engine_from_settings(settings)
    session_factory = create_session_factory(engine)
    redis_client = Redis.from_url(settings.redis_url)
    auth_service = AuthService(
        session_factory=session_factory,
        administrators=SqlAlchemyAdministratorRepository(),
        audits=SqlAlchemyAuditRepository(),
        rate_limiter=RedisLoginRateLimiter(redis_client),
        initial_username=settings.initial_admin_username,
        initial_secret=settings.initial_admin_password.get_secret_value(),
        signing_key=settings.jwt_signing_key_bytes,
        access_token_expire_minutes=settings.access_token_expire_minutes,
    )
    return ApplicationDependencies(
        engine=engine,
        session_factory=session_factory,
        redis_client=redis_client,
        auth_service=auth_service,
    )
