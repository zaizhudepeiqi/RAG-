from collections.abc import Callable
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

BACKEND_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.integration
def test_upgrade_from_empty_database_reaches_head(
    database_url: str,
    run_alembic: Callable[[str, str], None],
) -> None:
    assert (make_url(database_url).database or "").endswith("_test")

    run_alembic("downgrade", "base")
    run_alembic("upgrade", "head")

    config = Config(BACKEND_ROOT / "alembic.ini")
    head_revision = ScriptDirectory.from_config(config).get_current_head()
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            current_revision = MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()

    assert current_revision == head_revision
