import os
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parent


@pytest.fixture(scope="session")
def database_url() -> str:
    value = os.getenv("RAG_TEST_DATABASE_URL")
    if value is None:
        pytest.fail("RAG_TEST_DATABASE_URL is required for database integration tests")

    database_name = make_url(value).database or ""
    if not database_name.endswith("_test"):
        pytest.fail("RAG_TEST_DATABASE_URL must point to a database ending in '_test'")
    return value


@pytest.fixture(scope="session")
def run_alembic(database_url: str) -> Callable[[str, str], None]:
    def run(command: str, revision: str) -> None:
        environment = os.environ.copy()
        environment["DATABASE_URL"] = database_url
        subprocess.run(  # noqa: S603 - executable and arguments are repository-controlled.
            [
                sys.executable,
                "-m",
                "alembic",
                "-c",
                str(BACKEND_ROOT / "alembic.ini"),
                command,
                revision,
            ],
            cwd=REPOSITORY_ROOT,
            env=environment,
            check=True,
        )

    return run


@pytest.fixture(scope="session")
def migrated_database_url(
    database_url: str,
    run_alembic: Callable[[str, str], None],
) -> str:
    run_alembic("upgrade", "head")
    return database_url


@pytest.fixture(scope="session")
def database_engine(migrated_database_url: str) -> Iterator[Engine]:
    engine = create_engine(migrated_database_url)
    try:
        yield engine
    finally:
        engine.dispose()
