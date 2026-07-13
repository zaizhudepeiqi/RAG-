from dataclasses import dataclass
from typing import Literal, Protocol

DependencyCode = Literal["postgresql", "redis", "chroma", "storage", "celery", "mineru", "models"]
DependencyState = Literal["healthy", "degraded", "unhealthy", "not_configured"]


@dataclass(frozen=True)
class DependencyStatus:
    code: DependencyCode
    status: DependencyState
    message: str


class DependencyProbe(Protocol):
    code: DependencyCode
    required_for_readiness: bool

    def check(self) -> DependencyStatus: ...
