from typing import Protocol

from app.modules.parsing.normalization import NormalizedDocument


class ParserAdapter(Protocol):
    code: str
    version: str
    supported_extensions: frozenset[str]

    def parse(self, content: bytes, extension: str) -> NormalizedDocument: ...


class ParserRegistry:
    def __init__(self) -> None:
        self._adapters: dict[tuple[str, str], ParserAdapter] = {}

    def register(self, adapter: ParserAdapter) -> None:
        key = (adapter.code, adapter.version)
        if key in self._adapters:
            raise ValueError("parser code and version already registered")
        self._adapters[key] = adapter

    def require(self, code: str, version: str, extension: str) -> ParserAdapter:
        try:
            adapter = self._adapters[(code, version)]
        except KeyError as error:
            raise LookupError("parser is not registered") from error
        if extension.casefold() not in adapter.supported_extensions:
            raise ValueError(f"parser does not support {extension}")
        return adapter
