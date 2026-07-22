from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from typing import Literal
from uuid import UUID, uuid4

import pytest
from app.infrastructure.database.repositories.parsing import SqlAlchemyDataSourceRepository
from app.infrastructure.database.session import create_session_factory, transaction
from app.modules.parsing.domain import SourceBlob
from app.modules.parsing.ports import StoredBlob
from app.modules.parsing.service import DataSourceService
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration


class ConcurrentDataSourceRepository(SqlAlchemyDataSourceRepository):
    def __init__(self, barrier: Barrier) -> None:
        self._barrier = barrier

    def acquire_blob(
        self,
        session: Session,
        candidate: SourceBlob,
    ) -> tuple[SourceBlob, bool]:
        self._barrier.wait(timeout=5)
        return super().acquire_blob(session, candidate)


class NoopAuditRepository:
    def record(self, _session: Session, **_kwargs: object) -> None:
        pass


@pytest.fixture(autouse=True)
def empty_source_tables(database_engine: Engine) -> None:
    with database_engine.begin() as connection:
        connection.execute(text("TRUNCATE data_sources, source_blobs CASCADE"))


@pytest.mark.parametrize(
    ("duplicate_action", "expected_source_count", "expected_reference_count"),
    [("reuse", 1, 1), ("create_alias", 2, 2)],
)
def test_concurrent_uploads_preserve_duplicate_semantics(
    database_engine: Engine,
    duplicate_action: Literal["reuse", "create_alias"],
    expected_source_count: int,
    expected_reference_count: int,
) -> None:
    session_factory = create_session_factory(database_engine)
    service = DataSourceService(
        ConcurrentDataSourceRepository(Barrier(2)),
        NoopAuditRepository(),
    )
    stored = StoredBlob(
        storage_key=f"blobs/{'a' * 64}",
        sha256="a" * 64,
        size_bytes=12,
    )
    administrator_id = uuid4()

    def register(file_name: str) -> UUID:
        with transaction(session_factory) as session:
            uploaded = service.register_upload(
                session,
                stored=stored,
                file_name=file_name,
                extension="txt",
                mime_type="text/plain",
                origin_type="admin_upload",
                duplicate_action=duplicate_action,
                administrator_id=administrator_id,
                now=datetime.now(UTC),
                trace_id=None,
                source_ip=None,
                user_agent=None,
            )
        return uploaded.details.source.id

    with ThreadPoolExecutor(max_workers=2) as executor:
        source_ids = list(executor.map(register, ("first.txt", "second.txt")))

    with database_engine.connect() as connection:
        source_count = connection.scalar(text("SELECT count(*) FROM data_sources"))
        blob = connection.execute(text("SELECT reference_count, sha256 FROM source_blobs")).one()

    assert len(set(source_ids)) == expected_source_count
    assert source_count == expected_source_count
    assert blob.reference_count == expected_reference_count
    assert blob.sha256 == stored.sha256
