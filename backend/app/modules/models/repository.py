from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.models.domain import ModelProvider

ProviderSort = Literal["display_name", "-display_name", "created_at", "-created_at"]


@dataclass(frozen=True)
class ModelProviderListQuery:
    search: str | None = None
    enabled: bool | None = None
    page: int = 1
    page_size: int = 20
    sort: ProviderSort = "display_name"


@dataclass(frozen=True)
class ModelProviderPage:
    items: list[ModelProvider]
    total: int
    page: int
    page_size: int


class ModelProviderRepository(Protocol):
    def add(self, session: Session, provider: ModelProvider) -> None: ...

    def get(
        self,
        session: Session,
        provider_id: UUID,
        *,
        for_update: bool = False,
    ) -> ModelProvider | None: ...

    def find_by_display_name(
        self,
        session: Session,
        display_name: str,
    ) -> ModelProvider | None: ...

    def list(
        self,
        session: Session,
        query: ModelProviderListQuery,
    ) -> ModelProviderPage: ...

    def save(self, session: Session, provider: ModelProvider) -> None: ...

    def has_models(self, session: Session, provider_id: UUID) -> bool: ...

    def mark_models_stale(self, session: Session, provider_id: UUID) -> None: ...
