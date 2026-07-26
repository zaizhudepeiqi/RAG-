from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.infrastructure.database.models.knowledge_bases import (
    ChunkAssetModel,
    ChunkModel,
    ChunkSourceBlockModel,
    IndexGenerationItemModel,
    IndexGenerationModel,
)
from app.infrastructure.database.models.parsing import (
    ParsedAssetModel,
    ParsedBlockAssetModel,
    ParsedBlockModel,
)
from app.infrastructure.database.session import transaction
from app.modules.chunking.domain import ChunkDraft, SourceAsset, SourceBlock, TokenCount
from app.modules.chunking.normalization import normalize_text


class SqlAlchemyGenerationItemStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def start_chunking(self, item_id: UUID) -> str:
        with transaction(self._session_factory) as session:
            item = self._locked_item(session, item_id)
            if item is None:
                raise RuntimeError("generation item does not exist")
            generation = session.get(IndexGenerationModel, item.index_generation_id)
            if generation is None or generation.is_frozen:
                raise RuntimeError("generation is not mutable")
            if item.status == "queued":
                item.status = "chunking"
                item.started_at = datetime.now(UTC)
                item.stage_progress = {"chunking": "running"}
            return item.status

    def load_source_blocks(self, parsed_source_version_id: UUID) -> tuple[SourceBlock, ...]:
        with transaction(self._session_factory) as session:
            blocks = session.scalars(
                select(ParsedBlockModel)
                .where(ParsedBlockModel.parsed_source_version_id == parsed_source_version_id)
                .order_by(ParsedBlockModel.order_index, ParsedBlockModel.id)
            ).all()
            links = session.execute(
                select(ParsedBlockAssetModel.block_id, ParsedAssetModel)
                .join(ParsedAssetModel, ParsedAssetModel.id == ParsedBlockAssetModel.asset_id)
                .where(ParsedAssetModel.parsed_source_version_id == parsed_source_version_id)
                .order_by(ParsedAssetModel.order_index, ParsedAssetModel.id)
            ).all()
            assets_by_block: dict[UUID, list[SourceAsset]] = {}
            for block_id, asset in links:
                assets_by_block.setdefault(block_id, []).append(
                    SourceAsset(id=asset.id, caption=asset.caption, ocr_text=asset.ocr_text)
                )
            return tuple(
                SourceBlock(
                    id=block.id,
                    parsed_source_version_id=block.parsed_source_version_id,
                    block_type=block.block_type,
                    order_index=block.order_index,
                    text_content=block.text_content,
                    markdown_content=block.markdown_content,
                    heading_level=block.heading_level,
                    heading_path=tuple(block.heading_path or ()),
                    page_number=block.page_number,
                    bounding_box=block.bounding_box,
                    assets=tuple(assets_by_block.get(block.id, ())),
                )
                for block in blocks
            )

    def save_chunks(
        self,
        item_id: UUID,
        generation_id: UUID,
        chunks: tuple[ChunkDraft, ...],
        indexable_chunk_ids: tuple[UUID, ...],
        warnings: tuple[str, ...],
    ) -> None:
        with transaction(self._session_factory) as session:
            item = self._locked_item(session, item_id)
            if item is None or item.index_generation_id != generation_id:
                raise RuntimeError("generation item does not match generation")
            if item.status == "embedding":
                return
            if item.status != "chunking":
                raise RuntimeError("generation item is not chunking")
            if not chunks or not indexable_chunk_ids:
                raise ValueError("chunk output cannot be empty")
            if session.scalar(
                select(func.count())
                .select_from(ChunkModel)
                .where(ChunkModel.generation_item_id == item_id)
            ):
                raise RuntimeError("chunk checkpoint exists in an unexpected state")

            models = {
                chunk.id: self._chunk_model(item_id, generation_id, chunk) for chunk in chunks
            }
            session.add_all(models.values())
            session.flush()
            for chunk in chunks:
                model = models[chunk.id]
                model.parent_chunk_id = chunk.parent_chunk_id
                model.previous_chunk_id = chunk.previous_chunk_id
                model.next_chunk_id = chunk.next_chunk_id
            session.flush()
            session.add_all(
                [
                    ChunkSourceBlockModel(
                        chunk_id=chunk.id,
                        parsed_block_id=block_id,
                        order_index=order_index,
                    )
                    for chunk in chunks
                    for order_index, block_id in enumerate(chunk.source_block_ids)
                ]
            )
            session.add_all(
                [
                    ChunkAssetModel(chunk_id=chunk.id, parsed_asset_id=asset_id)
                    for chunk in chunks
                    for asset_id in chunk.asset_ids
                ]
            )
            item.status = "embedding"
            item.chunk_count = len(chunks)
            item.stage_progress = {
                "chunking": "succeeded",
                "embedding": "queued",
                "indexableChunkCount": len(indexable_chunk_ids),
                "warnings": list(warnings),
            }

    def load_indexable_chunks(self, item_id: UUID) -> tuple[ChunkDraft, ...]:
        with transaction(self._session_factory) as session:
            models = session.scalars(
                select(ChunkModel)
                .where(
                    ChunkModel.generation_item_id == item_id,
                    ChunkModel.chunk_kind.in_(("chunk", "child")),
                )
                .order_by(ChunkModel.order_index, ChunkModel.id)
            ).all()
            return tuple(self._chunk_domain(model) for model in models)

    def checkpoint_embedding(self, item_id: UUID, vector_count: int) -> None:
        self._checkpoint(
            item_id,
            expected="embedding",
            next_status="keyword_indexing",
            completed_stage="embedding",
            next_stage="keyword",
            vector_count=vector_count,
        )

    def checkpoint_keyword(self, item_id: UUID) -> None:
        self._checkpoint(
            item_id,
            expected="keyword_indexing",
            next_status="vector_indexing",
            completed_stage="keyword",
            next_stage="vector",
        )

    def checkpoint_vector(self, item_id: UUID) -> None:
        self._checkpoint(
            item_id,
            expected="vector_indexing",
            next_status="validating",
            completed_stage="vector",
            next_stage="validation",
        )

    def complete_validation(self, item_id: UUID) -> None:
        with transaction(self._session_factory) as session:
            item = self._locked_item(session, item_id)
            if item is None:
                raise RuntimeError("generation item does not exist")
            if item.status == "succeeded":
                return
            if item.status != "validating":
                raise RuntimeError("generation item is not validating")
            chunk_count = int(
                session.scalar(
                    select(func.count())
                    .select_from(ChunkModel)
                    .where(ChunkModel.generation_item_id == item_id)
                )
                or 0
            )
            mapped_count = int(
                session.scalar(
                    select(func.count(func.distinct(ChunkSourceBlockModel.chunk_id)))
                    .select_from(ChunkSourceBlockModel)
                    .join(ChunkModel, ChunkModel.id == ChunkSourceBlockModel.chunk_id)
                    .where(ChunkModel.generation_item_id == item_id)
                )
                or 0
            )
            if chunk_count == 0 or mapped_count != chunk_count or item.vector_count == 0:
                raise ValueError("generation item validation failed")
            progress = dict(item.stage_progress)
            progress["validation"] = "succeeded"
            item.stage_progress = progress
            item.status = "succeeded"
            item.finished_at = datetime.now(UTC)
            item.error_code = None
            item.error_message = None
            item.retryable = False

    def _checkpoint(
        self,
        item_id: UUID,
        *,
        expected: str,
        next_status: str,
        completed_stage: str,
        next_stage: str,
        vector_count: int | None = None,
    ) -> None:
        with transaction(self._session_factory) as session:
            item = self._locked_item(session, item_id)
            if item is None:
                raise RuntimeError("generation item does not exist")
            if item.status == next_status:
                return
            if item.status != expected:
                raise RuntimeError("generation item checkpoint is stale")
            progress = dict(item.stage_progress)
            progress[completed_stage] = "succeeded"
            progress[next_stage] = "queued"
            item.stage_progress = progress
            item.status = next_status
            if vector_count is not None:
                if vector_count <= 0:
                    raise ValueError("vector checkpoint cannot be empty")
                item.vector_count = vector_count

    @staticmethod
    def _locked_item(session: Session, item_id: UUID) -> IndexGenerationItemModel | None:
        return session.scalar(
            select(IndexGenerationItemModel)
            .where(IndexGenerationItemModel.id == item_id)
            .with_for_update()
        )

    @staticmethod
    def _chunk_model(item_id: UUID, generation_id: UUID, chunk: ChunkDraft) -> ChunkModel:
        return ChunkModel(
            id=chunk.id,
            index_generation_id=generation_id,
            generation_item_id=item_id,
            parsed_source_version_id=chunk.parsed_source_version_id,
            chunk_kind=chunk.chunk_kind,
            parent_chunk_id=None,
            order_index=chunk.order_index,
            text_content=chunk.text,
            searchable_text=chunk.searchable_text,
            normalized_text_hash=hashlib.sha256(
                normalize_text(chunk.text).encode("utf-8")
            ).hexdigest(),
            token_count=chunk.token_count.value,
            token_counter_code=chunk.token_count.counter_code,
            token_counter_version=chunk.token_count.counter_version,
            heading_path=list(chunk.heading_path) or None,
            page_range=list(chunk.page_numbers) or None,
            primary_page_number=min(chunk.page_numbers) if chunk.page_numbers else None,
            bounding_boxes=list(chunk.bounding_boxes) or None,
            previous_chunk_id=None,
            next_chunk_id=None,
        )

    @staticmethod
    def _chunk_domain(model: ChunkModel) -> ChunkDraft:
        return ChunkDraft(
            id=model.id,
            parsed_source_version_id=model.parsed_source_version_id,
            chunk_kind=model.chunk_kind,
            order_index=model.order_index,
            text=model.text_content,
            searchable_text=model.searchable_text,
            token_count=TokenCount(
                value=model.token_count,
                counter_code=model.token_counter_code,
                counter_version=model.token_counter_version,
                estimated=False,
            ),
            source_block_ids=(),
            asset_ids=(),
            heading_path=tuple(model.heading_path or ()),
            page_numbers=tuple(model.page_range or ()),
            bounding_boxes=tuple(model.bounding_boxes or ()),
            parent_chunk_id=model.parent_chunk_id,
            previous_chunk_id=model.previous_chunk_id,
            next_chunk_id=model.next_chunk_id,
        )
