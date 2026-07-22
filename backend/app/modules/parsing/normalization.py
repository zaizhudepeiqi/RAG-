from dataclasses import dataclass


@dataclass(frozen=True)
class NormalizedBlock:
    block_type: str
    order_index: int
    text_content: str | None
    markdown_content: str | None
    heading_level: int | None = None
    heading_path: tuple[str, ...] | None = None
    page_number: int | None = None
    bounding_box: dict[str, object] | None = None
    raw_locator: dict[str, object] | None = None


@dataclass(frozen=True)
class NormalizedDocument:
    markdown: str
    blocks: tuple[NormalizedBlock, ...]
    feature_flags: dict[str, bool]
