from datetime import UTC, datetime
from io import BytesIO
from typing import Protocol
from uuid import UUID

from app.infrastructure.parsers.builtin_text import ParserInputError
from app.infrastructure.parsers.registry import ParserRegistry
from app.modules.parsing.domain import ParseTaskSnapshot
from app.modules.parsing.normalization import NormalizedDocument
from app.modules.parsing.ports import SourceStorage, StoredBlob
from app.modules.tasks.worker import NonRetryableTaskError, RetryableTaskError

SOURCE_PARSE_TASK = "source_parse"
MAX_NORMALIZED_MARKDOWN_BYTES = 400 * 1024 * 1024


class ParseTaskStore(Protocol):
    def load(self, operation_id: UUID) -> ParseTaskSnapshot | None: ...
    def mark_normalizing(self, version_id: UUID) -> bool: ...
    def save_succeeded(
        self,
        snapshot: ParseTaskSnapshot,
        document: NormalizedDocument,
        markdown_artifact: StoredBlob,
        finished_at: datetime,
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
    ) -> None:
        self._store = store
        self._parsers = parsers
        self._storage = storage

    def run(self, operation_id: UUID) -> dict[str, object]:
        snapshot = self._store.load(operation_id)
        if snapshot is None:
            raise NonRetryableTaskError("PARSED_SOURCE_VERSION_NOT_FOUND")
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
