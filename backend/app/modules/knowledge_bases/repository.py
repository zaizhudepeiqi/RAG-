from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.knowledge_bases.domain import (
    BuildConfigRevision,
    GenerationDetails,
    GenerationRecord,
    InitialKnowledgeBaseGraph,
    KnowledgeBase,
    KnowledgeBaseRuntimeSnapshot,
    NewGenerationGraph,
    RetrievalConfigRevision,
    SourceSelectionSnapshot,
)


@dataclass(frozen=True)
class KnowledgeBaseListQuery:
    search: str | None = None
    page: int = 1
    page_size: int = 20


@dataclass(frozen=True)
class KnowledgeBasePage:
    items: list[KnowledgeBase]
    total: int
    page: int
    page_size: int


class KnowledgeBaseRepository(Protocol):
    def find_by_name(self, session: Session, name: str) -> KnowledgeBase | None: ...

    def get(
        self,
        session: Session,
        knowledge_base_id: UUID,
        *,
        for_update: bool = False,
    ) -> KnowledgeBase | None: ...

    def list(self, session: Session, query: KnowledgeBaseListQuery) -> KnowledgeBasePage: ...

    def load_source_snapshots(
        self,
        session: Session,
        source_ids: tuple[UUID, ...],
    ) -> tuple[SourceSelectionSnapshot, ...]: ...

    def add_initial_graph(self, session: Session, graph: InitialKnowledgeBaseGraph) -> None: ...

    def attach_operation(
        self,
        session: Session,
        *,
        knowledge_base_id: UUID,
        generation_id: UUID,
        operation_id: UUID,
    ) -> None: ...

    def find_generation_id_by_operation(
        self,
        session: Session,
        operation_id: UUID,
    ) -> UUID | None: ...

    def runtime_snapshot(
        self,
        session: Session,
        knowledge_base: KnowledgeBase,
    ) -> KnowledgeBaseRuntimeSnapshot: ...

    def save(self, session: Session, knowledge_base: KnowledgeBase) -> None: ...

    def get_build_config_revision(
        self, session: Session, revision_id: UUID
    ) -> BuildConfigRevision | None: ...

    def find_build_config_revision_by_hash(
        self, session: Session, knowledge_base_id: UUID, config_hash: str
    ) -> BuildConfigRevision | None: ...

    def add_build_config_revision(
        self, session: Session, revision: BuildConfigRevision
    ) -> None: ...

    def next_build_revision_number(self, session: Session, knowledge_base_id: UUID) -> int: ...

    def get_retrieval_config_revision(
        self, session: Session, revision_id: UUID
    ) -> RetrievalConfigRevision | None: ...

    def find_retrieval_config_revision_by_hash(
        self, session: Session, knowledge_base_id: UUID, config_hash: str
    ) -> RetrievalConfigRevision | None: ...

    def add_retrieval_config_revision(
        self, session: Session, revision: RetrievalConfigRevision
    ) -> None: ...

    def next_retrieval_revision_number(self, session: Session, knowledge_base_id: UUID) -> int: ...

    def add_generation(self, session: Session, graph: NewGenerationGraph) -> None: ...

    def attach_generation_operation(
        self, session: Session, generation_id: UUID, operation_id: UUID
    ) -> None: ...

    def list_generations(
        self, session: Session, knowledge_base_id: UUID
    ) -> Sequence[GenerationRecord]: ...

    def get_generation(
        self, session: Session, knowledge_base_id: UUID, generation_id: UUID
    ) -> GenerationDetails | None: ...

    def set_generation_status(
        self, session: Session, generation_id: UUID, status: str
    ) -> GenerationRecord: ...
