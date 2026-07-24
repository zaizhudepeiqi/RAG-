from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.modules.parsing.domain import (
    DataSource,
    DataSourceDetails,
    ParsedArtifact,
    ParsedAsset,
    ParsedBlock,
    ParsedSourceVersion,
    ParsedSourceVersionDetails,
    RegisteredUpload,
    SourceBlob,
    normalize_parse_config,
)
from app.modules.parsing.ports import DataSourceAuditRepository, StoredBlob
from app.modules.parsing.repository import (
    DataSourceListQuery,
    DataSourcePage,
    DataSourceRepository,
)
from app.modules.parsing.settings_domain import ParseConfig
from app.modules.parsing.settings_service import (
    MinerUCloudConsentRequiredError,
    MinerUSettingsService,
)
from app.modules.tasks.service import TaskService

REUSABLE_PARSE_STATUSES = (
    "queued",
    "submitting",
    "uploading",
    "provider_pending",
    "parsing",
    "downloading",
    "normalizing",
    "succeeded",
    "degraded",
)
EMPTY_FEATURE_FLAGS = {
    "hasText": False,
    "hasPages": False,
    "hasHeadings": False,
    "hasBoundingBoxes": False,
    "hasAssets": False,
    "hasTables": False,
    "hasFormulas": False,
}


class DataSourceNotFoundError(ValueError):
    pass


class DataSourceRevisionConflictError(ValueError):
    pass


class ParseConfigInvalidError(ValueError):
    pass


class ParsedSourceVersionNotFoundError(ValueError):
    pass


class ParsedVersionNotSelectableError(ValueError):
    pass


@dataclass(frozen=True)
class ParseRequestResult:
    version: ParsedSourceVersion
    reused: bool


class DataSourceService:
    def __init__(
        self,
        repository: DataSourceRepository,
        audits: DataSourceAuditRepository,
        tasks: TaskService | None = None,
        mineru_settings: MinerUSettingsService | None = None,
        operation_retention_days: int = 30,
    ) -> None:
        self._repository = repository
        self._audits = audits
        self._tasks = tasks
        self._mineru_settings = mineru_settings
        self._operation_retention_days = operation_retention_days

    def register_upload(
        self,
        session: Session,
        *,
        stored: StoredBlob,
        file_name: str,
        extension: str,
        mime_type: str,
        origin_type: Literal["admin_upload"],
        duplicate_action: Literal["reuse", "create_alias"],
        administrator_id: UUID,
        now: datetime,
        trace_id: UUID | None,
        source_ip: str | None,
        user_agent: str | None,
        source_path: str | None = None,
    ) -> RegisteredUpload:
        blob, created = self._repository.acquire_blob(
            session,
            SourceBlob(
                id=uuid4(),
                sha256=stored.sha256,
                size_bytes=stored.size_bytes,
                storage_key=stored.storage_key,
                mime_type=mime_type,
                reference_count=1,
                created_at=now,
                last_referenced_at=now,
                purge_after=None,
            ),
        )
        duplicate = self._repository.find_active_source_by_sha256(session, stored.sha256)
        if duplicate is not None and duplicate_action == "reuse":
            return RegisteredUpload(
                details=self._details(session, duplicate),
                duplicate_of_data_source_id=duplicate.id,
            )
        if not created:
            blob.reference_count += 1
            blob.last_referenced_at = now
            blob.purge_after = None
            self._repository.save_blob(session, blob)

        source = DataSource(
            id=uuid4(),
            source_blob_id=blob.id,
            display_name=file_name,
            source_path=source_path if source_path is not None else file_name,
            original_file_name=file_name,
            extension=extension,
            mime_type=mime_type,
            size_bytes=stored.size_bytes,
            sha256=stored.sha256,
            origin_type=origin_type,
            origin_ref={},
            revision=1,
            created_at=now,
            updated_at=now,
            deleted_at=None,
        )
        self._repository.add_source(session, source)
        self._audits.record(
            session,
            occurred_at=now,
            actor_id=administrator_id,
            event_code="data_source.created",
            target_id=source.id,
            target_name=source.display_name,
            change_summary={
                "extension": source.extension,
                "mimeType": source.mime_type,
                "sizeBytes": source.size_bytes,
                "sha256Short": source.sha256[:12],
                "duplicate": duplicate is not None,
            },
            trace_id=trace_id,
            source_ip=source_ip,
            user_agent=user_agent,
        )
        return RegisteredUpload(
            details=DataSourceDetails(source=source, blob=blob),
            duplicate_of_data_source_id=duplicate.id if duplicate is not None else None,
        )

    def get(self, session: Session, source_id: UUID) -> DataSourceDetails:
        source = self._repository.get_source(session, source_id)
        if source is None:
            raise DataSourceNotFoundError
        return self._details(session, source)

    def list(
        self, session: Session, query: DataSourceListQuery
    ) -> tuple[DataSourcePage, list[DataSourceDetails]]:
        page = self._repository.list_sources(session, query)
        return page, [self._details(session, source) for source in page.items]

    def request_parse(
        self,
        session: Session,
        source_id: UUID,
        *,
        expected_revision: int,
        requested_config: ParseConfig,
        reuse_policy: Literal["reuse_if_exact", "force_new"],
        now: datetime,
    ) -> ParseRequestResult:
        if self._tasks is None:
            raise RuntimeError("parse operations are not configured")
        source = self._repository.get_source(session, source_id, for_update=True)
        if source is None:
            raise DataSourceNotFoundError
        if source.revision != expected_revision:
            raise DataSourceRevisionConflictError
        try:
            normalized = normalize_parse_config(
                source.extension,
                requested_config,
                force_new=reuse_policy == "force_new",
            )
        except ValueError as error:
            raise ParseConfigInvalidError from error
        if normalized.parser_code == "mineru_precision_api":
            if self._mineru_settings is None:
                raise RuntimeError("MinerU settings are not configured")
            settings = self._mineru_settings.get(session, now=now)
            if settings.cloud_processing_confirmed_at is None:
                raise MinerUCloudConsentRequiredError

        if reuse_policy == "reuse_if_exact":
            existing = self._repository.find_exact_version(
                session,
                source_id=source.id,
                source_sha256=source.sha256,
                parser_code=normalized.parser_code,
                parser_version=normalized.parser_version,
                config_hash=normalized.config_hash,
                statuses=REUSABLE_PARSE_STATUSES,
            )
            if existing is not None:
                return ParseRequestResult(version=existing, reused=True)

        version_id = uuid4()
        version_number = self._repository.next_version_number(session, source.id)
        operation = self._tasks.create_operation(
            session,
            task_type="source_parse",
            target_type="parsed_source_version",
            target_id=version_id,
            target_revision=version_number,
            business_key=(
                f"source.parse:{source.id}:{source.sha256}:{normalized.parser_code}:"
                f"{normalized.parser_version}:{normalized.config_hash}:{reuse_policy}:"
                f"{version_number}"
            ),
            event_type="parsing.source.requested",
            payload={
                "parsedSourceVersionId": str(version_id),
                "dataSourceId": str(source.id),
                "versionNumber": version_number,
            },
            now=now,
            expires_at=now + timedelta(days=self._operation_retention_days),
        )
        snapshot = dict(normalized.snapshot)
        snapshot["executionIntent"] = {
            "reusePolicy": reuse_policy,
            "noCache": reuse_policy == "force_new",
        }
        version = ParsedSourceVersion(
            id=version_id,
            data_source_id=source.id,
            version_number=version_number,
            parser_code=normalized.parser_code,
            parser_version=normalized.parser_version,
            normalizer_version=normalized.normalizer_version,
            config_snapshot=snapshot,
            config_hash=normalized.config_hash,
            source_sha256=source.sha256,
            status="queued",
            quality_level=None,
            progress_current=None,
            progress_total=None,
            progress_unit=None,
            page_count=0,
            block_count=0,
            asset_count=0,
            markdown_char_count=0,
            feature_flags=dict(EMPTY_FEATURE_FLAGS),
            error_code=None,
            error_message=None,
            retryable=False,
            operation_id=operation.id,
            started_at=None,
            finished_at=None,
            created_at=now,
        )
        self._repository.add_version(session, version)
        return ParseRequestResult(version=version, reused=False)

    def rename(
        self,
        session: Session,
        source_id: UUID,
        *,
        expected_revision: int,
        display_name: str,
        administrator_id: UUID,
        now: datetime,
        trace_id: UUID | None,
        source_ip: str | None,
        user_agent: str | None,
    ) -> DataSourceDetails:
        source = self._repository.get_source(session, source_id, for_update=True)
        if source is None:
            raise DataSourceNotFoundError
        if source.revision != expected_revision:
            raise DataSourceRevisionConflictError
        source.display_name = display_name
        source.revision += 1
        source.updated_at = now
        self._repository.save_source(session, source)
        self._audits.record(
            session,
            occurred_at=now,
            actor_id=administrator_id,
            event_code="data_source.renamed",
            target_id=source.id,
            target_name=source.display_name,
            change_summary={"displayName": source.display_name},
            trace_id=trace_id,
            source_ip=source_ip,
            user_agent=user_agent,
        )
        return self._details(session, source)

    def get_parsed_version(
        self,
        session: Session,
        version_id: UUID,
    ) -> ParsedSourceVersionDetails:
        details = self._repository.get_parsed_version(session, version_id)
        if details is None:
            raise ParsedSourceVersionNotFoundError
        return details

    def get_parsed_markdown(
        self,
        session: Session,
        version_id: UUID,
    ) -> ParsedSourceVersionDetails:
        details = self.get_parsed_version(session, version_id)
        self._require_selectable(details)
        if details.normalized_storage_key is None:
            raise ParsedVersionNotSelectableError
        return details

    def list_parsed_blocks(
        self,
        session: Session,
        version_id: UUID,
        *,
        page_number: int | None,
        block_type: str | None,
        page: int,
        page_size: int,
    ) -> tuple[Sequence[ParsedBlock], int]:
        details = self.get_parsed_version(session, version_id)
        self._require_selectable(details)
        return self._repository.list_parsed_blocks(
            session,
            version_id,
            page_number=page_number,
            block_type=block_type,
            page=page,
            page_size=page_size,
        )

    def list_parsed_assets(
        self,
        session: Session,
        version_id: UUID,
        *,
        page: int,
        page_size: int,
    ) -> tuple[Sequence[ParsedAsset], int]:
        details = self.get_parsed_version(session, version_id)
        self._require_selectable(details)
        return self._repository.list_parsed_assets(
            session,
            version_id,
            page=page,
            page_size=page_size,
        )

    def get_parsed_asset(
        self,
        session: Session,
        version_id: UUID,
        asset_id: UUID,
    ) -> ParsedAsset:
        details = self.get_parsed_version(session, version_id)
        asset = self._repository.get_parsed_asset(session, version_id, asset_id)
        if asset is None:
            raise ParsedSourceVersionNotFoundError
        self._require_selectable(details)
        return asset

    def list_parsed_artifacts(
        self,
        session: Session,
        version_id: UUID,
    ) -> Sequence[ParsedArtifact]:
        self.get_parsed_version(session, version_id)
        return self._repository.list_parsed_artifacts(session, version_id)

    def _details(self, session: Session, source: DataSource) -> DataSourceDetails:
        blob = self._repository.get_blob(session, source.source_blob_id)
        if blob is None:
            raise RuntimeError("data source blob does not exist")
        return DataSourceDetails(
            source=source,
            blob=blob,
            version_count=self._repository.count_versions(session, source.id),
            latest_versions=tuple(self._repository.list_versions(session, source.id, limit=10)),
        )

    @staticmethod
    def _require_selectable(details: ParsedSourceVersionDetails) -> None:
        if details.version.status not in {"succeeded", "degraded"}:
            raise ParsedVersionNotSelectableError
