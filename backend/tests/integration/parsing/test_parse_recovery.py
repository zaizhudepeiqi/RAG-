import json
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from app.core.security import encrypt_secret
from app.infrastructure.database.repositories.mineru_settings import (
    SqlAlchemyMinerUSettingsRepository,
)
from app.infrastructure.database.repositories.parsing import (
    SqlAlchemyDataSourceRepository,
    SqlAlchemyMinerUTestTaskStore,
    SqlAlchemyParseTaskStore,
    SqlAlchemyParsingCleanupTaskStore,
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
from app.modules.parsing.ports import MinerUPollResult, MinerUSignedUpload, MinerUSubmitRequest
from app.modules.parsing.service import DataSourceService
from app.modules.parsing.settings_domain import (
    DEFAULT_PARSE_CONFIG,
    MINERU_SETTINGS_ID,
    mineru_token_aad,
)
from app.modules.parsing.settings_service import MinerUSettingsService
from app.modules.parsing.tasks import (
    MINERU_CONNECTION_TEST_TASK,
    PARSING_CLEANUP_TASK,
    SOURCE_PARSE_TASK,
    MinerUConnectionTestHandler,
    ParsingCleanupHandler,
    SourceParseHandler,
)
from app.modules.tasks.service import TaskService
from app.modules.tasks.worker import execute_operation
from pydantic import SecretStr
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration

KEY = b"m" * 32


class WorkerDependencies:
    def __init__(self, operations: SqlAlchemyOperationExecutionStore) -> None:
        self.operations = operations


class NoopAuditRepository:
    def record(self, _session: Session, **_kwargs: object) -> None:
        pass


class TestMinerUAdapter:
    __test__ = False

    def __init__(self, result_archive: bytes) -> None:
        self.result_archive = result_archive
        self.requests: list[MinerUSubmitRequest] = []
        self.uploaded = b""
        self.poll_count = 0
        self.download_urls: list[str] = []

    def request_upload(self, request: MinerUSubmitRequest) -> MinerUSignedUpload:
        self.requests.append(request)
        return MinerUSignedUpload(
            batch_id="batch-settings-test-001",
            data_id=request.data_id,
            upload_url="https://upload.example.com/redacted",
            trace_id="trace-settings-submit",
        )

    def upload(self, _upload_url: str, source: BytesIO) -> None:
        self.uploaded = source.read()

    def poll(self, batch_id: str, data_id: str) -> MinerUPollResult:
        self.poll_count += 1
        done = self.poll_count == 2
        return MinerUPollResult(
            batch_id=batch_id,
            data_id=data_id,
            state="done" if done else "running",
            full_zip_url=("https://download.example.com/result.zip" if done else None),
            error_message=None,
            progress_current=1 if done else 0,
            progress_total=1,
            trace_id="trace-settings-poll",
            provider_task_id="provider-settings-test-001",
        )

    def download_result(self, url: str) -> bytes:
        self.download_urls.append(url)
        return self.result_archive


@pytest.fixture(autouse=True)
def empty_recovery_tables(database_engine: Engine) -> None:
    with database_engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE audit_logs, parsed_artifacts, parsed_block_assets, parsed_assets, "
                "parsed_blocks, task_outbox, parsed_source_versions, operations, data_sources, "
                "source_blobs, mineru_settings, administrators CASCADE"
            )
        )


def mineru_archive() -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as bundle:
        bundle.writestr("test/result.md", "# MinerU connection test\n")
        bundle.writestr(
            "test/result_content_list.json",
            json.dumps(
                [
                    {
                        "type": "text",
                        "text": "MinerU connection test",
                        "text_level": 1,
                        "page_idx": 0,
                        "bbox": [1, 2, 100, 20],
                    }
                ]
            ),
        )
    return output.getvalue()


def configure_mineru(database_engine: Engine) -> None:
    encrypted = encrypt_secret(
        b"mineru-test-token",
        KEY,
        associated_data=mineru_token_aad(MINERU_SETTINGS_ID),
        key_version="v1",
    )
    with database_engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO mineru_settings (
                    id, base_url, token_ciphertext, token_nonce, token_key_version,
                    token_prefix, token_revision, default_parse_config,
                    poll_timeout_seconds, cloud_processing_confirmed_at, revision
                ) VALUES (
                    :id, 'https://mineru.example.com', :ciphertext, :nonce, 'v1',
                    'mine...oken', 1, CAST(:config AS jsonb), 1800, now(), 1
                )
                """
            ),
            {
                "id": MINERU_SETTINGS_ID,
                "ciphertext": encrypted.ciphertext,
                "nonce": encrypted.nonce,
                "config": json.dumps(
                    {
                        "parserCode": DEFAULT_PARSE_CONFIG.parser_code,
                        "modelVersion": DEFAULT_PARSE_CONFIG.model_version,
                        "language": DEFAULT_PARSE_CONFIG.language,
                        "ocrEnabled": DEFAULT_PARSE_CONFIG.ocr_enabled,
                        "tableEnabled": DEFAULT_PARSE_CONFIG.table_enabled,
                        "formulaEnabled": DEFAULT_PARSE_CONFIG.formula_enabled,
                        "pageRanges": DEFAULT_PARSE_CONFIG.page_ranges,
                        "extraFormats": list(DEFAULT_PARSE_CONFIG.extra_formats),
                        "forceProviderRefresh": DEFAULT_PARSE_CONFIG.force_provider_refresh,
                    }
                ),
            },
        )


def test_mineru_settings_test_executes_upload_poll_download_and_normalize(
    database_engine: Engine,
    tmp_path: Path,
) -> None:
    del tmp_path
    configure_mineru(database_engine)
    session_factory = create_session_factory(database_engine)
    now = datetime.now(UTC)
    with transaction(session_factory) as session:
        operation = TaskService(
            SqlAlchemyOperationRepository(),
            SqlAlchemyOutboxRepository(),
        ).create_operation(
            session,
            task_type=MINERU_CONNECTION_TEST_TASK,
            target_type="mineru_settings",
            target_id=MINERU_SETTINGS_ID,
            target_revision=1,
            business_key="mineru.settings.test:integration-001",
            event_type="parsing.mineru.test.requested",
            payload={"settingsRevision": 1},
            now=now,
            expires_at=now + timedelta(days=1),
        )
    adapter = TestMinerUAdapter(mineru_archive())
    delays: list[float] = []
    handler = MinerUConnectionTestHandler(
        SqlAlchemyMinerUTestTaskStore(session_factory),
        mineru_adapter_factory=lambda **kwargs: _assert_factory(kwargs, adapter),
        credential_encryption_key=KEY,
        sleeper=delays.append,
    )

    execute_operation(
        operation.id,
        MINERU_CONNECTION_TEST_TASK,
        handler,
        WorkerDependencies(SqlAlchemyOperationExecutionStore(session_factory)),
    )

    assert len(adapter.requests) == 1
    assert adapter.requests[0].data_id == str(operation.id)
    assert adapter.requests[0].force_provider_refresh is True
    assert adapter.uploaded.startswith(b"%PDF-")
    assert adapter.uploaded.rstrip().endswith(b"%%EOF")
    assert adapter.poll_count == 2
    assert adapter.download_urls == ["https://download.example.com/result.zip"]
    assert delays == [3.0]
    with database_engine.connect() as connection:
        stored = connection.execute(
            text("SELECT status, result_summary::text FROM operations WHERE id = :id"),
            {"id": operation.id},
        ).one()
    assert stored.status == "succeeded"
    assert "mineru-test-token" not in stored.result_summary
    assert "upload.example.com" not in stored.result_summary
    assert "download.example.com" not in stored.result_summary


def test_resumed_parse_queries_original_batch_without_new_upload(
    database_engine: Engine,
    tmp_path: Path,
) -> None:
    configure_mineru(database_engine)
    session_factory = create_session_factory(database_engine)
    storage = LocalStorageAdapter(tmp_path / "storage")
    tasks = TaskService(SqlAlchemyOperationRepository(), SqlAlchemyOutboxRepository())
    service = DataSourceService(
        SqlAlchemyDataSourceRepository(),
        NoopAuditRepository(),
        tasks=tasks,
        mineru_settings=MinerUSettingsService(
            SqlAlchemyMinerUSettingsRepository(),
            NoopAuditRepository(),
            KEY,
        ),
    )
    now = datetime.now(UTC)
    stored = storage.store_blob(BytesIO(b"%PDF-1.7\nresume"), max_bytes=1024)
    with transaction(session_factory) as session:
        source = service.register_upload(
            session,
            stored=stored,
            file_name="resume.pdf",
            extension="pdf",
            mime_type="application/pdf",
            origin_type="admin_upload",
            duplicate_action="reuse",
            administrator_id=MINERU_SETTINGS_ID,
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
    original_operation_id = requested.version.operation_id
    assert original_operation_id is not None
    with database_engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE parsed_source_versions
                SET status = 'failed', error_code = 'MINERU_TIMEOUT', retryable = true,
                    provider_batch_id = 'batch-settings-test-001',
                    provider_data_id = CAST(id AS text), finished_at = now()
                WHERE id = :version_id
                """
            ),
            {"version_id": requested.version.id},
        )
        connection.execute(
            text(
                "UPDATE operations SET status = 'failed', retryable = true, "
                "finished_at = now() WHERE id = :operation_id"
            ),
            {"operation_id": original_operation_id},
        )
    with transaction(session_factory) as session:
        resumed = service.resume_provider_query(
            session,
            requested.version.id,
            now=datetime.now(UTC),
        )

    adapter = TestMinerUAdapter(mineru_archive())
    parsers = ParserRegistry()
    parsers.register(BuiltinTextParser())
    handler = SourceParseHandler(
        SqlAlchemyParseTaskStore(session_factory),
        parsers,
        storage,
        mineru_adapter_factory=lambda **_kwargs: adapter,
        credential_encryption_key=KEY,
        sleeper=lambda _delay: None,
    )
    execute_operation(
        resumed.id,
        SOURCE_PARSE_TASK,
        handler,
        WorkerDependencies(SqlAlchemyOperationExecutionStore(session_factory)),
    )

    assert adapter.requests == []
    assert adapter.uploaded == b""
    assert adapter.poll_count == 2
    with database_engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT status, provider_batch_id, operation_id "
                "FROM parsed_source_versions WHERE id = :version_id"
            ),
            {"version_id": requested.version.id},
        ).one()
    assert row.status == "succeeded"
    assert row.provider_batch_id == "batch-settings-test-001"
    assert row.operation_id == resumed.id


def test_source_cleanup_removes_content_and_file_but_keeps_tombstone(
    database_engine: Engine,
    tmp_path: Path,
) -> None:
    session_factory = create_session_factory(database_engine)
    storage = LocalStorageAdapter(tmp_path / "storage")
    tasks = TaskService(SqlAlchemyOperationRepository(), SqlAlchemyOutboxRepository())
    service = DataSourceService(
        SqlAlchemyDataSourceRepository(),
        NoopAuditRepository(),
        tasks=tasks,
    )
    now = datetime.now(UTC)
    stored = storage.store_blob(BytesIO(b"cleanup body"), max_bytes=1024)
    with transaction(session_factory) as session:
        source = service.register_upload(
            session,
            stored=stored,
            file_name="cleanup.txt",
            extension="txt",
            mime_type="text/plain",
            origin_type="admin_upload",
            duplicate_action="reuse",
            administrator_id=MINERU_SETTINGS_ID,
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
    parse_operation_id = requested.version.operation_id
    assert parse_operation_id is not None
    parsers = ParserRegistry()
    parsers.register(BuiltinTextParser())
    execute_operation(
        parse_operation_id,
        SOURCE_PARSE_TASK,
        SourceParseHandler(SqlAlchemyParseTaskStore(session_factory), parsers, storage),
        WorkerDependencies(SqlAlchemyOperationExecutionStore(session_factory)),
    )
    with transaction(session_factory) as session:
        cleanup = service.request_delete_source(
            session,
            source.id,
            expected_revision=1,
            administrator_id=MINERU_SETTINGS_ID,
            now=datetime.now(UTC),
            trace_id=None,
            source_ip=None,
            user_agent=None,
        )

    execute_operation(
        cleanup.id,
        PARSING_CLEANUP_TASK,
        ParsingCleanupHandler(SqlAlchemyParsingCleanupTaskStore(session_factory), storage),
        WorkerDependencies(SqlAlchemyOperationExecutionStore(session_factory)),
    )

    with database_engine.connect() as connection:
        tombstone = connection.execute(
            text(
                """
                SELECT ds.deleted_at, sb.reference_count, sb.purge_after
                FROM data_sources ds JOIN source_blobs sb ON sb.id = ds.source_blob_id
                WHERE ds.id = :source_id
                """
            ),
            {"source_id": source.id},
        ).one()
        version_count = connection.scalar(text("SELECT count(*) FROM parsed_source_versions"))
        cleanup_status = connection.scalar(
            text("SELECT status FROM operations WHERE id = :id"),
            {"id": cleanup.id},
        )
    assert tombstone.deleted_at is not None
    assert tombstone.reference_count == 0
    assert tombstone.purge_after is not None
    assert version_count == 0
    assert cleanup_status == "succeeded"
    assert storage.exists(stored.storage_key) is False


def test_source_cleanup_keeps_blob_still_referenced_by_an_alias(
    database_engine: Engine,
    tmp_path: Path,
) -> None:
    session_factory = create_session_factory(database_engine)
    storage = LocalStorageAdapter(tmp_path / "storage")
    service = DataSourceService(
        SqlAlchemyDataSourceRepository(),
        NoopAuditRepository(),
        tasks=TaskService(SqlAlchemyOperationRepository(), SqlAlchemyOutboxRepository()),
    )
    now = datetime.now(UTC)
    stored = storage.store_blob(BytesIO(b"shared source"), max_bytes=1024)
    with transaction(session_factory) as session:
        first = service.register_upload(
            session,
            stored=stored,
            file_name="first.txt",
            extension="txt",
            mime_type="text/plain",
            origin_type="admin_upload",
            duplicate_action="create_alias",
            administrator_id=MINERU_SETTINGS_ID,
            now=now,
            trace_id=None,
            source_ip=None,
            user_agent=None,
        ).details.source
    with transaction(session_factory) as session:
        alias = service.register_upload(
            session,
            stored=stored,
            file_name="alias.txt",
            extension="txt",
            mime_type="text/plain",
            origin_type="admin_upload",
            duplicate_action="create_alias",
            administrator_id=MINERU_SETTINGS_ID,
            now=now,
            trace_id=None,
            source_ip=None,
            user_agent=None,
        ).details.source
    with transaction(session_factory) as session:
        cleanup = service.request_delete_source(
            session,
            first.id,
            expected_revision=1,
            administrator_id=MINERU_SETTINGS_ID,
            now=datetime.now(UTC),
            trace_id=None,
            source_ip=None,
            user_agent=None,
        )

    execute_operation(
        cleanup.id,
        PARSING_CLEANUP_TASK,
        ParsingCleanupHandler(SqlAlchemyParsingCleanupTaskStore(session_factory), storage),
        WorkerDependencies(SqlAlchemyOperationExecutionStore(session_factory)),
    )

    with database_engine.connect() as connection:
        blob = connection.execute(
            text("SELECT reference_count, purge_after FROM source_blobs")
        ).one()
        alias_deleted_at = connection.scalar(
            text("SELECT deleted_at FROM data_sources WHERE id = :id"),
            {"id": alias.id},
        )
    assert blob.reference_count == 1
    assert blob.purge_after is None
    assert alias_deleted_at is None
    assert storage.exists(stored.storage_key) is True


def _assert_factory(
    kwargs: dict[str, object],
    adapter: TestMinerUAdapter,
) -> TestMinerUAdapter:
    assert kwargs["base_url"] == "https://mineru.example.com"
    credential = kwargs["credential"]
    assert isinstance(credential, SecretStr)
    assert credential.get_secret_value() == "mineru-test-token"
    return adapter
