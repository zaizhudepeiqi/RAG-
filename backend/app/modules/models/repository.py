from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.models.domain import (
    DiscoveredModelCandidate,
    ModelConfig,
    ModelProvider,
    ModelReference,
    ModelType,
    ModelVerificationSnapshot,
)

ProviderSort = Literal["display_name", "-display_name", "created_at", "-created_at"]
ModelSort = Literal["display_name", "-display_name", "created_at", "-created_at"]


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

    def list_discovered_candidates(
        self,
        session: Session,
        provider_id: UUID,
        *,
        model_type: ModelType | None,
        provider_status: str | None,
    ) -> Sequence[DiscoveredModelCandidate]: ...


@dataclass(frozen=True)
class ModelConfigListQuery:
    provider_id: UUID | None = None
    model_type: ModelType | None = None
    enabled: bool | None = None
    verification_status: str | None = None
    search: str | None = None
    page: int = 1
    page_size: int = 20
    sort: ModelSort = "display_name"


@dataclass(frozen=True)
class ModelConfigPage:
    items: list[ModelConfig]
    total: int
    page: int
    page_size: int


class ModelConfigRepository(Protocol):
    def add(self, session: Session, model: ModelConfig) -> None: ...

    def get(
        self,
        session: Session,
        model_id: UUID,
        *,
        for_update: bool = False,
    ) -> ModelConfig | None: ...

    def find_identity(
        self,
        session: Session,
        provider_id: UUID,
        model_name: str,
        model_type: ModelType,
    ) -> ModelConfig | None: ...

    def list(self, session: Session, query: ModelConfigListQuery) -> ModelConfigPage: ...

    def save(self, session: Session, model: ModelConfig) -> None: ...

    def latest_verification(
        self,
        session: Session,
        model_id: UUID,
    ) -> ModelVerificationSnapshot | None: ...

    def references(self, session: Session, model_id: UUID) -> tuple[ModelReference, ...]: ...
