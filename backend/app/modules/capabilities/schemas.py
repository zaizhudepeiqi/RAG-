from collections.abc import Mapping

from pydantic import Field

from app.core.schemas import ApiModel
from app.modules.capabilities.domain import CapabilityOption


class CapabilityOptionResponse(ApiModel):
    code: str
    name: str
    description: str
    enabled: bool
    visible: bool
    version: str
    category: str | None = None
    unavailable_reason: str | None = None
    config_schema: dict[str, object] | None = None
    ui_schema: dict[str, object] | None = None
    required_source_features: list[str] = Field(default_factory=list)
    preferred_source_features: list[str] = Field(default_factory=list)


def capability_response(option: CapabilityOption) -> CapabilityOptionResponse:
    return CapabilityOptionResponse(
        code=option.code,
        name=option.name,
        description=option.description,
        enabled=option.enabled,
        visible=option.visible,
        version=option.version,
        category=option.category,
        unavailable_reason=option.unavailable_reason,
        config_schema=_thaw_mapping(option.config_schema),
        ui_schema=_thaw_mapping(option.ui_schema),
        required_source_features=list(option.required_source_features),
        preferred_source_features=list(option.preferred_source_features),
    )


def _thaw_mapping(value: Mapping[str, object] | None) -> dict[str, object] | None:
    if value is None:
        return None
    return {key: _thaw_json(item) for key, item in value.items()}


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value
