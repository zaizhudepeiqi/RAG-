import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from typing import NoReturn, Protocol
from uuid import UUID

from pydantic import SecretStr

from app.core.security import CredentialDecryptionError, EncryptedSecret, decrypt_secret
from app.infrastructure.parsers.builtin_text import ParserInputError
from app.infrastructure.parsers.registry import ParserRegistry
from app.modules.parsing.domain import (
    TERMINAL_PARSE_STATES,
    ParseState,
    ParseTaskSnapshot,
)
from app.modules.parsing.normalization import (
    MinerUNormalizationError,
    NormalizedAsset,
    NormalizedDocument,
    normalize_mineru_archive,
)
from app.modules.parsing.ports import (
    MinerUAdapterFactory,
    MinerUError,
    MinerUParseClient,
    MinerUPollResult,
    MinerUSubmitRequest,
    SourceStorage,
    StoredBlob,
)
from app.modules.parsing.settings_domain import mineru_token_aad
from app.modules.tasks.worker import NonRetryableTaskError, RetryableTaskError

SOURCE_PARSE_TASK = "source_parse"
MAX_NORMALIZED_MARKDOWN_BYTES = 400 * 1024 * 1024
MAX_MINERU_RESULT_BYTES = 400 * 1024 * 1024
MAX_NORMALIZED_ASSET_BYTES = 200 * 1024 * 1024
MAX_CONSECUTIVE_POLL_ERRORS = 5
Sleeper = Callable[[float], None]
Monotonic = Callable[[], float]


@dataclass(frozen=True)
class StoredNormalizedAsset:
    asset: NormalizedAsset
    stored: StoredBlob


class ParseTaskStore(Protocol):
    def load(self, operation_id: UUID) -> ParseTaskSnapshot | None: ...
    def start_mineru(self, version_id: UUID, data_id: str, started_at: datetime) -> bool: ...
    def save_upload_checkpoint(
        self,
        version_id: UUID,
        *,
        batch_id: str,
        data_id: str,
        trace_id: str | None,
    ) -> bool: ...
    def mark_provider_pending(self, version_id: UUID) -> bool: ...
    def save_provider_poll(self, version_id: UUID, result: MinerUPollResult) -> ParseState: ...
    def save_raw_result(self, version_id: UUID, result: StoredBlob) -> bool: ...
    def mark_normalizing(self, version_id: UUID) -> bool: ...
    def save_succeeded(
        self,
        snapshot: ParseTaskSnapshot,
        document: NormalizedDocument,
        markdown_artifact: StoredBlob,
        finished_at: datetime,
        assets: tuple[StoredNormalizedAsset, ...] = (),
    ) -> bool: ...
    def save_failed(
        self,
        version_id: UUID,
        *,
        error_code: str,
        retryable: bool,
        finished_at: datetime,
    ) -> None: ...


class SourceParseHandler:
    def __init__(
        self,
        store: ParseTaskStore,
        parsers: ParserRegistry,
        storage: SourceStorage,
        *,
        mineru_adapter_factory: MinerUAdapterFactory | None = None,
        credential_encryption_key: bytes | None = None,
        sleeper: Sleeper = time.sleep,
        monotonic: Monotonic = time.monotonic,
    ) -> None:
        self._store = store
        self._parsers = parsers
        self._storage = storage
        self._mineru_adapter_factory = mineru_adapter_factory
        self._credential_encryption_key = credential_encryption_key
        self._sleeper = sleeper
        self._monotonic = monotonic

    def run(self, operation_id: UUID) -> dict[str, object]:
        snapshot = self._store.load(operation_id)
        if snapshot is None:
            raise NonRetryableTaskError("PARSED_SOURCE_VERSION_NOT_FOUND")
        if snapshot.status in TERMINAL_PARSE_STATES:
            return {"parsedSourceVersionId": str(snapshot.version_id), "duplicate": True}
        if snapshot.parser_code == "mineru_precision_api":
            return self._run_mineru(snapshot)
        return self._run_builtin(snapshot)

    def _run_builtin(self, snapshot: ParseTaskSnapshot) -> dict[str, object]:
        if not self._store.mark_normalizing(snapshot.version_id):
            return {"parsedSourceVersionId": str(snapshot.version_id), "duplicate": True}
        try:
            parser = self._parsers.require(
                snapshot.parser_code,
                snapshot.parser_version,
                snapshot.extension,
            )
            with self._storage.open_binary(snapshot.source_storage_key) as source:
                document = parser.parse(source.read(), snapshot.extension)
            artifact = self._storage.store_blob(
                BytesIO(document.markdown.encode("utf-8")),
                max_bytes=MAX_NORMALIZED_MARKDOWN_BYTES,
            )
        except ParserInputError as error:
            self._store.save_failed(
                snapshot.version_id,
                error_code=error.code,
                retryable=False,
                finished_at=datetime.now(UTC),
            )
            raise NonRetryableTaskError(error.code) from error
        except (LookupError, ValueError) as error:
            code = "PARSER_INPUT_UNSUPPORTED"
            self._store.save_failed(
                snapshot.version_id,
                error_code=code,
                retryable=False,
                finished_at=datetime.now(UTC),
            )
            raise NonRetryableTaskError(code) from error
        except OSError as error:
            code = "PARSER_STORAGE_FAILED"
            self._store.save_failed(
                snapshot.version_id,
                error_code=code,
                retryable=True,
                finished_at=datetime.now(UTC),
            )
            raise RetryableTaskError(code) from error
        self._store.save_succeeded(snapshot, document, artifact, datetime.now(UTC))
        return {
            "parsedSourceVersionId": str(snapshot.version_id),
            "blockCount": len(document.blocks),
            "markdownCharCount": len(document.markdown),
        }

    def _run_mineru(self, snapshot: ParseTaskSnapshot) -> dict[str, object]:
        if snapshot.status is ParseState.NORMALIZING:
            if snapshot.raw_result_storage_key is None:
                self._fail(snapshot, "MINERU_CHECKPOINT_INVALID", retryable=False)
            try:
                raw_result = self._load_stored_blob(snapshot.raw_result_storage_key)
            except RetryableTaskError as error:
                self._fail(snapshot, error.code, retryable=True, cause=error)
            except NonRetryableTaskError as error:
                self._fail(snapshot, error.code, retryable=False, cause=error)
            return self._normalize_mineru_result(
                snapshot,
                raw_result,
            )
        adapter = self._mineru_adapter(snapshot)
        expected_data_id = str(snapshot.version_id)
        batch_id = snapshot.provider_batch_id
        data_id = snapshot.provider_data_id

        if batch_id is None:
            if data_id not in {None, expected_data_id}:
                self._fail(snapshot, "MINERU_CHECKPOINT_INVALID", retryable=False)
            self._store.start_mineru(snapshot.version_id, expected_data_id, datetime.now(UTC))
            try:
                request = self._submit_request(snapshot, expected_data_id)
            except NonRetryableTaskError as error:
                self._fail(snapshot, error.code, retryable=False, cause=error)
            try:
                upload = adapter.request_upload(request)
            except MinerUError as error:
                self._fail(snapshot, error.code, retryable=error.retryable, cause=error)
            if upload.data_id != expected_data_id:
                self._fail(snapshot, "MINERU_RESPONSE_INVALID", retryable=False)
            self._store.save_upload_checkpoint(
                snapshot.version_id,
                batch_id=upload.batch_id,
                data_id=upload.data_id,
                trace_id=upload.trace_id,
            )
            try:
                with self._storage.open_binary(snapshot.source_storage_key) as source:
                    adapter.upload(upload.upload_url, source)
            except MinerUError as error:
                self._fail(snapshot, error.code, retryable=error.retryable, cause=error)
            except OSError as error:
                self._fail(snapshot, "PARSER_STORAGE_FAILED", retryable=True, cause=error)
            self._store.mark_provider_pending(snapshot.version_id)
            batch_id = upload.batch_id
            data_id = upload.data_id
        else:
            if data_id != expected_data_id:
                self._fail(snapshot, "MINERU_CHECKPOINT_INVALID", retryable=False)
            self._store.mark_provider_pending(snapshot.version_id)

        return self._poll_and_download(snapshot, adapter, batch_id, expected_data_id)

    def _poll_and_download(
        self,
        snapshot: ParseTaskSnapshot,
        adapter: MinerUParseClient,
        batch_id: str,
        data_id: str,
    ) -> dict[str, object]:
        settings = snapshot.mineru_settings
        if settings is None:
            self._fail(snapshot, "MINERU_AUTH_FAILED", retryable=False)
        started = self._monotonic()
        consecutive_errors = 0
        while True:
            elapsed = self._monotonic() - started
            if elapsed >= settings.poll_timeout_seconds:
                self._fail(snapshot, "MINERU_TIMEOUT", retryable=True)
            try:
                result = adapter.poll(batch_id, data_id)
            except MinerUError as error:
                consecutive_errors += 1
                if error.retryable and consecutive_errors <= MAX_CONSECUTIVE_POLL_ERRORS:
                    self._sleeper(float(mineru_poll_delay_seconds(elapsed)))
                    continue
                self._fail(snapshot, error.code, retryable=error.retryable, cause=error)

            consecutive_errors = 0
            if result.batch_id != batch_id or result.data_id != data_id:
                self._fail(snapshot, "MINERU_RESPONSE_INVALID", retryable=False)
            self._store.save_provider_poll(snapshot.version_id, result)
            if result.state == "failed":
                self._fail(snapshot, "MINERU_POLL_FAILED", retryable=False)
            if result.state == "done":
                if result.full_zip_url is None:
                    self._fail(snapshot, "MINERU_RESPONSE_INVALID", retryable=False)
                return self._download_result(snapshot, adapter, result.full_zip_url)
            self._sleeper(float(mineru_poll_delay_seconds(elapsed)))

    def _download_result(
        self,
        snapshot: ParseTaskSnapshot,
        adapter: MinerUParseClient,
        result_url: str,
    ) -> dict[str, object]:
        try:
            content = adapter.download_result(result_url)
            expected_sha256 = hashlib.sha256(content).hexdigest()
            stored = self._storage.store_blob(
                BytesIO(content),
                max_bytes=MAX_MINERU_RESULT_BYTES,
            )
        except MinerUError as error:
            self._fail(snapshot, error.code, retryable=error.retryable, cause=error)
        except OSError as error:
            self._fail(snapshot, "PARSER_STORAGE_FAILED", retryable=True, cause=error)
        except ValueError as error:
            self._fail(snapshot, "PARSER_ARCHIVE_INVALID", retryable=False, cause=error)
        if stored.sha256 != expected_sha256 or stored.size_bytes != len(content):
            self._fail(snapshot, "PARSER_STORAGE_FAILED", retryable=True)
        self._store.save_raw_result(snapshot.version_id, stored)
        return self._normalize_mineru_result(snapshot, stored)

    def _normalize_mineru_result(
        self,
        snapshot: ParseTaskSnapshot,
        raw_result: StoredBlob,
    ) -> dict[str, object]:
        try:
            with self._storage.open_binary(raw_result.storage_key) as source:
                content = source.read(MAX_MINERU_RESULT_BYTES + 1)
            if len(content) > MAX_MINERU_RESULT_BYTES:
                raise MinerUNormalizationError("PARSER_ARCHIVE_UNSAFE")
            document = normalize_mineru_archive(content)
            markdown = self._storage.store_blob(
                BytesIO(document.markdown.encode("utf-8")),
                max_bytes=MAX_NORMALIZED_MARKDOWN_BYTES,
            )
            assets = tuple(
                StoredNormalizedAsset(
                    asset=asset,
                    stored=self._storage.store_blob(
                        BytesIO(asset.content),
                        max_bytes=MAX_NORMALIZED_ASSET_BYTES,
                    ),
                )
                for asset in document.assets
            )
        except MinerUNormalizationError as error:
            self._fail(snapshot, error.code, retryable=False, cause=error)
        except OSError as error:
            self._fail(snapshot, "PARSER_STORAGE_FAILED", retryable=True, cause=error)
        except ValueError as error:
            self._fail(snapshot, "PARSER_NORMALIZATION_FAILED", retryable=False, cause=error)
        self._store.save_succeeded(
            snapshot,
            document,
            markdown,
            datetime.now(UTC),
            assets,
        )
        return {
            "parsedSourceVersionId": str(snapshot.version_id),
            "qualityLevel": document.quality_level,
            "blockCount": len(document.blocks),
            "assetCount": len(document.assets),
            "rawResultSha256": raw_result.sha256,
            "rawResultSizeBytes": raw_result.size_bytes,
        }

    def _load_stored_blob(self, storage_key: str) -> StoredBlob:
        try:
            with self._storage.open_binary(storage_key) as source:
                content = source.read(MAX_MINERU_RESULT_BYTES + 1)
        except OSError as error:
            raise RetryableTaskError("PARSER_STORAGE_FAILED") from error
        if not content or len(content) > MAX_MINERU_RESULT_BYTES:
            raise NonRetryableTaskError("PARSER_ARCHIVE_INVALID")
        return StoredBlob(
            storage_key=storage_key,
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
        )

    def _mineru_adapter(self, snapshot: ParseTaskSnapshot) -> MinerUParseClient:
        settings = snapshot.mineru_settings
        if (
            settings is None
            or not settings.cloud_processing_confirmed
            or settings.token_ciphertext is None
            or settings.token_nonce is None
            or settings.token_key_version is None
            or self._mineru_adapter_factory is None
            or self._credential_encryption_key is None
        ):
            self._fail(snapshot, "MINERU_AUTH_FAILED", retryable=False)
        try:
            plaintext = decrypt_secret(
                EncryptedSecret(
                    ciphertext=settings.token_ciphertext,
                    nonce=settings.token_nonce,
                    key_version=settings.token_key_version,
                ),
                self._credential_encryption_key,
                associated_data=mineru_token_aad(settings.id),
            )
            credential = SecretStr(plaintext.decode("utf-8"))
        except (CredentialDecryptionError, UnicodeDecodeError) as error:
            self._fail(snapshot, "MINERU_AUTH_FAILED", retryable=False, cause=error)
        return self._mineru_adapter_factory(
            base_url=settings.base_url,
            credential=credential,
        )

    @staticmethod
    def _submit_request(snapshot: ParseTaskSnapshot, data_id: str) -> MinerUSubmitRequest:
        config = snapshot.config_snapshot
        extra_formats = config.get("extraFormats", [])
        if not isinstance(extra_formats, list) or not all(
            isinstance(item, str) for item in extra_formats
        ):
            raise NonRetryableTaskError("PARSE_CONFIG_INVALID")
        return MinerUSubmitRequest(
            file_name=snapshot.source_file_name,
            data_id=data_id,
            model_version=_config_string(config, "modelVersion"),
            language=_config_string(config, "language", default="ch"),
            ocr_enabled=_config_bool(config, "ocrEnabled", default=False),
            table_enabled=_config_bool(config, "tableEnabled", default=False),
            formula_enabled=_config_bool(config, "formulaEnabled", default=False),
            page_ranges=_config_optional_string(config, "pageRanges"),
            extra_formats=tuple(extra_formats),
            force_provider_refresh=_config_bool(
                config,
                "forceProviderRefresh",
                default=False,
            ),
        )

    def _fail(
        self,
        snapshot: ParseTaskSnapshot,
        code: str,
        *,
        retryable: bool,
        cause: Exception | None = None,
    ) -> NoReturn:
        self._store.save_failed(
            snapshot.version_id,
            error_code=code,
            retryable=retryable,
            finished_at=datetime.now(UTC),
        )
        error_type = RetryableTaskError if retryable else NonRetryableTaskError
        if cause is not None:
            raise error_type(code) from cause
        raise error_type(code)


def mineru_poll_delay_seconds(elapsed_seconds: float) -> int:
    if elapsed_seconds < 0:
        raise ValueError("elapsed seconds cannot be negative")
    if elapsed_seconds < 60:
        return 3
    if elapsed_seconds < 600:
        return 10
    return 30


def _config_string(config: dict[str, object], key: str, *, default: str | None = None) -> str:
    value = config.get(key, default)
    if not isinstance(value, str) or not value:
        raise NonRetryableTaskError("PARSE_CONFIG_INVALID")
    return value


def _config_optional_string(config: dict[str, object], key: str) -> str | None:
    value = config.get(key)
    if value is not None and not isinstance(value, str):
        raise NonRetryableTaskError("PARSE_CONFIG_INVALID")
    return value


def _config_bool(config: dict[str, object], key: str, *, default: bool) -> bool:
    value = config.get(key, default)
    if not isinstance(value, bool):
        raise NonRetryableTaskError("PARSE_CONFIG_INVALID")
    return value
