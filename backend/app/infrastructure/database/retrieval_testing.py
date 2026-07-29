from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.infrastructure.database.models.knowledge_bases import IndexGenerationModel
from app.infrastructure.database.repositories.knowledge_bases import (
    SqlAlchemyKnowledgeBaseRepository,
)
from app.modules.retrieval.testing import RetrievalTestSnapshot


class SqlAlchemyRetrievalTestSnapshotStore:
    def __init__(self) -> None:
        self._knowledge_bases = SqlAlchemyKnowledgeBaseRepository()

    def get_active(self, session: Session, knowledge_base_id: UUID) -> RetrievalTestSnapshot | None:
        knowledge_base = self._knowledge_bases.get(session, knowledge_base_id)
        if (
            knowledge_base is None
            or not knowledge_base.enabled
            or knowledge_base.active_generation_id is None
            or knowledge_base.active_retrieval_revision_id is None
        ):
            return None
        generation = session.get(IndexGenerationModel, knowledge_base.active_generation_id)
        if (
            generation is None
            or generation.knowledge_base_id != knowledge_base_id
            or generation.status not in {"succeeded", "partial_ready"}
            or not generation.is_frozen
        ):
            return None
        build = self._knowledge_bases.get_build_config_revision(
            session, generation.build_config_revision_id
        )
        retrieval = self._knowledge_bases.get_retrieval_config_revision(
            session, knowledge_base.active_retrieval_revision_id
        )
        if (
            build is None
            or retrieval is None
            or build.knowledge_base_id != knowledge_base_id
            or retrieval.knowledge_base_id != knowledge_base_id
        ):
            return None
        return RetrievalTestSnapshot(
            knowledge_base_id=knowledge_base_id,
            generation_id=generation.id,
            collection_name=generation.collection_name,
            build_revision=build,
            retrieval_revision=retrieval,
        )
