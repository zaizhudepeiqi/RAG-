from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from app.infrastructure.database.repositories.parsing import (
    SqlAlchemyDataSourceRepository,
    SqlAlchemyParseTaskStore,
)
from app.infrastructure.database.repositories.tasks import (
    SqlAlchemyOperationExecutionStore,
    SqlAlchemyOperationRepository,
    SqlAlchemyOutboxRepository,
)
from app.infrastructure.database.session import create_session_factory, transaction
from app.infrastructure.parsers.builtin_text import BuiltinTextParser
from app.infrastructure.parsers.registry import ParserRegistry
from app.infrastructure.storage.local import LocalStorageAdapter
from app.modules.parsing.service import DataSourceService
from app.modules.parsing.settings_domain import DEFAULT_PARSE_CONFIG
from app.modules.parsing.tasks import SOURCE_PARSE_TASK, SourceParseHandler
from app.modules.tasks.service import TaskService
from app.modules.tasks.worker import execute_operation
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration


class NoopAuditRepository:
    def record(self, _session: Session, **_kwargs: object) -> None:
        pass


class WorkerDependencies:
    def __init__(self, operations: SqlAlchemyOperationExecutionStore) -> None:
        self.operations = operations


@pytest.fixture(autouse=True)
def empty_builtin_parse_tables(database_engine: Engine) -> None:
    with database_engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE parsed_artifacts, parsed_blocks, task_outbox, "
                "parsed_source_versions, operations, data_sources, source_blobs CASCADE"
            )
        )


def test_builtin_worker_is_idempotent_and_publishes_terminal_artifacts(
    database_engine: Engine,
    tmp_path: Path,
) -> None:
    session_factory = create_session_factory(database_engine)
    storage = LocalStorageAdapter(tmp_path / "storage")
    repository = SqlAlchemyDataSourceRepository()
    service = DataSourceService(
        repository,
        NoopAuditRepository(),
        tasks=TaskService(SqlAlchemyOperationRepository(), SqlAlchemyOutboxRepository()),
    )
    stored = storage.store_blob(BytesIO(b"# Heading\n\nBody\n"), max_bytes=1024)
    now = datetime.now(UTC)
    with transaction(session_factory) as session:
        source = service.register_upload(
            session,
            stored=stored,
            file_name="source.md",
            extension="md",
            mime_type="text/markdown",
            origin_type="admin_upload",
            duplicate_action="reuse",
            administrator_id=uuid4(),
            now=now,
            trace_id=None,
            source_ip=None,
            user_agent=None,
        ).details.source
    with transaction(session_factory) as session:
        requested = service.request_parse(
            session,
            source.id,
            expected_revision=1,
            requested_config=DEFAULT_PARSE_CONFIG,
            reuse_policy="reuse_if_exact",
            now=now,
        )
    operation_id = requested.version.operation_id
    assert operation_id is not None

    parsers = ParserRegistry()
    parsers.register(BuiltinTextParser())
    handler = SourceParseHandler(SqlAlchemyParseTaskStore(session_factory), parsers, storage)
    dependencies = WorkerDependencies(SqlAlchemyOperationExecutionStore(session_factory))

    execute_operation(operation_id, SOURCE_PARSE_TASK, handler, dependencies)
    execute_operation(operation_id, SOURCE_PARSE_TASK, handler, dependencies)

    with database_engine.connect() as connection:
        version = connection.execute(
            text(
                "SELECT status, quality_level, block_count, markdown_char_count, "
                "feature_flags, normalized_storage_key FROM parsed_source_versions"
            )
        ).one()
        block_count = connection.scalar(text("SELECT count(*) FROM parsed_blocks"))
        artifact_count = connection.scalar(text("SELECT count(*) FROM parsed_artifacts"))
        operation_status = connection.scalar(text("SELECT status FROM operations"))
    assert version.status == "succeeded"
    assert version.quality_level == "full"
    assert version.block_count == 1
    assert version.markdown_char_count == len("# Heading\n\nBody\n")
    assert version.feature_flags["hasText"] is True
    assert version.feature_flags["hasHeadings"] is True
    assert block_count == 1
    assert artifact_count == 1
    assert operation_status == "succeeded"
    with storage.open_binary(version.normalized_storage_key) as artifact:
        assert artifact.read() == b"# Heading\n\nBody\n"
