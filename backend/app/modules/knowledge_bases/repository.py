from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.knowledge_bases.domain import (
    InitialKnowledgeBaseGraph,
    KnowledgeBase,
    KnowledgeBaseRuntimeSnapshot,
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
