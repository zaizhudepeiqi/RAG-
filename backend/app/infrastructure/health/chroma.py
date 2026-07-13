import httpx

from app.infrastructure.vector.chroma import ChromaAdapter
from app.modules.observability.ports import DependencyCode, DependencyStatus


class ChromaHealthProbe:
    code: DependencyCode = "chroma"
    required_for_readiness = True

    def __init__(self, adapter: ChromaAdapter) -> None:
        self._adapter = adapter

    def check(self) -> DependencyStatus:
        try:
            self._adapter.heartbeat()
            return DependencyStatus(self.code, "healthy", "available")
        except httpx.HTTPError:
            return DependencyStatus(self.code, "unhealthy", "chroma unavailable")
