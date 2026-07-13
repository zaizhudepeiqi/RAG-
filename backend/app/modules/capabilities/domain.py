from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class CapabilityOption:
    code: str
    name: str
    description: str
    enabled: bool
    visible: bool
    version: str
    category: str | None = None
    unavailable_reason: str | None = None
    config_schema: Mapping[str, object] | None = None
    ui_schema: Mapping[str, object] | None = None
    required_source_features: tuple[str, ...] = ()
    preferred_source_features: tuple[str, ...] = ()
