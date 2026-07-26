from __future__ import annotations

import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from typing import Protocol
from uuid import UUID

from app.modules.chunking.domain import ChunkDraft, NormalizedUnit
from app.modules.chunking.ids import deterministic_chunk_id, link_adjacent_chunks
from app.modules.chunking.normalization import split_paragraphs, split_sentences
from app.modules.chunking.token_counter import TokenCounter


@dataclass(frozen=True)
class ChunkingContext:
    generation_id: UUID
    parsed_source_version_id: UUID
    algorithm_version: str
    counter: TokenCounter


@dataclass(frozen=True)
class ChunkingResult:
    chunks: tuple[ChunkDraft, ...]
    warnings: tuple[str, ...] = ()


class ChunkStrategy(Protocol):
    def chunk(
        self, context: ChunkingContext, units: tuple[NormalizedUnit, ...]
    ) -> ChunkingResult: ...


class EmbeddingPort(Protocol):
    def embed_documents(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...


@dataclass(frozen=True)
class _Piece:
    unit: NormalizedUnit
    text: str


class TokenChunkStrategy:
    def __init__(self, chunk_size: int, chunk_overlap: int) -> None:
        _validate_size_and_overlap(chunk_size, chunk_overlap)
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk(self, context: ChunkingContext, units: tuple[NormalizedUnit, ...]) -> ChunkingResult:
        pieces = _sentence_pieces(units)
        chunks = _window_chunks(
            context,
            pieces,
            maximum=self.chunk_size,
            minimum=0,
            overlap_count=0,
            overlap_tokens=self.chunk_overlap,
        )
        return ChunkingResult(chunks)


class ParagraphChunkStrategy:
    def __init__(self, max_chunk_size: int, min_chunk_size: int, overlap_paragraphs: int) -> None:
        if max_chunk_size <= 0:
            raise ValueError("max_chunk_size must be positive")
        if min_chunk_size < 0 or min_chunk_size >= max_chunk_size:
            raise ValueError("min_chunk_size must be non-negative and smaller than max_chunk_size")
        if overlap_paragraphs < 0:
            raise ValueError("overlap_paragraphs must be non-negative")
        self.max_chunk_size = max_chunk_size
        self.min_chunk_size = min_chunk_size
        self.overlap_paragraphs = overlap_paragraphs

    def chunk(self, context: ChunkingContext, units: tuple[NormalizedUnit, ...]) -> ChunkingResult:
        pieces = tuple(
            _Piece(unit, paragraph) for unit in units for paragraph in split_paragraphs(unit.text)
        )
        return ChunkingResult(
            _window_chunks(
                context,
                pieces,
                maximum=self.max_chunk_size,
                minimum=self.min_chunk_size,
                overlap_count=self.overlap_paragraphs,
                overlap_tokens=0,
            )
        )


class HeadingChunkStrategy:
    def __init__(
        self, max_heading_level: int, max_chunk_size: int, include_heading_path: bool
    ) -> None:
        if not 1 <= max_heading_level <= 6:
            raise ValueError("max_heading_level must be between 1 and 6")
        if max_chunk_size <= 0:
            raise ValueError("max_chunk_size must be positive")
        self.max_heading_level = max_heading_level
        self.max_chunk_size = max_chunk_size
        self.include_heading_path = include_heading_path

    def chunk(self, context: ChunkingContext, units: tuple[NormalizedUnit, ...]) -> ChunkingResult:
        _validate_units(context, units)
        resolved_units, heading_source = _resolve_heading_units(units)
        if heading_source == "fallback":
            fallback = ParagraphChunkStrategy(self.max_chunk_size, 0, 0).chunk(context, units)
            return replace(fallback, warnings=("CHUNK_HEADING_FALLBACK",))
        groups: list[list[NormalizedUnit]] = []
        keys: list[tuple[str, ...]] = []
        for unit in resolved_units:
            key = unit.heading_path[: self.max_heading_level]
            if not groups or keys[-1] != key:
                groups.append([])
                keys.append(key)
            groups[-1].append(unit)
        chunks: list[ChunkDraft] = []
        for key, group in zip(keys, groups, strict=True):
            heading = " > ".join(key) if self.include_heading_path else ""
            body_limit = _body_limit(context.counter, heading, self.max_chunk_size)
            result = ParagraphChunkStrategy(body_limit, 0, 0).chunk(context, tuple(group))
            for chunk in result.chunks:
                text = chunk.text
                searchable = chunk.searchable_text
                if heading:
                    text = f"{heading}\n{text}"
                    searchable = f"{heading}\n{searchable}"
                if context.counter.count(text).value > self.max_chunk_size:
                    raise ValueError("heading path leaves insufficient room for chunk content")
                chunks.append(
                    replace(
                        chunk,
                        order_index=len(chunks),
                        text=text,
                        searchable_text=searchable,
                        token_count=context.counter.count(text),
                        heading_path=key,
                    )
                )
        return ChunkingResult(_reidentify_and_link(context, tuple(chunks)))


class PageChunkStrategy:
    def __init__(self, max_chunk_size: int, chunk_overlap: int) -> None:
        _validate_size_and_overlap(max_chunk_size, chunk_overlap)
        self.max_chunk_size = max_chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk(self, context: ChunkingContext, units: tuple[NormalizedUnit, ...]) -> ChunkingResult:
        _validate_units(context, units)
        if any(not unit.page_numbers for unit in units):
            raise ValueError("page chunking requires page numbers for every unit")
        chunks: list[ChunkDraft] = []
        current_page: int | None = None
        page_units: list[NormalizedUnit] = []
        for unit in units:
            page = unit.page_numbers[0]
            if current_page is not None and page != current_page:
                chunks.extend(self._page_chunks(context, tuple(page_units)))
                page_units = []
            current_page = page
            page_units.append(unit)
        chunks.extend(self._page_chunks(context, tuple(page_units)))
        return ChunkingResult(_reidentify_and_link(context, tuple(chunks)))

    def _page_chunks(
        self, context: ChunkingContext, units: tuple[NormalizedUnit, ...]
    ) -> tuple[ChunkDraft, ...]:
        return _window_chunks(
            context,
            _sentence_pieces(units),
            maximum=self.max_chunk_size,
            minimum=0,
            overlap_count=0,
            overlap_tokens=self.chunk_overlap,
        )


class SemanticChunkStrategy:
    def __init__(
        self,
        min_chunk_size: int,
        max_chunk_size: int,
        similarity_threshold: float,
        sentence_window: int,
        embeddings: EmbeddingPort,
    ) -> None:
        if min_chunk_size < 0 or min_chunk_size >= max_chunk_size:
            raise ValueError("min_chunk_size must be non-negative and smaller than max_chunk_size")
        if not 0 <= similarity_threshold <= 1:
            raise ValueError("similarity_threshold must be between 0 and 1")
        if sentence_window <= 0:
            raise ValueError("sentence_window must be positive")
        self.min_chunk_size = min_chunk_size
        self.max_chunk_size = max_chunk_size
        self.similarity_threshold = similarity_threshold
        self.sentence_window = sentence_window
        self.embeddings = embeddings

    def chunk(self, context: ChunkingContext, units: tuple[NormalizedUnit, ...]) -> ChunkingResult:
        _validate_units(context, units)
        pieces = _sentence_pieces(units)
        if not pieces:
            return ChunkingResult(())
        windows = [
            "\n".join(piece.text for piece in pieces[index : index + self.sentence_window])
            for index in range(len(pieces))
        ]
        vectors = self.embeddings.embed_documents(windows)
        if len(vectors) != len(pieces):
            raise ValueError("embedding response count does not match semantic windows")
        _validate_vectors(vectors)
        groups: list[list[_Piece]] = [[]]
        for index, piece in enumerate(pieces):
            boundary = (
                index > 0
                and _cosine(vectors[index - 1], vectors[index]) < self.similarity_threshold
            )
            if boundary:
                groups.append([])
            groups[-1].append(piece)
        merged_groups = _merge_small_groups_forward(groups, self.min_chunk_size, context.counter)
        chunks = tuple(
            chunk
            for group in merged_groups
            for chunk in _window_chunks(
                context,
                tuple(group),
                maximum=self.max_chunk_size,
                minimum=0,
                overlap_count=0,
                overlap_tokens=0,
            )
        )
        return ChunkingResult(_reidentify_and_link(context, chunks))


def _sentence_pieces(units: tuple[NormalizedUnit, ...]) -> tuple[_Piece, ...]:
    return tuple(
        _Piece(unit, sentence)
        for unit in units
        for sentence in (split_sentences(unit.text) or (unit.text,))
        if sentence
    )


def _window_chunks(
    context: ChunkingContext,
    pieces: tuple[_Piece, ...],
    *,
    maximum: int,
    minimum: int,
    overlap_count: int,
    overlap_tokens: int,
) -> tuple[ChunkDraft, ...]:
    _validate_units(context, tuple(piece.unit for piece in pieces))
    expanded = tuple(
        split_piece
        for piece in pieces
        for split_piece in _split_oversized_piece(piece, maximum, context.counter, overlap_tokens)
    )
    groups: list[tuple[_Piece, ...]] = []
    current: list[_Piece] = []
    index = 0
    while index < len(expanded):
        piece = expanded[index]
        candidate = (*current, piece)
        if current and context.counter.count(_join_text(candidate)).value > maximum:
            groups.append(tuple(current))
            current = _overlap_pieces(current, overlap_count, overlap_tokens, context.counter)
            if current and context.counter.count(_join_text((*current, piece))).value > maximum:
                current = []
            continue
        current.append(piece)
        index += 1
        if minimum and context.counter.count(_join_text(current)).value < minimum:
            continue
    if current:
        groups.append(tuple(current))
    chunks = tuple(_draft(context, index, group) for index, group in enumerate(groups))
    return link_adjacent_chunks(chunks)


def _split_oversized_piece(
    piece: _Piece,
    maximum: int,
    counter: TokenCounter,
    overlap_tokens: int,
) -> tuple[_Piece, ...]:
    if counter.count(piece.text).value <= maximum:
        return (piece,)
    parts: list[_Piece] = []
    start = 0
    while start < len(piece.text):
        end = _largest_prefix(piece.text, start, maximum, counter)
        parts.append(_Piece(piece.unit, piece.text[start:end].strip()))
        if end >= len(piece.text):
            break
        overlap_start = _smallest_suffix_start(piece.text, start, end, overlap_tokens, counter)
        start = overlap_start if overlap_start > start else end
    return tuple(part for part in parts if part.text)


def _largest_prefix(text: str, start: int, maximum: int, counter: TokenCounter) -> int:
    low, high = start + 1, len(text)
    best = low
    while low <= high:
        middle = (low + high) // 2
        if counter.count(text[start:middle]).value <= maximum:
            best = middle
            low = middle + 1
        else:
            high = middle - 1
    return best


def _smallest_suffix_start(
    text: str, start: int, end: int, overlap: int, counter: TokenCounter
) -> int:
    if overlap <= 0:
        return end
    low, high = start, end
    best = end
    while low <= high:
        middle = (low + high) // 2
        if counter.count(text[middle:end]).value <= overlap:
            best = middle
            high = middle - 1
        else:
            low = middle + 1
    return best


def _overlap_pieces(
    pieces: list[_Piece], count: int, tokens: int, counter: TokenCounter
) -> list[_Piece]:
    if count:
        return pieces[-count:]
    if not tokens:
        return []
    selected: list[_Piece] = []
    for piece in reversed(pieces):
        if counter.count(_join_text((piece, *selected))).value > tokens:
            break
        selected.insert(0, piece)
    return selected


def _draft(context: ChunkingContext, order_index: int, pieces: tuple[_Piece, ...]) -> ChunkDraft:
    text = _join_text(pieces)
    units = tuple(piece.unit for piece in pieces)
    searchable_text = _searchable_text(text, units)
    return ChunkDraft(
        id=deterministic_chunk_id(
            context.generation_id,
            context.parsed_source_version_id,
            "chunk",
            order_index,
            context.algorithm_version,
        ),
        parsed_source_version_id=context.parsed_source_version_id,
        chunk_kind="chunk",
        order_index=order_index,
        text=text,
        searchable_text=searchable_text,
        token_count=context.counter.count(text),
        source_block_ids=_unique(item for unit in units for item in unit.source_block_ids),
        asset_ids=_unique(item for unit in units for item in unit.asset_ids),
        heading_path=units[0].heading_path if units else (),
        page_numbers=_unique(item for unit in units for item in unit.page_numbers),
        bounding_boxes=tuple(item for unit in units for item in unit.bounding_boxes),
    )


def _reidentify_and_link(
    context: ChunkingContext, chunks: tuple[ChunkDraft, ...]
) -> tuple[ChunkDraft, ...]:
    identified = tuple(
        replace(
            chunk,
            id=deterministic_chunk_id(
                context.generation_id,
                context.parsed_source_version_id,
                chunk.chunk_kind,
                index,
                context.algorithm_version,
            ),
            order_index=index,
            previous_chunk_id=None,
            next_chunk_id=None,
        )
        for index, chunk in enumerate(chunks)
    )
    return link_adjacent_chunks(identified)


def _join_text(pieces: Sequence[_Piece]) -> str:
    return "\n\n".join(piece.text for piece in pieces).strip()


def _unique[T](items: Iterable[T]) -> tuple[T, ...]:
    return tuple(dict.fromkeys(items))


def _validate_size_and_overlap(maximum: int, overlap: int) -> None:
    if maximum <= 0:
        raise ValueError("maximum chunk size must be positive")
    if overlap < 0 or overlap >= maximum:
        raise ValueError("chunk overlap must be non-negative and smaller than chunk size")


def _validate_units(context: ChunkingContext, units: tuple[NormalizedUnit, ...]) -> None:
    if any(unit.parsed_source_version_id != context.parsed_source_version_id for unit in units):
        raise ValueError("chunking cannot cross parsed source versions")


def _searchable_text(text: str, units: tuple[NormalizedUnit, ...]) -> str:
    supplements: list[str] = []
    seen: set[tuple[UUID, ...]] = set()
    for unit in units:
        identity = unit.source_block_ids
        if identity in seen:
            continue
        seen.add(identity)
        if unit.searchable_text == unit.text:
            continue
        supplement = unit.searchable_text
        if supplement.startswith(unit.text):
            supplement = supplement[len(unit.text) :].strip()
        if supplement:
            supplements.append(supplement)
    return "\n\n".join((text, *_unique(supplements))).strip()


MARKDOWN_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


def _resolve_heading_units(
    units: tuple[NormalizedUnit, ...],
) -> tuple[tuple[NormalizedUnit, ...], str]:
    if any(unit.heading_path for unit in units):
        return units, "parser_blocks"
    path: list[str] = []
    resolved: list[NormalizedUnit] = []
    found_markdown = False
    for unit in units:
        lines = unit.text.splitlines()
        match = MARKDOWN_HEADING.match(lines[0]) if lines else None
        if match is not None:
            found_markdown = True
            level = len(match.group(1))
            title = match.group(2).strip()
            path[level - 1 :] = [title]
            body = "\n".join(lines[1:]).strip() or title
            searchable = unit.searchable_text.replace(unit.text, body, 1)
            resolved.append(
                replace(unit, text=body, searchable_text=searchable, heading_path=tuple(path))
            )
        else:
            resolved.append(replace(unit, heading_path=tuple(path)))
    return tuple(resolved), "markdown" if found_markdown else "fallback"


def _body_limit(counter: TokenCounter, heading: str, maximum: int) -> int:
    if not heading:
        return maximum
    prefix_tokens = counter.count(f"{heading}\n").value
    available = maximum - prefix_tokens
    if available <= 0:
        raise ValueError("heading path exceeds maximum chunk size")
    return available


def _merge_small_groups_forward(
    groups: list[list[_Piece]], minimum: int, counter: TokenCounter
) -> list[list[_Piece]]:
    if minimum <= 0:
        return [group for group in groups if group]
    merged: list[list[_Piece]] = []
    pending: list[_Piece] = []
    for group in groups:
        if not group:
            continue
        combined = [*pending, *group]
        if counter.count(_join_text(combined)).value < minimum:
            pending = combined
            continue
        merged.append(combined)
        pending = []
    if pending:
        if merged:
            merged[-1].extend(pending)
        else:
            merged.append(pending)
    return merged


def _validate_vectors(vectors: Sequence[Sequence[float]]) -> None:
    if not vectors:
        raise ValueError("embedding response cannot be empty")
    dimension = len(vectors[0])
    if dimension == 0 or any(len(vector) != dimension for vector in vectors):
        raise ValueError("embedding vectors must have the same non-zero dimension")
    if any(not math.isfinite(value) for vector in vectors for value in vector):
        raise ValueError("embedding vectors must contain finite values")


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        raise ValueError("embedding vectors must have the same non-zero dimension")
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0
    return dot / (left_norm * right_norm)
