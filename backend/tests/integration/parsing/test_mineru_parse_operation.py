import json
from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from app.core.security import encrypt_secret
from app.infrastructure.database.repositories.mineru_settings import (
    SqlAlchemyMinerUSettingsRepository,
)
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
from app.infrastructure.parsers.mineru_precision import (
    MinerUError,
    MinerUPollResult,
    MinerUSignedUpload,
    MinerUSubmitRequest,
)
from app.infrastructure.parsers.registry import ParserRegistry
from app.infrastructure.storage.local import LocalStorageAdapter
from app.modules.parsing.service import DataSourceService
from app.modules.parsing.settings_domain import (
    DEFAULT_PARSE_CONFIG,
    MINERU_SETTINGS_ID,
    mineru_token_aad,
)
from app.modules.parsing.settings_service import MinerUSettingsService
from app.modules.parsing.tasks import SOURCE_PARSE_TASK, SourceParseHandler
from app.modules.tasks.service import TaskService
from app.modules.tasks.worker import RetryableTaskError, execute_operation
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration

KEY = b"m" * 32


class NoopAuditRepository:
    def record(self, _session: Session, **_kwargs: object) -> None:
        pass


class WorkerDependencies:
    def __init__(self, operations: SqlAlchemyOperationExecutionStore) -> None:
        self.operations = operations


class SimulatedWorkerCrash(RuntimeError):
    pass


class ControlledClock:
    def __init__(self) -> None:
        self.elapsed_seconds = 0.0
        self.delays: list[float] = []

    def monotonic(self) -> float:
        return self.elapsed_seconds

    def sleep(self, delay: float) -> None:
        self.delays.append(delay)
        self.elapsed_seconds += delay


class ControlledMinerUAdapter:
    def __init__(
        self,
        *,
        poll_results: list[MinerUPollResult | MinerUError],
        result_archive: bytes,
        before_upload: Callable[[], None] | None = None,
        crash_on_upload: bool = False,
    ) -> None:
        self._poll_results = poll_results
        self._result_archive = result_archive
        self._before_upload = before_upload
        self._crash_on_upload = crash_on_upload
        self.submit_requests: list[MinerUSubmitRequest] = []
        self.upload_count = 0
        self.poll_count = 0
        self.download_urls: list[str] = []

    def request_upload(self, request: MinerUSubmitRequest) -> MinerUSignedUpload:
        self.submit_requests.append(request)
        return MinerUSignedUpload(
            batch_id="batch-worker-001",
            data_id=request.data_id,
            upload_url="https://upload.example.com/redacted",
            trace_id="trace-submit",
        )

    def upload(self, _upload_url: str, _source: BytesIO) -> None:
        self.upload_count += 1
        if self._before_upload is not None:
            self._before_upload()
        if self._crash_on_upload:
            raise SimulatedWorkerCrash

    def poll(self, _batch_id: str, _data_id: str) -> MinerUPollResult:
        self.poll_count += 1
        result = self._poll_results.pop(0)
        if isinstance(result, MinerUError):
            raise result
        return result

    def download_result(self, url: str) -> bytes:
        self.download_urls.append(url)
        return self._result_archive


@pytest.fixture(autouse=True)
def empty_mineru_parse_tables(database_engine: Engine) -> None:
    with database_engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE parsed_artifacts, parsed_blocks, task_outbox, "
                "parsed_source_versions, operations, data_sources, source_blobs, "
                "mineru_settings CASCADE"
            )
        )


def configure_mineru(connection: Engine) -> None:
    encrypted = encrypt_secret(
        b"mineru-test-token",
        KEY,
        associated_data=mineru_token_aad(MINERU_SETTINGS_ID),
        key_version="v1",
    )
    with connection.begin() as transaction_connection:
        transaction_connection.execute(
            text(
                """
                INSERT INTO mineru_settings (
                    id, base_url, token_ciphertext, token_nonce, token_key_version,
                    token_prefix, token_revision, default_parse_config,
                    poll_timeout_seconds, cloud_processing_confirmed_at, revision
                )
                VALUES (
                    :id, 'https://mineru.example.com', :ciphertext, :nonce, 'v1',
                    'mine...oken', 1, CAST(:default_parse_config AS jsonb),
                    1800, now(), 1
                )
                """
            ),
            {
                "id": MINERU_SETTINGS_ID,
                "ciphertext": encrypted.ciphertext,
                "nonce": encrypted.nonce,
                "default_parse_config": json.dumps(
                    {
                        "parserCode": "mineru_precision_api",
                        "modelVersion": "pipeline",
                        "language": "ch",
                        "ocrEnabled": False,
                        "tableEnabled": True,
                        "formulaEnabled": True,
                        "pageRanges": None,
                        "extraFormats": [],
                        "forceProviderRefresh": False,
                    }
                ),
            },
        )


def create_parse_request(
    database_engine: Engine,
    storage: LocalStorageAdapter,
) -> tuple[UUID, UUID]:
    configure_mineru(database_engine)
    session_factory = create_session_factory(database_engine)
    service = DataSourceService(
        SqlAlchemyDataSourceRepository(),
        NoopAuditRepository(),
        tasks=TaskService(SqlAlchemyOperationRepository(), SqlAlchemyOutboxRepository()),
        mineru_settings=MinerUSettingsService(
            SqlAlchemyMinerUSettingsRepository(),
            NoopAuditRepository(),
            KEY,
        ),
    )
    now = datetime.now(UTC)
    stored = storage.store_blob(BytesIO(b"%PDF-1.7\nfixture"), max_bytes=1024)
    with transaction(session_factory) as session:
        source = service.register_upload(
            session,
            stored=stored,
            file_name="contract.pdf",
            extension="pdf",
            mime_type="application/pdf",
            origin_type="admin_upload",
            duplicate_action="reuse",
            administrator_id=uuid4(),
            now=now,
            trace_id=None,
            source_ip=None,
            user_agent=None,
        ).details.source
    with transaction(session_factory) as session:
        request = service.request_parse(
            session,
            source.id,
            expected_revision=1,
            requested_config=DEFAULT_PARSE_CONFIG,
            reuse_policy="reuse_if_exact",
            now=now,
        )
    operation_id = request.version.operation_id
    assert operation_id is not None
    return operation_id, request.version.id


def parse_handler(
    database_engine: Engine,
    storage: LocalStorageAdapter,
    adapter: ControlledMinerUAdapter,
    clock: ControlledClock,
) -> SourceParseHandler:
    parsers = ParserRegistry()
    parsers.register(BuiltinTextParser())
    return SourceParseHandler(
        SqlAlchemyParseTaskStore(create_session_factory(database_engine)),
        parsers,
        storage,
        mineru_adapter_factory=lambda **_kwargs: adapter,
        credential_encryption_key=KEY,
        sleeper=clock.sleep,
        monotonic=clock.monotonic,
    )


def poll_result(
    state: str,
    data_id: str,
    *,
    progress: int | None = None,
) -> MinerUPollResult:
    return MinerUPollResult(
        batch_id="batch-worker-001",
        data_id=data_id,
        state=state,  # type: ignore[arg-type]
        full_zip_url=("https://download.example.com/result.zip" if state == "done" else None),
        error_message=None,
        progress_current=progress,
        progress_total=2 if progress is not None else None,
        trace_id=f"trace-{state}",
        provider_task_id="provider-task-001",
    )


def test_mineru_worker_persists_checkpoint_before_upload_and_resumes_without_resubmit(
    database_engine: Engine,
    tmp_path: Path,
) -> None:
    storage = LocalStorageAdapter(tmp_path / "storage")
    operation_id, version_id = create_parse_request(database_engine, storage)

    def assert_checkpoint_exists_before_upload() -> None:
        with database_engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT status, provider_batch_id, provider_data_id
                    FROM parsed_source_versions
                    WHERE id = :version_id
                    """
                ),
                {"version_id": version_id},
            ).one()
        assert row.status == "uploading"
        assert row.provider_batch_id == "batch-worker-001"
        assert row.provider_data_id == str(version_id)

    first_clock = ControlledClock()
    first_adapter = ControlledMinerUAdapter(
        poll_results=[],
        result_archive=b"zip-result-v1",
        before_upload=assert_checkpoint_exists_before_upload,
        crash_on_upload=True,
    )
    with pytest.raises(SimulatedWorkerCrash):
        parse_handler(database_engine, storage, first_adapter, first_clock).run(operation_id)

    second_clock = ControlledClock()
    second_adapter = ControlledMinerUAdapter(
        poll_results=[
            poll_result("pending", str(version_id)),
            poll_result("running", str(version_id), progress=1),
            poll_result("converting", str(version_id), progress=2),
            poll_result("done", str(version_id), progress=2),
        ],
        result_archive=b"zip-result-v1",
    )
    handler = parse_handler(database_engine, storage, second_adapter, second_clock)
    execute_operation(
        operation_id,
        SOURCE_PARSE_TASK,
        handler,
        WorkerDependencies(
            SqlAlchemyOperationExecutionStore(create_session_factory(database_engine))
        ),
    )

    with database_engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT status, provider_batch_id, provider_data_id, provider_task_id,
                       provider_trace_id, progress_current, progress_total,
                       raw_result_storage_key
                FROM parsed_source_versions
                WHERE id = :version_id
                """
            ),
            {"version_id": version_id},
        ).one()
        operation_status = connection.scalar(
            text("SELECT status FROM operations WHERE id = :operation_id"),
            {"operation_id": operation_id},
        )

    assert first_adapter.submit_requests[0].data_id == str(version_id)
    assert first_adapter.upload_count == 1
    assert second_adapter.submit_requests == []
    assert second_adapter.upload_count == 0
    assert second_adapter.poll_count == 4
    assert second_clock.delays == [3.0, 3.0, 3.0]
    assert row.status == "normalizing"
    assert row.provider_batch_id == "batch-worker-001"
    assert row.provider_data_id == str(version_id)
    assert row.provider_task_id == "provider-task-001"
    assert row.provider_trace_id == "trace-done"
    assert (row.progress_current, row.progress_total) == (2, 2)
    assert operation_status == "succeeded"
    assert row.raw_result_storage_key is not None
    with storage.open_binary(row.raw_result_storage_key) as raw_result:
        assert raw_result.read() == b"zip-result-v1"
    assert row.raw_result_storage_key.endswith(sha256(b"zip-result-v1").hexdigest())


def test_mineru_worker_stops_after_consecutive_poll_errors_without_new_submission(
    database_engine: Engine,
    tmp_path: Path,
) -> None:
    storage = LocalStorageAdapter(tmp_path / "storage")
    operation_id, version_id = create_parse_request(database_engine, storage)
    clock = ControlledClock()
    adapter = ControlledMinerUAdapter(
        poll_results=[MinerUError("MINERU_RATE_LIMITED", retryable=True) for _ in range(6)],
        result_archive=b"unused",
    )
    handler = parse_handler(database_engine, storage, adapter, clock)

    with pytest.raises(RetryableTaskError, match="MINERU_RATE_LIMITED"):
        handler.run(operation_id)
    duplicate = handler.run(operation_id)

    with database_engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT status, retryable, provider_batch_id, provider_data_id
                FROM parsed_source_versions
                WHERE id = :version_id
                """
            ),
            {"version_id": version_id},
        ).one()
    assert len(adapter.submit_requests) == 1
    assert adapter.upload_count == 1
    assert adapter.poll_count == 6
    assert clock.delays == [3.0] * 5
    assert duplicate == {"parsedSourceVersionId": str(version_id), "duplicate": True}
    assert row.status == "failed"
    assert row.retryable is True
    assert row.provider_batch_id == "batch-worker-001"
    assert row.provider_data_id == str(version_id)
