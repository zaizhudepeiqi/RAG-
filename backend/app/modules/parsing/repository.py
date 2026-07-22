from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.parsing.domain import DataSource, SourceBlob

DataSourceSort = Literal["display_name", "-display_name", "created_at", "-created_at"]


@dataclass(frozen=True)
class DataSourceListQuery:
    extension: str | None = None
    origin_type: str | None = None
    search: str | None = None
    page: int = 1
    page_size: int = 20
    sort: DataSourceSort = "-created_at"


@dataclass(frozen=True)
class DataSourcePage:
    items: list[DataSource]
    total: int
    page: int
    page_size: int


class DataSourceRepository(Protocol):
    def acquire_blob(
        self,
        session: Session,
        candidate: SourceBlob,
    ) -> tuple[SourceBlob, bool]: ...

    def save_blob(self, session: Session, blob: SourceBlob) -> None: ...

    def get_blob(self, session: Session, blob_id: UUID) -> SourceBlob | None: ...

    def find_active_source_by_sha256(
        self,
        session: Session,
        sha256: str,
    ) -> DataSource | None: ...

    def add_source(self, session: Session, source: DataSource) -> None: ...

    def get_source(
        self,
        session: Session,
        source_id: UUID,
        *,
        for_update: bool = False,
    ) -> DataSource | None: ...

    def save_source(self, session: Session, source: DataSource) -> None: ...

    def list_sources(self, session: Session, query: DataSourceListQuery) -> DataSourcePage: ...

    def count_versions(self, session: Session, source_id: UUID) -> int: ...
