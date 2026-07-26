from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.retrieval.fusion import RetrievalCandidate


@dataclass(frozen=True)
class ContextChunk:
    chunk_id: UUID
    generation_id: UUID
    parsed_source_version_id: UUID
    chunk_kind: str
    parent_chunk_id: UUID | None
    order_index: int
    document: str
    previous_chunk_id: UUID | None = None
    next_chunk_id: UUID | None = None


@dataclass(frozen=True)
class RetrievedContext:
    chunk_id: UUID
    parsed_source_version_id: UUID
    chunk_kind: str
    parent_chunk_id: UUID | None
    document: str
    order_index: int
    fused_score: float
    rerank_score: float | None
    matched_child_ids: tuple[UUID, ...]
    expanded_from_chunk_ids: tuple[UUID, ...]


class ContextStore(Protocol):
    def load_context_chunks(
        self,
        session: Session,
        *,
        generation_id: UUID,
        candidates: tuple[RetrievalCandidate, ...],
        context_window: int,
    ) -> tuple[ContextChunk, ...]: ...


def expand_context(
    candidates: tuple[RetrievalCandidate, ...],
    chunks: Iterable[ContextChunk],
    *,
    context_window: int,
) -> tuple[RetrievedContext, ...]:
    if not 0 <= context_window <= 5:
        raise ValueError("context_window must be between 0 and 5")
    by_id = {chunk.chunk_id: chunk for chunk in chunks}
    contexts: dict[UUID, RetrievedContext] = {}
    for candidate in candidates:
        anchor = by_id.get(candidate.chunk_id)
        if anchor is None:
            continue
        if anchor.chunk_kind == "child" and anchor.parent_chunk_id is not None:
            parent = by_id.get(anchor.parent_chunk_id)
            if parent is None or not _same_source(anchor, parent):
                continue
            current = contexts.get(parent.chunk_id)
            contexts[parent.chunk_id] = RetrievedContext(
                chunk_id=parent.chunk_id,
                parsed_source_version_id=parent.parsed_source_version_id,
                chunk_kind=parent.chunk_kind,
                parent_chunk_id=parent.parent_chunk_id,
                document=parent.document,
                order_index=parent.order_index,
                fused_score=max(current.fused_score, candidate.fused_score)
                if current
                else candidate.fused_score,
                rerank_score=_max_score(
                    current.rerank_score if current else None, candidate.rerank_score
                ),
                matched_child_ids=_append_unique(
                    current.matched_child_ids if current else (), candidate.chunk_id
                ),
                expanded_from_chunk_ids=_append_unique(
                    current.expanded_from_chunk_ids if current else (), candidate.chunk_id
                ),
            )
            continue

        for expanded_chunk in _window(anchor, by_id, context_window):
            current = contexts.get(expanded_chunk.chunk_id)
            contexts[expanded_chunk.chunk_id] = RetrievedContext(
                chunk_id=expanded_chunk.chunk_id,
                parsed_source_version_id=expanded_chunk.parsed_source_version_id,
                chunk_kind=expanded_chunk.chunk_kind,
                parent_chunk_id=expanded_chunk.parent_chunk_id,
                document=expanded_chunk.document,
                order_index=expanded_chunk.order_index,
                fused_score=max(current.fused_score, candidate.fused_score)
                if current
                else candidate.fused_score,
                rerank_score=_max_score(
                    current.rerank_score if current else None, candidate.rerank_score
                ),
                matched_child_ids=current.matched_child_ids if current else (),
                expanded_from_chunk_ids=_append_unique(
                    current.expanded_from_chunk_ids if current else (), candidate.chunk_id
                ),
            )
    return tuple(
        sorted(
            contexts.values(),
            key=lambda item: (
                str(item.parsed_source_version_id),
                item.order_index,
                str(item.chunk_id),
            ),
        )
    )


def _window(
    anchor: ContextChunk,
    by_id: dict[UUID, ContextChunk],
    context_window: int,
) -> tuple[ContextChunk, ...]:
    selected: dict[UUID, ContextChunk] = {anchor.chunk_id: anchor}
    current = anchor
    for _ in range(context_window):
        previous = by_id.get(current.previous_chunk_id) if current.previous_chunk_id else None
        if previous is None or not _same_scope(anchor, previous):
            break
        selected[previous.chunk_id] = previous
        current = previous
    current = anchor
    for _ in range(context_window):
        following = by_id.get(current.next_chunk_id) if current.next_chunk_id else None
        if following is None or not _same_scope(anchor, following):
            break
        selected[following.chunk_id] = following
        current = following
    return tuple(sorted(selected.values(), key=lambda item: (item.order_index, str(item.chunk_id))))


def _same_scope(left: ContextChunk, right: ContextChunk) -> bool:
    return _same_source(left, right) and left.parent_chunk_id == right.parent_chunk_id


def _same_source(left: ContextChunk, right: ContextChunk) -> bool:
    return (
        left.generation_id == right.generation_id
        and left.parsed_source_version_id == right.parsed_source_version_id
    )


def _append_unique(values: tuple[UUID, ...], value: UUID) -> tuple[UUID, ...]:
    return values if value in values else (*values, value)


def _max_score(left: float | None, right: float | None) -> float | None:
    if left is None:
        return right
    if right is None:
        return left
    return max(left, right)
