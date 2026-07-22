from collections.abc import Iterator
from datetime import UTC, datetime
from enum import IntEnum
from typing import Annotated, BinaryIO, Literal, Protocol, cast
from urllib.parse import quote
from uuid import UUID
from zipfile import BadZipFile

from fastapi import APIRouter, Depends, File, Form, Path, Query, Request, UploadFile
from pydantic import ValidationError
from sqlalchemy.orm import Session, sessionmaker
from starlette.responses import StreamingResponse

from app.core.errors import AppError
from app.infrastructure.database.session import transaction
from app.infrastructure.storage.local import EmptyStorageObjectError, StorageLimitExceededError
from app.modules.auth.dependencies import require_admin, require_csrf
from app.modules.auth.domain import Administrator
from app.modules.capabilities.registry import INPUT_TYPE_MIME_TYPES
from app.modules.parsing.archive import UnsafeArchiveError, open_safe_archive
from app.modules.parsing.ports import SourceStorage
from app.modules.parsing.repository import DataSourceListQuery
from app.modules.parsing.schemas import (
    DataSourceDetail,
    DataSourcePageView,
    RejectedUploadView,
    UpdateDataSourceRequest,
    UploadBatchResult,
    UploadedDataSourceView,
    UploadOptions,
    data_source_detail,
    data_source_summary,
    uploaded_data_source_view,
)
from app.modules.parsing.service import (
    DataSourceNotFoundError,
    DataSourceRevisionConflictError,
    DataSourceService,
)
from app.modules.parsing.validation import (
    SourceTypeMismatchError,
    SourceTypeUnsupportedError,
    inspect_source,
)

MAX_UPLOAD_FILES = 20
MAX_SOURCE_BYTES = 200 * 1024 * 1024


class DataSourceDependencies(Protocol):
    session_factory: sessionmaker[Session]
    data_source_service: DataSourceService
    source_storage: SourceStorage


class PageSize(IntEnum):
    DEFAULT = 20
    MEDIUM = 50
    LARGE = 100


router = APIRouter(
    prefix="/api/v1/data-sources",
    tags=["数据源"],
    dependencies=[Depends(require_admin)],
)


def get_dependencies(request: Request) -> DataSourceDependencies:
    return cast(DataSourceDependencies, request.app.state.dependencies)


@router.post(
    "/uploads",
    response_model=UploadBatchResult,
    operation_id="dataSourcesUpload",
    dependencies=[Depends(require_csrf)],
)
def upload_data_sources(
    files: Annotated[list[UploadFile], File()],
    request: Request,
    administrator: Annotated[Administrator, Depends(require_admin)],
    dependencies: Annotated[DataSourceDependencies, Depends(get_dependencies)],
    options: Annotated[str, Form()] = "{}",
) -> UploadBatchResult:
    if len(files) > MAX_UPLOAD_FILES:
        raise AppError(
            code="SOURCE_UPLOAD_BATCH_TOO_LARGE",
            message="单次最多上传 20 个文件",
            status_code=413,
        )
    try:
        parsed_options = UploadOptions.model_validate_json(options)
    except ValidationError as error:
        raise AppError(
            code="VALIDATION_ERROR",
            message="上传选项校验失败",
            status_code=422,
        ) from error

    accepted: list[UploadedDataSourceView] = []
    rejected: list[RejectedUploadView] = []
    for uploaded_file in files:
        file_name = uploaded_file.filename or ""
        try:
            inspected = inspect_source(
                file_name,
                uploaded_file.content_type or "application/octet-stream",
                uploaded_file.file,
            )
            if inspected.extension == "zip":
                _expand_archive(
                    uploaded_file.file,
                    options=parsed_options,
                    request=request,
                    administrator=administrator,
                    dependencies=dependencies,
                    accepted=accepted,
                    rejected=rejected,
                )
            else:
                accepted.append(
                    _store_source(
                        uploaded_file.file,
                        file_name=file_name,
                        source_path=file_name,
                        extension=inspected.extension,
                        mime_type=inspected.mime_type,
                        options=parsed_options,
                        request=request,
                        administrator=administrator,
                        dependencies=dependencies,
                    )
                )
        except UnsafeArchiveError:
            rejected.append(
                RejectedUploadView(
                    file_name=file_name,
                    code="SOURCE_ARCHIVE_UNSAFE",
                    message="ZIP 文件未通过安全检查",
                )
            )
        except (
            SourceTypeUnsupportedError,
            SourceTypeMismatchError,
            EmptyStorageObjectError,
            StorageLimitExceededError,
        ) as error:
            rejected.append(_source_rejection(file_name, error))
        finally:
            uploaded_file.file.close()

    result = UploadBatchResult(accepted=accepted, rejected=rejected)
    if not accepted:
        raise AppError(
            code="SOURCE_UPLOAD_REJECTED",
            message="所有文件均未通过上传校验",
            status_code=422,
            details={"rejected": [item.model_dump(mode="json") for item in rejected]},
        )
    return result


def _expand_archive(
    stream: BinaryIO,
    *,
    options: UploadOptions,
    request: Request,
    administrator: Administrator,
    dependencies: DataSourceDependencies,
    accepted: list[UploadedDataSourceView],
    rejected: list[RejectedUploadView],
) -> None:
    with open_safe_archive(stream) as archive:
        for entry in archive.entries:
            try:
                with archive.open_entry(entry) as entry_stream:
                    inspected = inspect_source(
                        entry.original_file_name,
                        _archive_entry_mime(entry.original_file_name),
                        entry_stream,
                    )
                    accepted.append(
                        _store_source(
                            entry_stream,
                            file_name=entry.original_file_name,
                            source_path=entry.source_path,
                            extension=inspected.extension,
                            mime_type=inspected.mime_type,
                            options=options,
                            request=request,
                            administrator=administrator,
                            dependencies=dependencies,
                        )
                    )
            except (
                SourceTypeUnsupportedError,
                SourceTypeMismatchError,
                EmptyStorageObjectError,
                StorageLimitExceededError,
            ) as error:
                rejected.append(_source_rejection(entry.source_path, error))
            except BadZipFile:
                rejected.append(
                    RejectedUploadView(
                        file_name=entry.source_path,
                        code="SOURCE_ARCHIVE_ENTRY_INVALID",
                        message="ZIP 条目损坏或无法读取",
                    )
                )


def _store_source(
    stream: BinaryIO,
    *,
    file_name: str,
    source_path: str,
    extension: str,
    mime_type: str,
    options: UploadOptions,
    request: Request,
    administrator: Administrator,
    dependencies: DataSourceDependencies,
) -> UploadedDataSourceView:
    stream.seek(0)
    stored = dependencies.source_storage.store_blob(stream, max_bytes=MAX_SOURCE_BYTES)
    with transaction(dependencies.session_factory) as session:
        registered = dependencies.data_source_service.register_upload(
            session,
            stored=stored,
            file_name=file_name,
            extension=extension,
            mime_type=mime_type,
            origin_type=options.origin_type,
            duplicate_action=options.duplicate_action,
            administrator_id=administrator.id,
            now=datetime.now(UTC),
            trace_id=_trace_id(request),
            source_ip=request.client.host if request.client is not None else None,
            user_agent=request.headers.get("User-Agent"),
            source_path=source_path,
        )
    return uploaded_data_source_view(registered)


def _source_rejection(
    file_name: str,
    error: SourceTypeUnsupportedError
    | SourceTypeMismatchError
    | EmptyStorageObjectError
    | StorageLimitExceededError,
) -> RejectedUploadView:
    if isinstance(error, (SourceTypeUnsupportedError, SourceTypeMismatchError)):
        return RejectedUploadView(
            file_name=file_name,
            code="SOURCE_TYPE_UNSUPPORTED",
            message="文件类型不受支持或与内容不匹配",
        )
    if isinstance(error, EmptyStorageObjectError):
        return RejectedUploadView(
            file_name=file_name,
            code="SOURCE_FILE_EMPTY",
            message="文件不能为空",
        )
    return RejectedUploadView(
        file_name=file_name,
        code="SOURCE_FILE_TOO_LARGE",
        message="单文件不能超过 200 MB",
    )


def _archive_entry_mime(file_name: str) -> str:
    extension = file_name.rpartition(".")[2].casefold()
    mime_types = INPUT_TYPE_MIME_TYPES.get(extension)
    return mime_types[0] if mime_types is not None else "application/octet-stream"


@router.get("", response_model=DataSourcePageView, operation_id="dataSourcesList")
def list_data_sources(
    dependencies: Annotated[DataSourceDependencies, Depends(get_dependencies)],
    extension: str | None = None,
    origin_type: Annotated[str | None, Query(alias="originType")] = None,
    search: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[PageSize, Query(alias="pageSize")] = PageSize.DEFAULT,
    sort: Literal["display_name", "-display_name", "created_at", "-created_at"] = "-created_at",
) -> DataSourcePageView:
    with transaction(dependencies.session_factory) as session:
        result, details = dependencies.data_source_service.list(
            session,
            DataSourceListQuery(
                extension=extension,
                origin_type=origin_type,
                search=search,
                page=page,
                page_size=page_size,
                sort=sort,
            ),
        )
    return DataSourcePageView(
        items=[data_source_summary(item) for item in details],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.get(
    "/{dataSourceId}",
    response_model=DataSourceDetail,
    operation_id="dataSourcesGet",
)
def get_data_source(
    data_source_id: Annotated[UUID, Path(alias="dataSourceId")],
    dependencies: Annotated[DataSourceDependencies, Depends(get_dependencies)],
) -> DataSourceDetail:
    try:
        with transaction(dependencies.session_factory) as session:
            details = dependencies.data_source_service.get(session, data_source_id)
    except DataSourceNotFoundError as error:
        raise _not_found() from error
    return data_source_detail(details)


@router.patch(
    "/{dataSourceId}",
    response_model=DataSourceDetail,
    operation_id="dataSourcesUpdate",
    dependencies=[Depends(require_csrf)],
)
def update_data_source(
    payload: UpdateDataSourceRequest,
    request: Request,
    data_source_id: Annotated[UUID, Path(alias="dataSourceId")],
    administrator: Annotated[Administrator, Depends(require_admin)],
    dependencies: Annotated[DataSourceDependencies, Depends(get_dependencies)],
) -> DataSourceDetail:
    try:
        with transaction(dependencies.session_factory) as session:
            details = dependencies.data_source_service.rename(
                session,
                data_source_id,
                expected_revision=payload.expected_revision,
                display_name=payload.display_name,
                administrator_id=administrator.id,
                now=datetime.now(UTC),
                trace_id=_trace_id(request),
                source_ip=request.client.host if request.client is not None else None,
                user_agent=request.headers.get("User-Agent"),
            )
    except DataSourceNotFoundError as error:
        raise _not_found() from error
    except DataSourceRevisionConflictError as error:
        raise AppError(
            code="REVISION_CONFLICT",
            message="数据源已被其他请求修改",
            status_code=409,
        ) from error
    return data_source_detail(details)


@router.get(
    "/{dataSourceId}/original",
    operation_id="dataSourcesOriginal",
    response_class=StreamingResponse,
)
def download_original_source(
    data_source_id: Annotated[UUID, Path(alias="dataSourceId")],
    dependencies: Annotated[DataSourceDependencies, Depends(get_dependencies)],
) -> StreamingResponse:
    try:
        with transaction(dependencies.session_factory) as session:
            details = dependencies.data_source_service.get(session, data_source_id)
    except DataSourceNotFoundError as error:
        raise _not_found() from error

    handle = dependencies.source_storage.open_binary(details.blob.storage_key)
    file_name = quote(details.source.original_file_name, safe="")
    return StreamingResponse(
        _stream(handle),
        media_type=_safe_download_mime(details.source.mime_type),
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{file_name}",
            "X-Content-Type-Options": "nosniff",
        },
    )


def _stream(handle: BinaryIO) -> Iterator[bytes]:
    try:
        while chunk := handle.read(1024 * 1024):
            yield chunk
    finally:
        handle.close()


def _safe_download_mime(mime_type: str) -> str:
    if mime_type in {"text/html", "text/markdown"}:
        return "application/octet-stream"
    return mime_type


def _not_found() -> AppError:
    return AppError(code="DATA_SOURCE_NOT_FOUND", message="数据源不存在", status_code=404)


def _trace_id(request: Request) -> UUID | None:
    trace_id = getattr(request.state, "trace_id", None)
    return trace_id if isinstance(trace_id, UUID) else None
