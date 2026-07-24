import json
import math
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
from typing import Any

from app.modules.parsing.archive import UnsafeArchiveError, open_safe_archive

IMAGE_MIME_TYPES = {
    ".bmp": "image/bmp",
    ".gif": "image/gif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


class MinerUNormalizationError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


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
    asset_source_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class NormalizedAsset:
    source_path: str
    asset_type: str
    mime_type: str
    content: bytes
    order_index: int
    page_number: int | None = None
    bounding_box: dict[str, object] | None = None
    caption: str | None = None
    ocr_text: str | None = None


@dataclass(frozen=True)
class NormalizedDocument:
    markdown: str
    blocks: tuple[NormalizedBlock, ...]
    feature_flags: dict[str, bool]
    assets: tuple[NormalizedAsset, ...] = ()
    page_count: int = 0
    quality_level: str = "full"


def normalize_mineru_archive(content: bytes) -> NormalizedDocument:
    entries = _read_archive(content)
    content_path, items, malformed_known = _find_content_list(entries)
    markdown_path, markdown = _find_markdown(entries, content_path)

    if items is None:
        if markdown is not None and markdown.strip():
            return _markdown_fallback(markdown_path, markdown)
        if malformed_known:
            raise MinerUNormalizationError("PARSER_NORMALIZATION_FAILED")
        if markdown is not None:
            raise MinerUNormalizationError("PARSER_OUTPUT_EMPTY")
        raise MinerUNormalizationError("PARSER_OUTPUT_UNSUPPORTED")

    blocks, assets, generated_markdown = _normalize_items(content_path, items, entries)
    effective_markdown = (
        markdown if markdown is not None and markdown.strip() else generated_markdown
    )
    if not effective_markdown.strip() or not blocks:
        if markdown is not None and markdown.strip():
            return _markdown_fallback(markdown_path, markdown)
        raise MinerUNormalizationError("PARSER_OUTPUT_EMPTY")

    page_numbers = [block.page_number for block in blocks if block.page_number is not None]
    has_bounding_boxes = any(block.bounding_box is not None for block in blocks)
    complete_source_map = all(
        block.page_number is not None and block.bounding_box is not None for block in blocks
    )
    return NormalizedDocument(
        markdown=effective_markdown,
        blocks=tuple(blocks),
        assets=tuple(assets),
        page_count=max(page_numbers, default=0),
        quality_level="full" if complete_source_map else "degraded",
        feature_flags={
            "hasText": bool(effective_markdown.strip()),
            "hasPages": bool(page_numbers),
            "hasHeadings": any(block.heading_level is not None for block in blocks),
            "hasBoundingBoxes": has_bounding_boxes,
            "hasAssets": bool(assets),
            "hasTables": any(block.block_type == "table" for block in blocks),
            "hasFormulas": any(block.block_type == "formula" for block in blocks),
        },
    )


def _read_archive(content: bytes) -> dict[str, bytes]:
    try:
        with open_safe_archive(BytesIO(content)) as archive:
            entries: dict[str, bytes] = {}
            for entry in archive.entries:
                with archive.open_entry(entry) as source:
                    entries[entry.source_path] = source.read()
            return entries
    except UnsafeArchiveError as error:
        message = str(error).casefold()
        if "no files" in message:
            code = "PARSER_OUTPUT_EMPTY"
        elif "invalid" in message:
            code = "PARSER_ARCHIVE_INVALID"
        else:
            code = "PARSER_ARCHIVE_UNSAFE"
        raise MinerUNormalizationError(code) from error
    except (EOFError, OSError, RuntimeError) as error:
        raise MinerUNormalizationError("PARSER_ARCHIVE_INVALID") from error


def _find_markdown(
    entries: dict[str, bytes],
    content_path: str,
) -> tuple[str, str | None]:
    candidates: list[tuple[str, str]] = []
    for path, content in entries.items():
        if PurePosixPath(path).suffix.casefold() != ".md":
            continue
        try:
            decoded = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            continue
        candidates.append((path, decoded))
    if not candidates:
        return "", None
    content_parent = PurePosixPath(content_path).parent
    content_name = PurePosixPath(content_path).name
    expected_name = (
        f"{content_name[: -len('_content_list.json')]}.md"
        if content_name.casefold().endswith("_content_list.json")
        else ""
    )
    candidates.sort(
        key=lambda item: (
            not (
                expected_name
                and PurePosixPath(item[0]).parent == content_parent
                and PurePosixPath(item[0]).name.casefold() == expected_name.casefold()
            ),
            PurePosixPath(item[0]).parent != content_parent,
            not item[1].strip(),
            item[0].casefold(),
        )
    )
    return candidates[0]


def _find_content_list(
    entries: dict[str, bytes],
) -> tuple[str, list[dict[str, object]] | None, bool]:
    known_paths = sorted(
        path
        for path in entries
        if PurePosixPath(path).name.casefold().endswith("content_list.json")
    )
    other_json = sorted(
        path
        for path in entries
        if PurePosixPath(path).suffix.casefold() == ".json" and path not in known_paths
    )
    malformed_known = False
    for path in (*known_paths, *other_json):
        try:
            payload = json.loads(entries[path].decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            malformed_known = malformed_known or path in known_paths
            continue
        if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
            continue
        items = [dict(item) for item in payload]
        if path in known_paths or _looks_like_content_list(items):
            return path, items, malformed_known
    return "", None, malformed_known


def _looks_like_content_list(items: list[dict[str, object]]) -> bool:
    if not items:
        return False
    return all(
        isinstance(item.get("type"), str)
        and any(key in item for key in ("text", "table_body", "img_path"))
        for item in items
    )


def _normalize_items(
    content_path: str,
    items: list[dict[str, object]],
    entries: dict[str, bytes],
) -> tuple[list[NormalizedBlock], list[NormalizedAsset], str]:
    blocks: list[NormalizedBlock] = []
    assets_by_path: dict[str, NormalizedAsset] = {}
    generated_markdown: list[str] = []
    heading_levels: dict[int, str] = {}

    for item_index, item in enumerate(items):
        item_type = str(item.get("type", "text")).casefold()
        page_index = _page_index(item.get("page_idx"))
        page_number = page_index + 1 if page_index is not None else None
        bounding_box = _bounding_box(item.get("bbox"))
        heading_level = _positive_int(item.get("text_level"))
        text_content, markdown_content, block_type = _item_content(item_type, item)
        asset_paths = _item_assets(
            item_type,
            item,
            content_path=content_path,
            entries=entries,
            page_number=page_number,
            bounding_box=bounding_box,
            assets_by_path=assets_by_path,
        )
        if text_content is None and markdown_content is None and not asset_paths:
            continue

        if heading_level is not None and text_content:
            heading_levels[heading_level] = text_content
            heading_levels = {
                level: value for level, value in heading_levels.items() if level <= heading_level
            }
        heading_path = (
            tuple(value for _, value in sorted(heading_levels.items())) if heading_levels else None
        )
        raw_locator: dict[str, object] = {
            "artifactPath": content_path,
            "itemIndex": item_index,
        }
        if page_index is not None:
            raw_locator["providerPageIndex"] = page_index
        block = NormalizedBlock(
            block_type=block_type,
            order_index=len(blocks),
            text_content=text_content,
            markdown_content=markdown_content,
            heading_level=heading_level,
            heading_path=heading_path,
            page_number=page_number,
            bounding_box=bounding_box,
            raw_locator=raw_locator,
            asset_source_paths=asset_paths,
        )
        blocks.append(block)
        rendered = markdown_content or text_content
        if rendered:
            generated_markdown.append(rendered)

    return blocks, list(assets_by_path.values()), "\n\n".join(generated_markdown)


def _item_content(
    item_type: str,
    item: dict[str, object],
) -> tuple[str | None, str | None, str]:
    text = _optional_text(item.get("text"))
    if item_type == "table":
        body = _optional_text(item.get("table_body")) or text
        return body, body, "table"
    if item_type in {"equation", "formula", "interline_equation"}:
        return text, text, "formula"
    if item_type == "image":
        caption = _joined_text(item.get("image_caption"))
        return caption, None, "image"
    if item_type == "text":
        return text, text, "text"
    return text, text, item_type[:64] or "unknown"


def _item_assets(
    item_type: str,
    item: dict[str, object],
    *,
    content_path: str,
    entries: dict[str, bytes],
    page_number: int | None,
    bounding_box: dict[str, object] | None,
    assets_by_path: dict[str, NormalizedAsset],
) -> tuple[str, ...]:
    raw_path = item.get("img_path")
    if not isinstance(raw_path, str) or not raw_path:
        return ()
    resolved = _resolve_asset_path(content_path, raw_path, entries)
    if resolved is None:
        return ()
    if resolved not in assets_by_path:
        mime_type = IMAGE_MIME_TYPES.get(PurePosixPath(resolved).suffix.casefold())
        if mime_type is None:
            return ()
        caption_key = "table_caption" if item_type == "table" else "image_caption"
        assets_by_path[resolved] = NormalizedAsset(
            source_path=resolved,
            asset_type="table_image" if item_type == "table" else "image",
            mime_type=mime_type,
            content=entries[resolved],
            order_index=len(assets_by_path),
            page_number=page_number,
            bounding_box=bounding_box,
            caption=_joined_text(item.get(caption_key)),
            ocr_text=_optional_text(item.get("ocr_text")),
        )
    return (resolved,)


def _resolve_asset_path(
    content_path: str,
    raw_path: str,
    entries: dict[str, bytes],
) -> str | None:
    normalized = raw_path.replace("\\", "/")
    parts = PurePosixPath(normalized).parts
    if not parts or normalized.startswith("/") or any(part in {"", ".", ".."} for part in parts):
        return None
    parent = PurePosixPath(content_path).parent
    candidates = [str(parent.joinpath(*parts)), "/".join(parts)]
    for candidate in candidates:
        if candidate in entries:
            return candidate
    suffix_matches = sorted(path for path in entries if path.endswith(f"/{'/'.join(parts)}"))
    return suffix_matches[0] if len(suffix_matches) == 1 else None


def _markdown_fallback(path: str, markdown: str) -> NormalizedDocument:
    return NormalizedDocument(
        markdown=markdown,
        blocks=(
            NormalizedBlock(
                block_type="markdown",
                order_index=0,
                text_content=markdown,
                markdown_content=markdown,
                raw_locator={"artifactPath": path},
            ),
        ),
        feature_flags={
            "hasText": True,
            "hasPages": False,
            "hasHeadings": any(line.startswith("#") for line in markdown.splitlines()),
            "hasBoundingBoxes": False,
            "hasAssets": False,
            "hasTables": False,
            "hasFormulas": False,
        },
        quality_level="degraded",
    )


def _page_index(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _positive_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _bounding_box(value: object) -> dict[str, object] | None:
    if isinstance(value, list) and len(value) == 4 and all(_finite_number(item) for item in value):
        x0, y0, x1, y1 = (float(item) for item in value)
        if x0 <= x1 and y0 <= y1:
            return {"x0": x0, "y0": y0, "x1": x1, "y1": y1}
    if isinstance(value, dict) and all(key in value for key in ("x0", "y0", "x1", "y1")):
        return _bounding_box([value["x0"], value["y0"], value["x1"], value["y1"]])
    return None


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _optional_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _joined_text(value: object) -> str | None:
    if isinstance(value, list):
        parts = [item.strip() for item in value if isinstance(item, str) and item.strip()]
        return "\n".join(parts) or None
    return _optional_text(value)
