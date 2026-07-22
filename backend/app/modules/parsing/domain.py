from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class SourceBlob:
    id: UUID
    sha256: str
    size_bytes: int
    storage_key: str
    mime_type: str
    reference_count: int
    created_at: datetime
    last_referenced_at: datetime
    purge_after: datetime | None


@dataclass
class DataSource:
    id: UUID
    source_blob_id: UUID
    display_name: str
    source_path: str
    original_file_name: str
    extension: str
    mime_type: str
    size_bytes: int
    sha256: str
    origin_type: str
    origin_ref: dict[str, object]
    revision: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


@dataclass(frozen=True)
class DataSourceDetails:
    source: DataSource
    blob: SourceBlob
    version_count: int = 0


@dataclass(frozen=True)
class RegisteredUpload:
    details: DataSourceDetails
    duplicate_of_data_source_id: UUID | None
