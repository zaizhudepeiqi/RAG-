import hashlib
import ipaddress
from collections.abc import Mapping
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import asc, delete, desc, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from app.infrastructure.database.models.auth import AuditLogModel
from app.infrastructure.database.models.parsing import (
    DataSourceModel,
    ParsedArtifactModel,
    ParsedAssetModel,
    ParsedBlockAssetModel,
    ParsedBlockModel,
    ParsedSourceVersionModel,
    SourceBlobModel,
)
from app.infrastructure.database.models.settings import MinerUSettingsModel
from app.infrastructure.database.models.tasks import OperationModel
from app.infrastructure.database.repositories.mineru_settings import (
    SqlAlchemyMinerUSettingsRepository,
)
from app.infrastructure.database.session import transaction
from app.modules.parsing.domain import (
    TERMINAL_PARSE_STATES,
    DataSource,
    MinerURuntimeSettings,
    MinerUTestTaskSnapshot,
    ParsedArtifact,
    ParsedAsset,
    ParsedBlock,
    ParsedSourceVersion,
    ParsedSourceVersionDetails,
    ParseEvent,
    ParseState,
    ParseTaskSnapshot,
    ParsingCleanupTaskSnapshot,
    ParsingReference,
    SourceBlob,
    transition_parse_state,
)
from app.modules.parsing.normalization import NormalizedDocument
from app.modules.parsing.ports import MinerUPollResult, StoredBlob
from app.modules.parsing.repository import DataSourceListQuery, DataSourcePage
from app.modules.parsing.settings_domain import MINERU_SETTINGS_ID
from app.modules.parsing.tasks import StoredNormalizedAsset


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

    def get_blob(
        self,
        session: Session,
        blob_id: UUID,
        *,
        for_update: bool = False,
    ) -> SourceBlob | None:
        statement = select(SourceBlobModel).where(SourceBlobModel.id == blob_id)
        if for_update:
            statement = statement.with_for_update()
        model = session.scalar(statement)
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
                .where(
                    ParsedSourceVersionModel.data_source_id == source_id,
                    ~self._cleanup_requested(
                        "parsed_source_version",
                        ParsedSourceVersionModel.id,
                    ),
                )
            )
            or 0
        )

    def has_nonterminal_versions(self, session: Session, source_id: UUID) -> bool:
        return bool(
            session.scalar(
                select(
                    select(ParsedSourceVersionModel.id)
                    .where(
                        ParsedSourceVersionModel.data_source_id == source_id,
                        ~ParsedSourceVersionModel.status.in_(
                            ("succeeded", "degraded", "failed", "cancelled")
                        ),
                    )
                    .exists()
                )
            )
        )

    def find_exact_version(
        self,
        session: Session,
        *,
        source_id: UUID,
        source_sha256: str,
        parser_code: str,
        parser_version: str,
        config_hash: str,
        statuses: tuple[str, ...],
    ) -> ParsedSourceVersion | None:
        model = session.scalar(
            select(ParsedSourceVersionModel)
            .where(
                ParsedSourceVersionModel.data_source_id == source_id,
                ParsedSourceVersionModel.source_sha256 == source_sha256,
                ParsedSourceVersionModel.parser_code == parser_code,
                ParsedSourceVersionModel.parser_version == parser_version,
                ParsedSourceVersionModel.config_hash == config_hash,
                ParsedSourceVersionModel.status.in_(statuses),
            )
            .order_by(ParsedSourceVersionModel.version_number.desc())
            .limit(1)
        )
        return self._version_domain(model) if model is not None else None

    def next_version_number(self, session: Session, source_id: UUID) -> int:
        current = session.scalar(
            select(func.max(ParsedSourceVersionModel.version_number)).where(
                ParsedSourceVersionModel.data_source_id == source_id
            )
        )
        return (current or 0) + 1

    def add_version(self, session: Session, version: ParsedSourceVersion) -> None:
        session.add(
            ParsedSourceVersionModel(
                id=version.id,
                data_source_id=version.data_source_id,
                version_number=version.version_number,
                parser_code=version.parser_code,
                parser_version=version.parser_version,
                normalizer_version=version.normalizer_version,
                config_snapshot=version.config_snapshot,
                config_hash=version.config_hash,
                source_sha256=version.source_sha256,
                status=version.status,
                quality_level=version.quality_level,
                progress_current=version.progress_current,
                progress_total=version.progress_total,
                progress_unit=version.progress_unit,
                page_count=version.page_count,
                block_count=version.block_count,
                asset_count=version.asset_count,
                markdown_char_count=version.markdown_char_count,
                feature_flags=version.feature_flags,
                error_code=version.error_code,
                error_message=version.error_message,
                retryable=version.retryable,
                operation_id=version.operation_id,
                started_at=version.started_at,
                finished_at=version.finished_at,
                created_at=version.created_at,
            )
        )

    def list_versions(
        self,
        session: Session,
        source_id: UUID,
        *,
        limit: int,
    ) -> list[ParsedSourceVersion]:
        models = session.scalars(
            select(ParsedSourceVersionModel)
            .where(
                ParsedSourceVersionModel.data_source_id == source_id,
                ~self._cleanup_requested(
                    "parsed_source_version",
                    ParsedSourceVersionModel.id,
                ),
            )
            .order_by(ParsedSourceVersionModel.version_number.desc())
            .limit(limit)
        ).all()
        return [self._version_domain(model) for model in models]

    def get_parsed_version(
        self,
        session: Session,
        version_id: UUID,
        *,
        for_update: bool = False,
    ) -> ParsedSourceVersionDetails | None:
        statement = select(ParsedSourceVersionModel).where(
            ParsedSourceVersionModel.id == version_id,
            ParsedSourceVersionModel.data_source_id.in_(
                select(DataSourceModel.id).where(DataSourceModel.deleted_at.is_(None))
            ),
            ~self._cleanup_requested(
                "parsed_source_version",
                ParsedSourceVersionModel.id,
            ),
        )
        if for_update:
            statement = statement.with_for_update()
        model = session.scalar(statement)
        if model is None:
            return None
        return ParsedSourceVersionDetails(
            version=self._version_domain(model),
            provider_batch_id=model.provider_batch_id,
            provider_task_id=model.provider_task_id,
            provider_data_id=model.provider_data_id,
            provider_trace_id=model.provider_trace_id,
            normalized_storage_key=model.normalized_storage_key,
        )

    def resume_provider_query(
        self,
        session: Session,
        version_id: UUID,
        operation_id: UUID,
    ) -> ParsedSourceVersion:
        model = session.get(ParsedSourceVersionModel, version_id)
        if model is None:
            raise RuntimeError("parsed source version does not exist")
        model.status = transition_parse_state(
            ParseState(model.status),
            ParseEvent.RESUME_PROVIDER_QUERY,
        ).value
        model.operation_id = operation_id
        model.error_code = None
        model.error_message = None
        model.retryable = False
        model.finished_at = None
        return self._version_domain(model)

    def list_parsed_blocks(
        self,
        session: Session,
        version_id: UUID,
        *,
        page_number: int | None,
        block_type: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[ParsedBlock], int]:
        filters: list[ColumnElement[bool]] = [
            ParsedBlockModel.parsed_source_version_id == version_id
        ]
        if page_number is not None:
            filters.append(ParsedBlockModel.page_number == page_number)
        if block_type is not None:
            filters.append(ParsedBlockModel.block_type == block_type)
        total = (
            session.scalar(select(func.count()).select_from(ParsedBlockModel).where(*filters)) or 0
        )
        models = session.scalars(
            select(ParsedBlockModel)
            .where(*filters)
            .order_by(ParsedBlockModel.order_index, ParsedBlockModel.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        asset_ids: dict[UUID, list[UUID]] = {model.id: [] for model in models}
        if asset_ids:
            links = session.execute(
                select(
                    ParsedBlockAssetModel.block_id,
                    ParsedBlockAssetModel.asset_id,
                )
                .join(ParsedAssetModel, ParsedAssetModel.id == ParsedBlockAssetModel.asset_id)
                .where(ParsedBlockAssetModel.block_id.in_(asset_ids))
                .order_by(ParsedAssetModel.order_index, ParsedAssetModel.id)
            ).all()
            for block_id, asset_id in links:
                asset_ids[block_id].append(asset_id)
        return (
            [
                ParsedBlock(
                    id=model.id,
                    block_type=model.block_type,
                    order_index=model.order_index,
                    text_content=model.text_content,
                    markdown_content=model.markdown_content,
                    heading_level=model.heading_level,
                    heading_path=(tuple(model.heading_path) if model.heading_path else None),
                    page_number=model.page_number,
                    bounding_box=(dict(model.bounding_box) if model.bounding_box else None),
                    raw_locator=(dict(model.raw_locator) if model.raw_locator else None),
                    asset_ids=tuple(asset_ids[model.id]),
                )
                for model in models
            ],
            total,
        )

    def list_parsed_assets(
        self,
        session: Session,
        version_id: UUID,
        *,
        page: int,
        page_size: int,
    ) -> tuple[list[ParsedAsset], int]:
        condition = ParsedAssetModel.parsed_source_version_id == version_id
        total = (
            session.scalar(select(func.count()).select_from(ParsedAssetModel).where(condition)) or 0
        )
        models = session.scalars(
            select(ParsedAssetModel)
            .where(condition)
            .order_by(ParsedAssetModel.order_index, ParsedAssetModel.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return [self._asset_domain(model) for model in models], total

    def get_parsed_asset(
        self,
        session: Session,
        version_id: UUID,
        asset_id: UUID,
    ) -> ParsedAsset | None:
        model = session.scalar(
            select(ParsedAssetModel).where(
                ParsedAssetModel.id == asset_id,
                ParsedAssetModel.parsed_source_version_id == version_id,
            )
        )
        return self._asset_domain(model) if model is not None else None

    def list_parsed_artifacts(
        self,
        session: Session,
        version_id: UUID,
    ) -> list[ParsedArtifact]:
        models = session.scalars(
            select(ParsedArtifactModel)
            .where(ParsedArtifactModel.parsed_source_version_id == version_id)
            .order_by(ParsedArtifactModel.artifact_type, ParsedArtifactModel.id)
        ).all()
        return [
            ParsedArtifact(
                id=model.id,
                artifact_type=model.artifact_type,
                display_name=model.display_name,
                storage_key=model.storage_key,
                sha256=model.sha256,
                size_bytes=model.size_bytes,
                is_downloadable=model.is_downloadable,
                created_at=model.created_at,
            )
            for model in models
        ]

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

    @staticmethod
    def _asset_domain(model: ParsedAssetModel) -> ParsedAsset:
        return ParsedAsset(
            id=model.id,
            asset_type=model.asset_type,
            mime_type=model.mime_type,
            page_number=model.page_number,
            bounding_box=(dict(model.bounding_box) if model.bounding_box else None),
            storage_key=model.storage_key,
            sha256=model.sha256,
            size_bytes=model.size_bytes,
            caption=model.caption,
            ocr_text=model.ocr_text,
            order_index=model.order_index,
        )

    @staticmethod
    def _version_domain(model: ParsedSourceVersionModel) -> ParsedSourceVersion:
        return ParsedSourceVersion(
            id=model.id,
            data_source_id=model.data_source_id,
            version_number=model.version_number,
            parser_code=model.parser_code,
            parser_version=model.parser_version,
            normalizer_version=model.normalizer_version,
            config_snapshot=dict(model.config_snapshot),
            config_hash=model.config_hash,
            source_sha256=model.source_sha256,
            status=model.status,
            quality_level=model.quality_level,
            progress_current=model.progress_current,
            progress_total=model.progress_total,
            progress_unit=model.progress_unit,
            page_count=model.page_count,
            block_count=model.block_count,
            asset_count=model.asset_count,
            markdown_char_count=model.markdown_char_count,
            feature_flags=dict(model.feature_flags),
            error_code=model.error_code,
            error_message=model.error_message,
            retryable=model.retryable,
            operation_id=model.operation_id,
            started_at=model.started_at,
            finished_at=model.finished_at,
            created_at=model.created_at,
        )

    @staticmethod
    def _cleanup_requested(target_type: str, target_id: object) -> ColumnElement[bool]:
        return (
            select(OperationModel.id)
            .where(
                OperationModel.task_type == "parsing_cleanup",
                OperationModel.target_type == target_type,
                OperationModel.target_id == target_id,
                OperationModel.status != "cancelled",
            )
            .exists()
        )


class SqlAlchemyParsingReferenceQuery:
    """Phase 3 replaces these empty queries with knowledge-base-owned lookups."""

    def for_data_source(
        self,
        _session: Session,
        _data_source_id: UUID,
    ) -> tuple[ParsingReference, ...]:
        return ()

    def for_parsed_version(
        self,
        _session: Session,
        _parsed_source_version_id: UUID,
    ) -> tuple[ParsingReference, ...]:
        return ()


class SqlAlchemyParsingCleanupTaskStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def load(
        self,
        operation_id: UUID,
        now: datetime,
    ) -> ParsingCleanupTaskSnapshot | None:
        with transaction(self._session_factory) as session:
            operation = session.get(OperationModel, operation_id)
            if operation is None or operation.task_type != "parsing_cleanup":
                return None
            source_blob_id: UUID | None = None
            source_blob_storage_key: str | None = None
            if operation.target_type == "data_source":
                source = session.get(DataSourceModel, operation.target_id)
                if source is None or source.deleted_at is None:
                    return None
                version_ids = tuple(
                    session.scalars(
                        select(ParsedSourceVersionModel.id).where(
                            ParsedSourceVersionModel.data_source_id == source.id
                        )
                    ).all()
                )
                source_blob_id = source.source_blob_id
                blob = session.get(SourceBlobModel, source.source_blob_id)
                if (
                    blob is not None
                    and blob.reference_count == 0
                    and blob.purge_after is not None
                    and blob.purge_after <= now
                ):
                    source_blob_storage_key = blob.storage_key
            elif operation.target_type == "parsed_source_version":
                version = session.get(ParsedSourceVersionModel, operation.target_id)
                version_ids = (version.id,) if version is not None else ()
            else:
                return None
            storage_keys = self._unshared_storage_keys(session, version_ids)
            return ParsingCleanupTaskSnapshot(
                operation_id=operation_id,
                target_type=operation.target_type,
                target_id=operation.target_id,
                version_ids=version_ids,
                storage_keys=storage_keys,
                source_blob_id=source_blob_id,
                source_blob_storage_key=source_blob_storage_key,
            )

    def finalize(self, snapshot: ParsingCleanupTaskSnapshot) -> int:
        if not snapshot.version_ids:
            return 0
        with transaction(self._session_factory) as session:
            block_ids = select(ParsedBlockModel.id).where(
                ParsedBlockModel.parsed_source_version_id.in_(snapshot.version_ids)
            )
            asset_ids = select(ParsedAssetModel.id).where(
                ParsedAssetModel.parsed_source_version_id.in_(snapshot.version_ids)
            )
            session.execute(
                delete(ParsedBlockAssetModel).where(
                    or_(
                        ParsedBlockAssetModel.block_id.in_(block_ids),
                        ParsedBlockAssetModel.asset_id.in_(asset_ids),
                    )
                )
            )
            for model in (ParsedBlockModel, ParsedAssetModel, ParsedArtifactModel):
                session.execute(
                    delete(model).where(model.parsed_source_version_id.in_(snapshot.version_ids))
                )
            result = session.execute(
                delete(ParsedSourceVersionModel).where(
                    ParsedSourceVersionModel.id.in_(snapshot.version_ids)
                )
            )
            return result.rowcount  # type: ignore[attr-defined,no-any-return]

    @staticmethod
    def _unshared_storage_keys(
        session: Session,
        version_ids: tuple[UUID, ...],
    ) -> tuple[str, ...]:
        if not version_ids:
            return ()
        versions = session.scalars(
            select(ParsedSourceVersionModel).where(ParsedSourceVersionModel.id.in_(version_ids))
        ).all()
        candidates = {
            key
            for version in versions
            for key in (version.raw_result_storage_key, version.normalized_storage_key)
            if key is not None
        }
        candidates.update(
            session.scalars(
                select(ParsedAssetModel.storage_key).where(
                    ParsedAssetModel.parsed_source_version_id.in_(version_ids)
                )
            ).all()
        )
        candidates.update(
            session.scalars(
                select(ParsedArtifactModel.storage_key).where(
                    ParsedArtifactModel.parsed_source_version_id.in_(version_ids)
                )
            ).all()
        )
        removable: list[str] = []
        for key in sorted(candidates):
            referenced = session.scalar(
                select(
                    or_(
                        select(SourceBlobModel.id)
                        .where(SourceBlobModel.storage_key == key)
                        .exists(),
                        select(ParsedSourceVersionModel.id)
                        .where(
                            ParsedSourceVersionModel.id.not_in(version_ids),
                            or_(
                                ParsedSourceVersionModel.raw_result_storage_key == key,
                                ParsedSourceVersionModel.normalized_storage_key == key,
                            ),
                        )
                        .exists(),
                        select(ParsedAssetModel.id)
                        .where(
                            ParsedAssetModel.parsed_source_version_id.not_in(version_ids),
                            ParsedAssetModel.storage_key == key,
                        )
                        .exists(),
                        select(ParsedArtifactModel.id)
                        .where(
                            ParsedArtifactModel.parsed_source_version_id.not_in(version_ids),
                            ParsedArtifactModel.storage_key == key,
                        )
                        .exists(),
                    )
                )
            )
            if not referenced:
                removable.append(key)
        return tuple(removable)


class SqlAlchemyMinerUTestTaskStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def load(self, operation_id: UUID) -> MinerUTestTaskSnapshot | None:
        with transaction(self._session_factory) as session:
            operation = session.get(OperationModel, operation_id)
            if (
                operation is None
                or operation.task_type != "mineru_connection_test"
                or operation.target_type != "mineru_settings"
                or operation.target_id != MINERU_SETTINGS_ID
            ):
                return None
            settings = SqlAlchemyMinerUSettingsRepository().get_for_update(
                session,
                MINERU_SETTINGS_ID,
            )
            if settings is None or operation.target_revision != settings.revision:
                return None
            return MinerUTestTaskSnapshot(operation_id=operation_id, settings=settings)


class SqlAlchemyParseTaskStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def load(self, operation_id: UUID) -> ParseTaskSnapshot | None:
        with transaction(self._session_factory) as session:
            row = session.execute(
                select(ParsedSourceVersionModel, DataSourceModel, SourceBlobModel)
                .join(
                    DataSourceModel,
                    DataSourceModel.id == ParsedSourceVersionModel.data_source_id,
                )
                .join(SourceBlobModel, SourceBlobModel.id == DataSourceModel.source_blob_id)
                .where(ParsedSourceVersionModel.operation_id == operation_id)
            ).one_or_none()
            if row is None:
                return None
            version, source, blob = row
            settings_model = (
                session.get(MinerUSettingsModel, MINERU_SETTINGS_ID)
                if version.parser_code == "mineru_precision_api"
                else None
            )
            mineru_settings = (
                MinerURuntimeSettings(
                    id=settings_model.id,
                    base_url=settings_model.base_url,
                    token_ciphertext=settings_model.token_ciphertext,
                    token_nonce=settings_model.token_nonce,
                    token_key_version=settings_model.token_key_version,
                    poll_timeout_seconds=settings_model.poll_timeout_seconds,
                    cloud_processing_confirmed=(
                        settings_model.cloud_processing_confirmed_at is not None
                    ),
                )
                if settings_model is not None
                else None
            )
            return ParseTaskSnapshot(
                operation_id=operation_id,
                version_id=version.id,
                parser_code=version.parser_code,
                parser_version=version.parser_version,
                extension=source.extension,
                source_storage_key=blob.storage_key,
                source_file_name=source.original_file_name,
                config_snapshot=dict(version.config_snapshot),
                status=ParseState(version.status),
                provider_batch_id=version.provider_batch_id,
                provider_task_id=version.provider_task_id,
                provider_data_id=version.provider_data_id,
                provider_trace_id=version.provider_trace_id,
                raw_result_storage_key=version.raw_result_storage_key,
                mineru_settings=mineru_settings,
            )

    def start_mineru(self, version_id: UUID, data_id: str, started_at: datetime) -> bool:
        with transaction(self._session_factory) as session:
            model = self._locked_version(session, version_id)
            if model is None:
                return False
            state = ParseState(model.status)
            if state is ParseState.SUBMITTING:
                if model.provider_data_id != data_id:
                    raise RuntimeError("MinerU data checkpoint changed")
                return False
            if state is not ParseState.QUEUED:
                return False
            model.status = transition_parse_state(state, ParseEvent.SUBMIT).value
            model.provider_data_id = data_id
            model.started_at = model.started_at or started_at
            return True

    def save_upload_checkpoint(
        self,
        version_id: UUID,
        *,
        batch_id: str,
        data_id: str,
        trace_id: str | None,
    ) -> bool:
        with transaction(self._session_factory) as session:
            model = self._locked_version(session, version_id)
            if model is None:
                return False
            if model.provider_data_id != data_id:
                raise RuntimeError("MinerU data checkpoint changed")
            state = ParseState(model.status)
            if state is ParseState.UPLOADING:
                if model.provider_batch_id != batch_id:
                    raise RuntimeError("MinerU batch checkpoint changed")
                return False
            if state is not ParseState.SUBMITTING:
                return False
            model.status = transition_parse_state(state, ParseEvent.UPLOAD).value
            model.provider_batch_id = batch_id
            model.provider_trace_id = trace_id or model.provider_trace_id
            return True

    def mark_provider_pending(self, version_id: UUID) -> bool:
        with transaction(self._session_factory) as session:
            model = self._locked_version(session, version_id)
            if model is None:
                return False
            state = ParseState(model.status)
            if state in {
                ParseState.PROVIDER_PENDING,
                ParseState.PARSING,
                ParseState.DOWNLOADING,
                ParseState.NORMALIZING,
            }:
                return False
            if state is not ParseState.UPLOADING:
                return False
            model.status = transition_parse_state(state, ParseEvent.WAIT_PROVIDER).value
            return True

    def save_provider_poll(self, version_id: UUID, result: MinerUPollResult) -> ParseState:
        with transaction(self._session_factory) as session:
            model = self._locked_version(session, version_id)
            if model is None:
                raise RuntimeError("parsed source version does not exist")
            if (
                model.provider_batch_id != result.batch_id
                or model.provider_data_id != result.data_id
            ):
                raise RuntimeError("MinerU poll checkpoint changed")
            if result.provider_task_id is not None:
                model.provider_task_id = result.provider_task_id
            if result.trace_id is not None:
                model.provider_trace_id = result.trace_id
            if result.progress_current is not None or result.progress_total is not None:
                if (
                    result.progress_current is None
                    or result.progress_total is None
                    or result.progress_current < 0
                    or result.progress_total < 1
                    or result.progress_current > result.progress_total
                ):
                    raise RuntimeError("MinerU progress is invalid")
                model.progress_current = result.progress_current
                model.progress_total = result.progress_total
                model.progress_unit = "pages"

            state = ParseState(model.status)
            if result.state in {"running", "converting"}:
                if state is ParseState.PROVIDER_PENDING:
                    event = (
                        ParseEvent.PROVIDER_RUNNING
                        if result.state == "running"
                        else ParseEvent.PROVIDER_CONVERTING
                    )
                    state = transition_parse_state(state, event)
                elif state is ParseState.PARSING:
                    event = (
                        ParseEvent.PROVIDER_RUNNING
                        if result.state == "running"
                        else ParseEvent.PROVIDER_CONVERTING
                    )
                    state = transition_parse_state(state, event)
            elif result.state == "done" and state in {
                ParseState.PROVIDER_PENDING,
                ParseState.PARSING,
            }:
                state = transition_parse_state(state, ParseEvent.DOWNLOAD)
            model.status = state.value
            return state

    def save_raw_result(self, version_id: UUID, result: StoredBlob) -> bool:
        with transaction(self._session_factory) as session:
            model = self._locked_version(session, version_id)
            if model is None:
                return False
            state = ParseState(model.status)
            if state is ParseState.NORMALIZING:
                if model.raw_result_storage_key != result.storage_key:
                    raise RuntimeError("raw result checkpoint changed")
                return False
            if state is not ParseState.DOWNLOADING:
                return False
            model.raw_result_storage_key = result.storage_key
            model.status = transition_parse_state(state, ParseEvent.NORMALIZE).value
            session.add(
                ParsedArtifactModel(
                    id=uuid4(),
                    parsed_source_version_id=model.id,
                    artifact_type="mineru_full_zip",
                    display_name="mineru-full.zip",
                    storage_key=result.storage_key,
                    sha256=result.sha256,
                    size_bytes=result.size_bytes,
                    is_downloadable=False,
                )
            )
            return True

    def mark_normalizing(self, version_id: UUID) -> bool:
        with transaction(self._session_factory) as session:
            model = self._locked_version(session, version_id)
            if model is None:
                return False
            state = ParseState(model.status)
            if state is ParseState.NORMALIZING:
                return True
            if state is not ParseState.QUEUED:
                return False
            model.status = transition_parse_state(state, ParseEvent.NORMALIZE).value
            return True

    def save_succeeded(
        self,
        snapshot: ParseTaskSnapshot,
        document: NormalizedDocument,
        markdown_artifact: StoredBlob,
        finished_at: datetime,
        assets: tuple[StoredNormalizedAsset, ...] = (),
    ) -> bool:
        with transaction(self._session_factory) as session:
            model = session.scalar(
                select(ParsedSourceVersionModel)
                .where(ParsedSourceVersionModel.id == snapshot.version_id)
                .with_for_update()
            )
            if model is None or model.status in {"succeeded", "degraded"}:
                return False
            if model.status != "normalizing":
                raise RuntimeError("parsed source version is not normalizing")
            asset_ids: dict[str, UUID] = {}
            for item in assets:
                asset_id = uuid4()
                asset_ids[item.asset.source_path] = asset_id
                session.add(
                    ParsedAssetModel(
                        id=asset_id,
                        parsed_source_version_id=model.id,
                        asset_type=item.asset.asset_type,
                        mime_type=item.asset.mime_type,
                        page_number=item.asset.page_number,
                        bounding_box=item.asset.bounding_box,
                        storage_key=item.stored.storage_key,
                        sha256=item.stored.sha256,
                        size_bytes=item.stored.size_bytes,
                        caption=item.asset.caption,
                        ocr_text=item.asset.ocr_text,
                        order_index=item.asset.order_index,
                        created_at=finished_at,
                    )
                )
            for block in document.blocks:
                content = block.markdown_content or block.text_content or ""
                block_id = uuid4()
                session.add(
                    ParsedBlockModel(
                        id=block_id,
                        parsed_source_version_id=model.id,
                        block_type=block.block_type,
                        order_index=block.order_index,
                        text_content=block.text_content,
                        markdown_content=block.markdown_content,
                        heading_level=block.heading_level,
                        heading_path=(list(block.heading_path) if block.heading_path else None),
                        page_number=block.page_number,
                        bounding_box=block.bounding_box,
                        raw_locator=block.raw_locator,
                        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                        created_at=finished_at,
                    )
                )
                for source_path in block.asset_source_paths:
                    linked_asset_id = asset_ids.get(source_path)
                    if linked_asset_id is None:
                        raise RuntimeError("normalized block references an unknown asset")
                    session.add(
                        ParsedBlockAssetModel(
                            block_id=block_id,
                            asset_id=linked_asset_id,
                        )
                    )
            session.add(
                ParsedArtifactModel(
                    id=uuid4(),
                    parsed_source_version_id=model.id,
                    artifact_type="markdown",
                    display_name="normalized.md",
                    storage_key=markdown_artifact.storage_key,
                    sha256=markdown_artifact.sha256,
                    size_bytes=markdown_artifact.size_bytes,
                    is_downloadable=True,
                    created_at=finished_at,
                )
            )
            event = ParseEvent.SUCCEED if document.quality_level == "full" else ParseEvent.DEGRADE
            model.status = transition_parse_state(ParseState(model.status), event).value
            model.quality_level = document.quality_level
            model.normalized_storage_key = markdown_artifact.storage_key
            model.page_count = document.page_count
            model.block_count = len(document.blocks)
            model.asset_count = len(assets)
            model.markdown_char_count = len(document.markdown)
            model.feature_flags = document.feature_flags
            model.finished_at = finished_at
            model.error_code = None
            model.error_message = None
            model.retryable = False
            return True

    def save_failed(
        self,
        version_id: UUID,
        *,
        error_code: str,
        retryable: bool,
        finished_at: datetime,
    ) -> None:
        with transaction(self._session_factory) as session:
            model = session.get(ParsedSourceVersionModel, version_id)
            if model is None or ParseState(model.status) in TERMINAL_PARSE_STATES:
                return
            model.status = transition_parse_state(
                ParseState(model.status),
                ParseEvent.FAIL,
            ).value
            model.error_code = error_code
            model.error_message = "解析输入无效" if not retryable else "解析暂时失败"
            model.retryable = retryable
            model.finished_at = finished_at

    @staticmethod
    def _locked_version(
        session: Session,
        version_id: UUID,
    ) -> ParsedSourceVersionModel | None:
        return session.scalar(
            select(ParsedSourceVersionModel)
            .where(ParsedSourceVersionModel.id == version_id)
            .with_for_update()
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
