from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import BinaryIO, Literal, Protocol
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy.orm import Session

from app.modules.parsing.domain import ParsingReference


@dataclass(frozen=True)
class StoredBlob:
    storage_key: str
    sha256: str
    size_bytes: int


class SourceStorage(Protocol):
    def store_blob(self, source: BinaryIO, *, max_bytes: int) -> StoredBlob: ...

    def open_binary(self, storage_key: str) -> BinaryIO: ...

    def delete(self, storage_key: str) -> None: ...

    def exists(self, storage_key: str) -> bool: ...


MinerUState = Literal["waiting-file", "pending", "running", "converting", "done", "failed"]


class MinerUError(Exception):
    def __init__(self, code: str, *, retryable: bool) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class MinerUSubmitRequest:
    file_name: str
    data_id: str
    model_version: str
    language: str
    ocr_enabled: bool
    table_enabled: bool
    formula_enabled: bool
    page_ranges: str | None
    extra_formats: tuple[str, ...]
    force_provider_refresh: bool = False


@dataclass(frozen=True)
class MinerUSignedUpload:
    batch_id: str
    data_id: str
    upload_url: str
    trace_id: str | None


@dataclass(frozen=True)
class MinerUPollResult:
    batch_id: str
    data_id: str
    state: MinerUState
    full_zip_url: str | None
    error_message: str | None
    progress_current: int | None
    progress_total: int | None
    trace_id: str | None
    provider_task_id: str | None = None


class MinerUParseClient(Protocol):
    def request_upload(self, request: MinerUSubmitRequest) -> MinerUSignedUpload: ...
    def upload(self, upload_url: str, source: BinaryIO) -> None: ...
    def poll(self, batch_id: str, data_id: str) -> MinerUPollResult: ...
    def download_result(self, url: str) -> bytes: ...


class MinerUAdapterFactory(Protocol):
    def __call__(
        self,
        *,
        base_url: str,
        credential: SecretStr,
    ) -> MinerUParseClient: ...


class DataSourceAuditRepository(Protocol):
    def record(
        self,
        session: Session,
        *,
        occurred_at: datetime,
        actor_id: UUID,
        event_code: str,
        target_id: UUID,
        target_name: str,
        change_summary: Mapping[str, object],
        trace_id: UUID | None,
        source_ip: str | None,
        user_agent: str | None,
    ) -> None: ...


class ParsingReferenceQuery(Protocol):
    def for_data_source(
        self,
        session: Session,
        data_source_id: UUID,
    ) -> tuple[ParsingReference, ...]: ...

    def for_parsed_version(
        self,
        session: Session,
        parsed_source_version_id: UUID,
    ) -> tuple[ParsingReference, ...]: ...
