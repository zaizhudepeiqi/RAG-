from dataclasses import dataclass
from typing import BinaryIO, Protocol


@dataclass(frozen=True)
class StoredBlob:
    storage_key: str
    sha256: str
    size_bytes: int


class SourceStorage(Protocol):
    def store_blob(self, source: BinaryIO, *, max_bytes: int) -> StoredBlob: ...

    def open_binary(self, storage_key: str) -> BinaryIO: ...

    def delete(self, storage_key: str) -> None: ...

    def exists(self, storage_key: str) -> bool: ...
