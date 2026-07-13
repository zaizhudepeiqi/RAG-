from collections.abc import Mapping
from dataclasses import replace
from types import MappingProxyType

from app.modules.capabilities.domain import CapabilityOption
from app.modules.capabilities.errors import CapabilityNotFoundError


class CapabilityRegistry:
    def __init__(self) -> None:
        self._options: dict[tuple[str, str], CapabilityOption] = {}

    def register(self, option: CapabilityOption) -> None:
        key = (option.code, option.version)
        if key in self._options:
            raise ValueError("duplicate capability code and version")
        self._options[key] = replace(
            option,
            config_schema=_freeze_mapping(option.config_schema),
            ui_schema=_freeze_mapping(option.ui_schema),
            required_source_features=tuple(option.required_source_features),
            preferred_source_features=tuple(option.preferred_source_features),
        )

    def list(
        self,
        *,
        category: str | None,
        include_disabled: bool,
    ) -> tuple[CapabilityOption, ...]:
        options = (
            option
            for option in self._options.values()
            if option.visible
            and (category is None or option.category == category)
            and (include_disabled or option.enabled)
        )
        return tuple(sorted(options, key=lambda item: (item.code, item.version)))

    def get(self, code: str, version: str) -> CapabilityOption:
        try:
            return self._options[(code, version)]
        except KeyError as error:
            raise CapabilityNotFoundError from error


def _freeze_mapping(value: Mapping[str, object] | None) -> Mapping[str, object] | None:
    if value is None:
        return None
    return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})


def _freeze_json(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    return value
