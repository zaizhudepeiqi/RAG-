from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.knowledge_bases.domain import (
    BuildConfigRevision,
    RetrievalConfig,
    RetrievalConfigRevision,
)
from app.modules.retrieval.engine import RetrievalResult, SingleKnowledgeBaseRetriever
from app.modules.retrieval.query_rewrite import QueryRewriteResult, QueryRewriteService


@dataclass(frozen=True)
class RetrievalTestSnapshot:
    knowledge_base_id: UUID
    generation_id: UUID
    collection_name: str
    build_revision: BuildConfigRevision
    retrieval_revision: RetrievalConfigRevision


class RetrievalTestSnapshotStore(Protocol):
    def get_active(
        self, session: Session, knowledge_base_id: UUID
    ) -> RetrievalTestSnapshot | None: ...


RetrieverFactory = Callable[[RetrievalTestSnapshot, RetrievalConfig], SingleKnowledgeBaseRetriever]
RewriteServiceFactory = Callable[[RetrievalConfig], QueryRewriteService]


@dataclass(frozen=True)
class RetrievalTestRun:
    snapshot: RetrievalTestSnapshot
    config: RetrievalConfig
    rewrite: QueryRewriteResult
    result: RetrievalResult


class RetrievalTestUnavailableError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("RETRIEVAL_TEST_UNAVAILABLE")
        self.code = "RETRIEVAL_TEST_UNAVAILABLE"


class RetrievalTestService:
    def __init__(
        self,
        snapshots: RetrievalTestSnapshotStore,
        retrievers: RetrieverFactory,
        rewrites: RewriteServiceFactory,
    ) -> None:
        self._snapshots = snapshots
        self._retrievers = retrievers
        self._rewrites = rewrites

    def run(
        self,
        session: Session,
        *,
        knowledge_base_id: UUID,
        query: str,
        override: RetrievalConfig | None = None,
    ) -> RetrievalTestRun:
        snapshot = self._snapshots.get_active(session, knowledge_base_id)
        if snapshot is None:
            raise RetrievalTestUnavailableError
        config = override or snapshot.retrieval_revision.config
        rewrite = self._rewrites(config).rewrite(
            query,
            code=config.query_rewrite.code,
            params=config.query_rewrite.params,
        )
        result = self._retrievers(snapshot, config).retrieve_many(
            session,
            generation_id=snapshot.generation_id,
            collection_name=snapshot.collection_name,
            queries=rewrite.queries,
            query_for_rerank=rewrite.original_query,
            config=config,
        )
        return RetrievalTestRun(snapshot, config, rewrite, result)
