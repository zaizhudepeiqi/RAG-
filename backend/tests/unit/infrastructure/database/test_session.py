import pytest
from app.core.config import Settings
from app.infrastructure.database.session import (
    create_engine_from_settings,
    create_session_factory,
    transaction,
)
from sqlalchemy import create_engine, text


def test_create_engine_uses_configured_database_url() -> None:
    settings = Settings.model_construct(database_url="sqlite+pysqlite:///:memory:")

    engine = create_engine_from_settings(settings)
    try:
        assert engine.url.drivername == "sqlite+pysqlite"
    finally:
        engine.dispose()


def test_transaction_commits_successful_work() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE records (value INTEGER NOT NULL)"))
        session_factory = create_session_factory(engine)

        with transaction(session_factory) as session:
            session.execute(text("INSERT INTO records (value) VALUES (1)"))

        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM records")) == 1
    finally:
        engine.dispose()


def test_transaction_rolls_back_failed_work() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE records (value INTEGER NOT NULL)"))
        session_factory = create_session_factory(engine)

        with pytest.raises(RuntimeError, match="stop"):
            with transaction(session_factory) as session:
                session.execute(text("INSERT INTO records (value) VALUES (1)"))
                raise RuntimeError("stop")

        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM records")) == 0
    finally:
        engine.dispose()
