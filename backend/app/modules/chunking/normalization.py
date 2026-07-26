import re
import unicodedata

from app.modules.chunking.domain import NormalizedUnit, SourceBlock

HORIZONTAL_WHITESPACE = re.compile(r"[^\S\r\n]+")
EXCESS_NEWLINES = re.compile(r"\n{3,}")
PARAGRAPH_BOUNDARY = re.compile(r"\n\s*\n+")
SENTENCE_BOUNDARY = re.compile(r"(?<=[\u3002\uff01\uff1f!?\uff1b;])\s*|(?<=[.])\s+(?=[A-Z0-9])")


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = "\n".join(
        HORIZONTAL_WHITESPACE.sub(" ", line).strip() for line in normalized.split("\n")
    )
    return EXCESS_NEWLINES.sub("\n\n", normalized).strip()


def normalize_blocks(blocks: tuple[SourceBlock, ...]) -> tuple[NormalizedUnit, ...]:
    if not blocks:
        return ()
    version_ids = {block.parsed_source_version_id for block in blocks}
    if len(version_ids) != 1:
        raise ValueError("normalization cannot cross parsed source versions")
    units: list[NormalizedUnit] = []
    for block in sorted(blocks, key=lambda item: (item.order_index, item.id)):
        text = normalize_text(block.text_content or block.markdown_content or "")
        asset_text = tuple(
            part
            for asset in block.assets
            for part in (normalize_text(asset.caption or ""), normalize_text(asset.ocr_text or ""))
            if part
        )
        searchable_text = "\n".join((text, *asset_text)).strip()
        if not searchable_text:
            continue
        units.append(
            NormalizedUnit(
                parsed_source_version_id=block.parsed_source_version_id,
                order_index=block.order_index,
                text=text or searchable_text,
                searchable_text=searchable_text,
                block_type=block.block_type,
                source_block_ids=(block.id,),
                asset_ids=tuple(asset.id for asset in block.assets),
                heading_path=block.heading_path,
                page_numbers=((block.page_number,) if block.page_number is not None else ()),
                bounding_boxes=((block.bounding_box,) if block.bounding_box is not None else ()),
            )
        )
    return tuple(units)


def split_paragraphs(text: str) -> tuple[str, ...]:
    return tuple(
        part for part in (normalize_text(item) for item in PARAGRAPH_BOUNDARY.split(text)) if part
    )


def split_sentences(text: str) -> tuple[str, ...]:
    return tuple(
        part for part in (normalize_text(item) for item in SENTENCE_BOUNDARY.split(text)) if part
    )
