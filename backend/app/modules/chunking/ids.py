from dataclasses import replace
from uuid import UUID, uuid5

from app.modules.chunking.domain import ChunkDraft


def deterministic_chunk_id(
    generation_id: UUID,
    parsed_source_version_id: UUID,
    chunk_kind: str,
    order_index: int,
    algorithm_version: str,
) -> UUID:
    identity = ":".join(
        (str(parsed_source_version_id), chunk_kind, str(order_index), algorithm_version)
    )
    return uuid5(generation_id, identity)


def link_adjacent_chunks(chunks: tuple[ChunkDraft, ...]) -> tuple[ChunkDraft, ...]:
    linked: list[ChunkDraft] = []
    for index, chunk in enumerate(chunks):
        previous_id = None
        next_id = None
        if (
            index > 0
            and chunks[index - 1].parsed_source_version_id == chunk.parsed_source_version_id
        ):
            previous_id = chunks[index - 1].id
        if (
            index + 1 < len(chunks)
            and chunks[index + 1].parsed_source_version_id == chunk.parsed_source_version_id
        ):
            next_id = chunks[index + 1].id
        linked.append(replace(chunk, previous_chunk_id=previous_id, next_chunk_id=next_id))
    return tuple(linked)
