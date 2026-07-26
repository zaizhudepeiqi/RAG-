from collections.abc import Sequence
from importlib.metadata import version
from typing import Protocol

import tiktoken

from app.modules.chunking.domain import TokenCount


class TokenCounter(Protocol):
    code: str
    version: str
    estimated: bool

    def count(self, text: str) -> TokenCount: ...
    def encode(self, text: str) -> Sequence[int]: ...
    def decode(self, tokens: Sequence[int]) -> str: ...


class Cl100kTokenCounter:
    code = "tiktoken_cl100k_base"
    version = f"tiktoken-{version('tiktoken')}:cl100k_base-v1"
    estimated = True

    def __init__(self) -> None:
        self._encoding = tiktoken.get_encoding("cl100k_base")

    def count(self, text: str) -> TokenCount:
        return TokenCount(
            value=len(self.encode(text)),
            counter_code=self.code,
            counter_version=self.version,
            estimated=self.estimated,
        )

    def encode(self, text: str) -> Sequence[int]:
        return self._encoding.encode(text, disallowed_special=())

    def decode(self, tokens: Sequence[int]) -> str:
        return self._encoding.decode(list(tokens))
