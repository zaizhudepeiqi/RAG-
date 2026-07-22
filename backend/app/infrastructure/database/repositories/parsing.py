import ipaddress
from collections.abc import Mapping
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import asc, desc, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.infrastructure.database.models.auth import AuditLogModel
from app.infrastructure.database.models.parsing import (
    DataSourceModel,
    ParsedSourceVersionModel,
    SourceBlobModel,
)
from app.modules.parsing.domain import DataSource, SourceBlob
from app.modules.parsing.repository import DataSourceListQuery, DataSourcePage


class SqlAlchemyDataSourceRepository:
    def acquire_blob(
        self,
        session: Session,
        candidate: SourceBlob,
    ) -> tuple[SourceBlob, bool]:
        created_id = session.scalar(
            insert(SourceBlobModel)
            .values(**self._blob_values(candidate))
            .on_conflict_do_nothing()
            .returning(SourceBlobModel.id)
        )
        if created_id is not None:
            return candidate, True

        model = session.scalar(
            select(SourceBlobModel)
            .where(SourceBlobModel.sha256 == candidate.sha256)
            .with_for_update()
        )
        if model is None:
            raise RuntimeError("source blob conflict did not resolve to a row")
        return self._blob_domain(model), False

    def save_blob(self, session: Session, blob: SourceBlob) -> None:
        model = session.get(SourceBlobModel, blob.id)
        if model is None:
            raise RuntimeError("source blob does not exist")
        for name, value in self._blob_values(blob).items():
            setattr(model, name, value)

    def get_blob(self, session: Session, blob_id: UUID) -> SourceBlob | None:
        model = session.get(SourceBlobModel, blob_id)
        return self._blob_domain(model) if model is not None else None

    def find_active_source_by_sha256(
        self,
        session: Session,
        sha256: str,
    ) -> DataSource | None:
        model = session.scalar(
            select(DataSourceModel)
            .where(DataSourceModel.sha256 == sha256, DataSourceModel.deleted_at.is_(None))
            .order_by(DataSourceModel.created_at, DataSourceModel.id)
            .limit(1)
        )
        return self._source_domain(model) if model is not None else None

    def add_source(self, session: Session, source: DataSource) -> None:
        session.add(DataSourceModel(**self._source_values(source)))

    def get_source(
        self,
        session: Session,
        source_id: UUID,
        *,
        for_update: bool = False,
    ) -> DataSource | None:
        statement = select(DataSourceModel).where(
            DataSourceModel.id == source_id,
            DataSourceModel.deleted_at.is_(None),
        )
        if for_update:
            statement = statement.with_for_update()
        model = session.scalar(statement)
        return self._source_domain(model) if model is not None else None

    def save_source(self, session: Session, source: DataSource) -> None:
        model = session.get(DataSourceModel, source.id)
        if model is None:
            raise RuntimeError("data source does not exist")
        for name, value in self._source_values(source).items():
            setattr(model, name, value)

    def list_sources(self, session: Session, query: DataSourceListQuery) -> DataSourcePage:
        filters: list[ColumnElement[bool]] = [DataSourceModel.deleted_at.is_(None)]
        if query.extension is not None:
            filters.append(DataSourceModel.extension == query.extension.lower())
        if query.origin_type is not None:
            filters.append(DataSourceModel.origin_type == query.origin_type)
        if query.search is not None:
            filters.append(DataSourceModel.display_name.ilike(f"%{query.search}%"))

        total = (
            session.scalar(select(func.count()).select_from(DataSourceModel).where(*filters)) or 0
        )
        sort_column = {
            "display_name": asc(func.lower(DataSourceModel.display_name)),
            "-display_name": desc(func.lower(DataSourceModel.display_name)),
            "created_at": asc(DataSourceModel.created_at),
            "-created_at": desc(DataSourceModel.created_at),
        }[query.sort]
        models = session.scalars(
            select(DataSourceModel)
            .where(*filters)
            .order_by(sort_column, DataSourceModel.id)
            .offset((query.page - 1) * query.page_size)
            .limit(query.page_size)
        ).all()
        return DataSourcePage(
            items=[self._source_domain(model) for model in models],
            total=total,
            page=query.page,
            page_size=query.page_size,
        )

    def count_versions(self, session: Session, source_id: UUID) -> int:
        return (
            session.scalar(
                select(func.count())
                .select_from(ParsedSourceVersionModel)
                .where(ParsedSourceVersionModel.data_source_id == source_id)
            )
            or 0
        )

    @staticmethod
    def _blob_values(blob: SourceBlob) -> dict[str, object]:
        return {
            "id": blob.id,
            "sha256": blob.sha256,
            "size_bytes": blob.size_bytes,
            "storage_key": blob.storage_key,
            "mime_type": blob.mime_type,
            "reference_count": blob.reference_count,
            "created_at": blob.created_at,
            "last_referenced_at": blob.last_referenced_at,
            "purge_after": blob.purge_after,
        }

    @staticmethod
    def _source_values(source: DataSource) -> dict[str, object]:
        return {
            "id": source.id,
            "source_blob_id": source.source_blob_id,
            "display_name": source.display_name,
            "source_path": source.source_path,
            "original_file_name": source.original_file_name,
            "extension": source.extension,
            "mime_type": source.mime_type,
            "size_bytes": source.size_bytes,
            "sha256": source.sha256,
            "origin_type": source.origin_type,
            "origin_ref": source.origin_ref,
            "revision": source.revision,
            "created_at": source.created_at,
            "updated_at": source.updated_at,
            "deleted_at": source.deleted_at,
        }

    @staticmethod
    def _blob_domain(model: SourceBlobModel) -> SourceBlob:
        return SourceBlob(
            id=model.id,
            sha256=model.sha256,
            size_bytes=model.size_bytes,
            storage_key=model.storage_key,
            mime_type=model.mime_type,
            reference_count=model.reference_count,
            created_at=model.created_at,
            last_referenced_at=model.last_referenced_at,
            purge_after=model.purge_after,
        )

    @staticmethod
    def _source_domain(model: DataSourceModel) -> DataSource:
        return DataSource(
            id=model.id,
            source_blob_id=model.source_blob_id,
            display_name=model.display_name,
            source_path=model.source_path,
            original_file_name=model.original_file_name,
            extension=model.extension,
            mime_type=model.mime_type,
            size_bytes=model.size_bytes,
            sha256=model.sha256,
            origin_type=model.origin_type,
            origin_ref=dict(model.origin_ref),
            revision=model.revision,
            created_at=model.created_at,
            updated_at=model.updated_at,
            deleted_at=model.deleted_at,
        )


class SqlAlchemyDataSourceAuditRepository:
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
    ) -> None:
        session.add(
            AuditLogModel(
                id=uuid4(),
                occurred_at=occurred_at,
                actor_type="administrator",
                actor_id=actor_id,
                event_code=event_code,
                target_type="data_source",
                target_id=target_id,
                target_name_snapshot=target_name,
                trace_id=trace_id,
                source_ip=self._valid_ip(source_ip),
                user_agent=user_agent,
                change_summary=dict(change_summary),
                result_status="succeeded",
            )
        )

    @staticmethod
    def _valid_ip(source_ip: str | None) -> str | None:
        if source_ip is None:
            return None
        try:
            return ipaddress.ip_address(source_ip).compressed
        except ValueError:
            return None
