from app.modules.capabilities.domain import CapabilityOption
from app.modules.capabilities.registry import CapabilityRegistry


class CapabilityService:
    def __init__(self, registry: CapabilityRegistry) -> None:
        self._registry = registry

    def list(
        self,
        *,
        category: str | None,
        include_disabled: bool,
    ) -> tuple[CapabilityOption, ...]:
        return self._registry.list(category=category, include_disabled=include_disabled)

    def get(self, code: str, version: str) -> CapabilityOption:
        return self._registry.get(code, version)
