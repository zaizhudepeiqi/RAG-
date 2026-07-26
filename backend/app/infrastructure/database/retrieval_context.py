from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.database.models.knowledge_bases import ChunkModel
from app.modules.retrieval.context import ContextChunk
from app.modules.retrieval.fusion import RetrievalCandidate


class SqlAlchemyContextStore:
    """Loads only the candidate, parent, and bounded neighbor chunks for one generation."""

    def load_context_chunks(
        self,
        session: Session,
        *,
        generation_id: UUID,
        candidates: tuple[RetrievalCandidate, ...],
        context_window: int,
    ) -> tuple[ContextChunk, ...]:
        if not 0 <= context_window <= 5:
            raise ValueError("context_window must be between 0 and 5")
        requested = {candidate.chunk_id for candidate in candidates}
        requested.update(
            candidate.parent_chunk_id
            for candidate in candidates
            if candidate.parent_chunk_id is not None
        )
        loaded: dict[UUID, ChunkModel] = {}
        frontier = requested
        for _ in range(context_window + 1):
            if not frontier:
                break
            rows = session.scalars(
                select(ChunkModel).where(
                    ChunkModel.index_generation_id == generation_id,
                    ChunkModel.id.in_(frontier),
                )
            ).all()
            next_frontier: set[UUID] = set()
            for row in rows:
                if row.id in loaded:
                    continue
                loaded[row.id] = row
                if row.previous_chunk_id is not None:
                    next_frontier.add(row.previous_chunk_id)
                if row.next_chunk_id is not None:
                    next_frontier.add(row.next_chunk_id)
            frontier = next_frontier - loaded.keys()

        return tuple(
            ContextChunk(
                chunk_id=row.id,
                generation_id=row.index_generation_id,
                parsed_source_version_id=row.parsed_source_version_id,
                chunk_kind=row.chunk_kind,
                parent_chunk_id=row.parent_chunk_id,
                order_index=row.order_index,
                document=row.text_content,
                previous_chunk_id=row.previous_chunk_id,
                next_chunk_id=row.next_chunk_id,
            )
            for row in loaded.values()
        )
