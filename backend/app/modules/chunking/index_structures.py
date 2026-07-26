from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from typing import Protocol
from uuid import UUID

from app.modules.chunking.domain import ChunkDraft
from app.modules.chunking.ids import deterministic_chunk_id, link_adjacent_chunks
from app.modules.chunking.strategies import ChunkingContext
from app.modules.chunking.token_counter import TokenCounter


@dataclass(frozen=True)
class IndexStructureResult:
    all_chunks: tuple[ChunkDraft, ...]
    indexable_chunks: tuple[ChunkDraft, ...]
    context_chunks: tuple[ChunkDraft, ...]


@dataclass(frozen=True)
class _TextWindow:
    text: str
    start: int
    end: int


class IndexStructure(Protocol):
    def assemble(
        self, context: ChunkingContext, strategy_chunks: tuple[ChunkDraft, ...]
    ) -> IndexStructureResult: ...


class ChunkIndexStructure:
    def assemble(
        self, context: ChunkingContext, strategy_chunks: tuple[ChunkDraft, ...]
    ) -> IndexStructureResult:
        _validate_strategy_chunks(context, strategy_chunks)
        chunks = _identify_and_link(context, strategy_chunks, "chunk")
        return IndexStructureResult(chunks, chunks, chunks)


class ParentChildIndexStructure:
    def __init__(
        self,
        parent_chunk_size: int,
        child_chunk_size: int,
        child_chunk_overlap: int,
    ) -> None:
        if parent_chunk_size <= 0 or child_chunk_size <= 0:
            raise ValueError("parent and child chunk sizes must be positive")
        if parent_chunk_size < child_chunk_size * 2:
            raise ValueError("parent chunk size must be at least twice child chunk size")
        if child_chunk_overlap < 0 or child_chunk_overlap >= child_chunk_size:
            raise ValueError("child overlap must be non-negative and smaller than child size")
        self.parent_chunk_size = parent_chunk_size
        self.child_chunk_size = child_chunk_size
        self.child_chunk_overlap = child_chunk_overlap

    def assemble(
        self, context: ChunkingContext, strategy_chunks: tuple[ChunkDraft, ...]
    ) -> IndexStructureResult:
        _validate_strategy_chunks(context, strategy_chunks)
        distinct_chunks = _deduplicate_strategy_chunks(strategy_chunks)
        fragments = tuple(
            fragment
            for chunk in distinct_chunks
            for fragment in _split_draft(chunk, self.parent_chunk_size, 0, context.counter)
        )
        parent_groups = _group_for_parents(fragments, self.parent_chunk_size, context.counter)
        parents = _build_parents(context, parent_groups)
        children = _build_children(
            context,
            parents,
            parent_groups,
            child_size=self.child_chunk_size,
            child_overlap=self.child_chunk_overlap,
        )
        return IndexStructureResult(
            all_chunks=(*parents, *children),
            indexable_chunks=children,
            context_chunks=parents,
        )


def _validate_strategy_chunks(context: ChunkingContext, chunks: tuple[ChunkDraft, ...]) -> None:
    if any(chunk.parsed_source_version_id != context.parsed_source_version_id for chunk in chunks):
        raise ValueError("index structure cannot cross parsed source versions")
    if any(chunk.chunk_kind != "chunk" for chunk in chunks):
        raise ValueError("index structure input must contain strategy chunks")


def _deduplicate_strategy_chunks(chunks: tuple[ChunkDraft, ...]) -> tuple[ChunkDraft, ...]:
    seen: set[tuple[UUID, tuple[UUID, ...], str]] = set()
    distinct: list[ChunkDraft] = []
    for chunk in chunks:
        key = (chunk.parsed_source_version_id, chunk.source_block_ids, chunk.text)
        if key in seen:
            continue
        seen.add(key)
        distinct.append(chunk)
    return tuple(distinct)


def _group_for_parents(
    chunks: tuple[ChunkDraft, ...], maximum: int, counter: TokenCounter
) -> tuple[tuple[ChunkDraft, ...], ...]:
    groups: list[tuple[ChunkDraft, ...]] = []
    current: list[ChunkDraft] = []
    for chunk in chunks:
        candidate = (*current, chunk)
        if current and counter.count(_join_draft_text(candidate)).value > maximum:
            groups.append(tuple(current))
            current = []
        current.append(chunk)
    if current:
        groups.append(tuple(current))
    return tuple(groups)


def _build_parents(
    context: ChunkingContext, groups: tuple[tuple[ChunkDraft, ...], ...]
) -> tuple[ChunkDraft, ...]:
    parents = tuple(
        _combine_drafts(context, group, "parent", index) for index, group in enumerate(groups)
    )
    return link_adjacent_chunks(parents)


def _build_children(
    context: ChunkingContext,
    parents: tuple[ChunkDraft, ...],
    parent_groups: tuple[tuple[ChunkDraft, ...], ...],
    *,
    child_size: int,
    child_overlap: int,
) -> tuple[ChunkDraft, ...]:
    children: list[ChunkDraft] = []
    for parent, source_chunks in zip(parents, parent_groups, strict=True):
        parent_children: list[ChunkDraft] = []
        source_spans = _draft_spans(source_chunks)
        windows = _text_windows(parent.text, child_size, child_overlap, context.counter)
        for window in windows:
            index = len(children) + len(parent_children)
            sources = tuple(
                source
                for start, end, source in source_spans
                if window.end > start and window.start < end
            )
            if not sources:
                raise ValueError("child window has no source mapping")
            child = _combine_drafts(context, sources, "child", index)
            parent_children.append(
                replace(
                    child,
                    text=window.text,
                    searchable_text=_join_searchable_text(sources, window.text),
                    token_count=context.counter.count(window.text),
                    parent_chunk_id=parent.id,
                    previous_chunk_id=None,
                    next_chunk_id=None,
                )
            )
        children.extend(link_adjacent_chunks(tuple(parent_children)))
    return tuple(children)


def _combine_drafts(
    context: ChunkingContext,
    chunks: tuple[ChunkDraft, ...],
    kind: str,
    order_index: int,
) -> ChunkDraft:
    text = _join_draft_text(chunks)
    searchable_text = _join_searchable_text(chunks, text)
    return ChunkDraft(
        id=deterministic_chunk_id(
            context.generation_id,
            context.parsed_source_version_id,
            kind,
            order_index,
            context.algorithm_version,
        ),
        parsed_source_version_id=context.parsed_source_version_id,
        chunk_kind=kind,
        order_index=order_index,
        text=text,
        searchable_text=searchable_text,
        token_count=context.counter.count(text),
        source_block_ids=_unique(
            source_id for chunk in chunks for source_id in chunk.source_block_ids
        ),
        asset_ids=_unique(asset_id for chunk in chunks for asset_id in chunk.asset_ids),
        heading_path=_common_heading_path(chunks),
        page_numbers=_unique(page for chunk in chunks for page in chunk.page_numbers),
        bounding_boxes=_unique_mappings(box for chunk in chunks for box in chunk.bounding_boxes),
    )


def _split_draft(
    chunk: ChunkDraft,
    maximum: int,
    overlap: int,
    counter: TokenCounter,
) -> tuple[ChunkDraft, ...]:
    windows = _text_windows(chunk.text, maximum, overlap, counter)
    return tuple(
        replace(
            chunk,
            text=window.text,
            searchable_text=_with_search_supplement(window.text, chunk.text, chunk.searchable_text),
            token_count=counter.count(window.text),
            previous_chunk_id=None,
            next_chunk_id=None,
        )
        for window in windows
    )


def _text_windows(
    text: str, maximum: int, overlap: int, counter: TokenCounter
) -> tuple[_TextWindow, ...]:
    if not text:
        return ()
    windows: list[_TextWindow] = []
    start = 0
    while start < len(text):
        end = _largest_end(text, start, maximum, counter)
        raw_value = text[start:end]
        value = raw_value.strip()
        if value:
            leading_whitespace = len(raw_value) - len(raw_value.lstrip())
            trailing_whitespace = len(raw_value) - len(raw_value.rstrip())
            windows.append(
                _TextWindow(
                    text=value,
                    start=start + leading_whitespace,
                    end=end - trailing_whitespace,
                )
            )
        if end == len(text):
            break
        next_start = _overlap_start(text, start, end, overlap, counter)
        start = next_start if next_start > start else end
    return tuple(windows)


def _largest_end(text: str, start: int, maximum: int, counter: TokenCounter) -> int:
    low, high = start + 1, len(text)
    best = start
    while low <= high:
        middle = (low + high) // 2
        if counter.count(text[start:middle]).value <= maximum:
            best = middle
            low = middle + 1
        else:
            high = middle - 1
    if best == start:
        raise ValueError("a single character exceeds the configured token limit")
    return best


def _overlap_start(
    text: str,
    window_start: int,
    window_end: int,
    overlap: int,
    counter: TokenCounter,
) -> int:
    if overlap == 0:
        return window_end
    low, high = window_start, window_end
    best = window_end
    while low <= high:
        middle = (low + high) // 2
        if counter.count(text[middle:window_end]).value <= overlap:
            best = middle
            high = middle - 1
        else:
            low = middle + 1
    return best


def _identify_and_link(
    context: ChunkingContext,
    chunks: tuple[ChunkDraft, ...],
    kind: str,
) -> tuple[ChunkDraft, ...]:
    identified = tuple(
        replace(
            chunk,
            id=deterministic_chunk_id(
                context.generation_id,
                context.parsed_source_version_id,
                kind,
                index,
                context.algorithm_version,
            ),
            chunk_kind=kind,
            order_index=index,
            parent_chunk_id=None,
            previous_chunk_id=None,
            next_chunk_id=None,
        )
        for index, chunk in enumerate(chunks)
    )
    return link_adjacent_chunks(identified)


def _join_draft_text(chunks: Sequence[ChunkDraft]) -> str:
    return "\n\n".join(chunk.text for chunk in chunks).strip()


def _draft_spans(chunks: tuple[ChunkDraft, ...]) -> tuple[tuple[int, int, ChunkDraft], ...]:
    spans: list[tuple[int, int, ChunkDraft]] = []
    offset = 0
    for chunk in chunks:
        end = offset + len(chunk.text)
        spans.append((offset, end, chunk))
        offset = end + 2
    return tuple(spans)


def _join_searchable_text(chunks: tuple[ChunkDraft, ...], text: str) -> str:
    supplements = _unique(
        supplement
        for chunk in chunks
        if (supplement := _search_supplement(chunk.text, chunk.searchable_text))
    )
    return "\n\n".join((text, *supplements)).strip()


def _with_search_supplement(text: str, source_text: str, searchable_text: str) -> str:
    supplement = _search_supplement(source_text, searchable_text)
    return "\n\n".join(part for part in (text, supplement) if part).strip()


def _search_supplement(text: str, searchable_text: str) -> str:
    if searchable_text == text:
        return ""
    if searchable_text.startswith(text):
        return searchable_text[len(text) :].strip()
    return searchable_text


def _common_heading_path(chunks: tuple[ChunkDraft, ...]) -> tuple[str, ...]:
    if not chunks:
        return ()
    common = list(chunks[0].heading_path)
    for chunk in chunks[1:]:
        prefix_length = 0
        for left, right in zip(common, chunk.heading_path, strict=False):
            if left != right:
                break
            prefix_length += 1
        common = common[:prefix_length]
        if not common:
            break
    return tuple(common)


def _unique[T](items: Iterable[T]) -> tuple[T, ...]:
    return tuple(dict.fromkeys(items))


def _unique_mappings(
    items: Iterable[dict[str, object]],
) -> tuple[dict[str, object], ...]:
    unique: list[dict[str, object]] = []
    for item in items:
        if item not in unique:
            unique.append(item)
    return tuple(unique)
