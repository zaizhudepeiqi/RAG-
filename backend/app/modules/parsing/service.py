from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.modules.parsing.domain import (
    DataSource,
    DataSourceDetails,
    RegisteredUpload,
    SourceBlob,
)
from app.modules.parsing.ports import DataSourceAuditRepository, StoredBlob
from app.modules.parsing.repository import (
    DataSourceListQuery,
    DataSourcePage,
    DataSourceRepository,
)


class DataSourceNotFoundError(ValueError):
    pass


class DataSourceRevisionConflictError(ValueError):
    pass


class DataSourceService:
    def __init__(
        self,
        repository: DataSourceRepository,
        audits: DataSourceAuditRepository,
    ) -> None:
        self._repository = repository
        self._audits = audits

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
            source_path=file_name,
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

    def _details(self, session: Session, source: DataSource) -> DataSourceDetails:
        blob = self._repository.get_blob(session, source.source_blob_id)
        if blob is None:
            raise RuntimeError("data source blob does not exist")
        return DataSourceDetails(
            source=source,
            blob=blob,
            version_count=self._repository.count_versions(session, source.id),
        )
