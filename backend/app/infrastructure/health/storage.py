from app.infrastructure.storage.local import LocalStorageAdapter
from app.modules.observability.ports import DependencyCode, DependencyStatus


class StorageHealthProbe:
    code: DependencyCode = "storage"
    required_for_readiness = True

    def __init__(self, adapter: LocalStorageAdapter) -> None:
        self._adapter = adapter

    def check(self) -> DependencyStatus:
        try:
            self._adapter.check_writable()
            return DependencyStatus(self.code, "healthy", "writable")
        except OSError:
            return DependencyStatus(self.code, "unhealthy", "storage unavailable")
