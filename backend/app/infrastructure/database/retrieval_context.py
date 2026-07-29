from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.database.models.knowledge_bases import (
    ChunkAssetModel,
    ChunkModel,
    ChunkSourceBlockModel,
)
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

        source_blocks: dict[UUID, list[UUID]] = {}
        assets: dict[UUID, list[UUID]] = {}
        if loaded:
            for chunk_id, block_id in session.execute(
                select(ChunkSourceBlockModel.chunk_id, ChunkSourceBlockModel.parsed_block_id)
                .where(ChunkSourceBlockModel.chunk_id.in_(loaded))
                .order_by(ChunkSourceBlockModel.chunk_id, ChunkSourceBlockModel.order_index)
            ):
                source_blocks.setdefault(chunk_id, []).append(block_id)
            for chunk_id, asset_id in session.execute(
                select(ChunkAssetModel.chunk_id, ChunkAssetModel.parsed_asset_id)
                .where(ChunkAssetModel.chunk_id.in_(loaded))
                .order_by(ChunkAssetModel.chunk_id, ChunkAssetModel.parsed_asset_id)
            ):
                assets.setdefault(chunk_id, []).append(asset_id)

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
                source_block_ids=tuple(source_blocks.get(row.id, [])),
                asset_ids=tuple(assets.get(row.id, [])),
                page_range=tuple(row.page_range or []),
                primary_page_number=row.primary_page_number,
                normalized_text_hash=row.normalized_text_hash.strip(),
            )
            for row in loaded.values()
        )
