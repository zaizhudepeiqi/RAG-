from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.infrastructure.database.repositories.parsing import SqlAlchemyDataSourceRepository
from app.infrastructure.database.repositories.tasks import (
    SqlAlchemyOperationRepository,
    SqlAlchemyOutboxRepository,
)
from app.infrastructure.database.session import create_session_factory, transaction
from app.modules.parsing.domain import ParsedSourceVersion
from app.modules.parsing.ports import StoredBlob
from app.modules.parsing.service import DataSourceService
from app.modules.parsing.settings_domain import DEFAULT_PARSE_CONFIG
from app.modules.tasks.service import TaskService
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration


class NoopAuditRepository:
    def record(self, _session: Session, **_kwargs: object) -> None:
        pass


class FailingVersionRepository(SqlAlchemyDataSourceRepository):
    def add_version(self, _session: Session, _version: ParsedSourceVersion) -> None:
        raise RuntimeError("simulated version persistence failure")


@pytest.fixture(autouse=True)
def empty_parse_tables(database_engine: Engine) -> None:
    with database_engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE task_outbox, parsed_source_versions, operations, "
                "data_sources, source_blobs CASCADE"
            )
        )


def test_parse_version_operation_and_outbox_rollback_together(
    database_engine: Engine,
) -> None:
    session_factory = create_session_factory(database_engine)
    repository = SqlAlchemyDataSourceRepository()
    upload_service = DataSourceService(repository, NoopAuditRepository())
    now = datetime.now(UTC)
    with transaction(session_factory) as session:
        source = upload_service.register_upload(
            session,
            stored=StoredBlob(storage_key="blobs/test-source", sha256="b" * 64, size_bytes=4),
            file_name="source.txt",
            extension="txt",
            mime_type="text/plain",
            origin_type="admin_upload",
            duplicate_action="reuse",
            administrator_id=uuid4(),
            now=now,
            trace_id=None,
            source_ip=None,
            user_agent=None,
        ).details.source

    service = DataSourceService(
        FailingVersionRepository(),
        NoopAuditRepository(),
        tasks=TaskService(SqlAlchemyOperationRepository(), SqlAlchemyOutboxRepository()),
    )
    with pytest.raises(RuntimeError, match="simulated version persistence failure"):
        with transaction(session_factory) as session:
            service.request_parse(
                session,
                source.id,
                expected_revision=1,
                requested_config=DEFAULT_PARSE_CONFIG,
                reuse_policy="reuse_if_exact",
                now=now,
            )

    with database_engine.connect() as connection:
        counts = (
            connection.scalar(text("SELECT count(*) FROM parsed_source_versions")),
            connection.scalar(text("SELECT count(*) FROM operations")),
            connection.scalar(text("SELECT count(*) FROM task_outbox")),
        )
    assert counts == (0, 0, 0)
