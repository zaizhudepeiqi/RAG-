from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class TokenCount:
    value: int
    counter_code: str
    counter_version: str
    estimated: bool


@dataclass(frozen=True)
class SourceAsset:
    id: UUID
    caption: str | None
    ocr_text: str | None


@dataclass(frozen=True)
class SourceBlock:
    id: UUID
    parsed_source_version_id: UUID
    block_type: str
    order_index: int
    text_content: str | None
    markdown_content: str | None
    heading_level: int | None
    heading_path: tuple[str, ...]
    page_number: int | None
    bounding_box: dict[str, object] | None
    assets: tuple[SourceAsset, ...] = ()


@dataclass(frozen=True)
class NormalizedUnit:
    parsed_source_version_id: UUID
    order_index: int
    text: str
    searchable_text: str
    block_type: str
    source_block_ids: tuple[UUID, ...]
    asset_ids: tuple[UUID, ...]
    heading_path: tuple[str, ...]
    page_numbers: tuple[int, ...]
    bounding_boxes: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class ChunkDraft:
    id: UUID
    parsed_source_version_id: UUID
    chunk_kind: str
    order_index: int
    text: str
    searchable_text: str
    token_count: TokenCount
    source_block_ids: tuple[UUID, ...]
    asset_ids: tuple[UUID, ...]
    heading_path: tuple[str, ...]
    page_numbers: tuple[int, ...]
    bounding_boxes: tuple[dict[str, object], ...]
    parent_chunk_id: UUID | None = None
    previous_chunk_id: UUID | None = None
    next_chunk_id: UUID | None = None
