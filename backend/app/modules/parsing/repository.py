from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.parsing.domain import (
    DataSource,
    ParsedArtifact,
    ParsedAsset,
    ParsedBlock,
    ParsedSourceVersion,
    ParsedSourceVersionDetails,
    SourceBlob,
)

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

    def get_blob(
        self,
        session: Session,
        blob_id: UUID,
        *,
        for_update: bool = False,
    ) -> SourceBlob | None: ...

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

    def has_nonterminal_versions(self, session: Session, source_id: UUID) -> bool: ...

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
    ) -> ParsedSourceVersion | None: ...

    def next_version_number(self, session: Session, source_id: UUID) -> int: ...

    def add_version(self, session: Session, version: ParsedSourceVersion) -> None: ...

    def list_versions(
        self,
        session: Session,
        source_id: UUID,
        *,
        limit: int,
    ) -> list[ParsedSourceVersion]: ...

    def get_parsed_version(
        self,
        session: Session,
        version_id: UUID,
        *,
        for_update: bool = False,
    ) -> ParsedSourceVersionDetails | None: ...

    def resume_provider_query(
        self,
        session: Session,
        version_id: UUID,
        operation_id: UUID,
    ) -> ParsedSourceVersion: ...

    def list_parsed_blocks(
        self,
        session: Session,
        version_id: UUID,
        *,
        page_number: int | None,
        block_type: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[ParsedBlock], int]: ...

    def list_parsed_assets(
        self,
        session: Session,
        version_id: UUID,
        *,
        page: int,
        page_size: int,
    ) -> tuple[list[ParsedAsset], int]: ...

    def get_parsed_asset(
        self,
        session: Session,
        version_id: UUID,
        asset_id: UUID,
    ) -> ParsedAsset | None: ...

    def list_parsed_artifacts(
        self,
        session: Session,
        version_id: UUID,
    ) -> list[ParsedArtifact]: ...
