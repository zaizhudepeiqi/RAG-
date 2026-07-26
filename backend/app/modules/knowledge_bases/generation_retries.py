from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.modules.knowledge_bases.tasks import GenerationBuildHandler

KNOWLEDGE_BASE_RETRY_TASK = "knowledge_base_build_retry"


@dataclass(frozen=True)
class GenerationRetryPreparation:
    generation_id: UUID
    repair_created: bool


class GenerationRetryStore(Protocol):
    def prepare(self, operation_id: UUID) -> GenerationRetryPreparation: ...


class GenerationRetryHandler:
    def __init__(self, store: GenerationRetryStore, builds: GenerationBuildHandler) -> None:
        self._store = store
        self._builds = builds

    def run(self, operation_id: UUID) -> dict[str, object]:
        preparation = self._store.prepare(operation_id)
        result = self._builds.run(operation_id)
        return {
            **result,
            "repairCreated": preparation.repair_created,
        }
