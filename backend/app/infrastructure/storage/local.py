import os
from hashlib import sha256
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from app.modules.parsing.ports import StoredBlob


class StorageLimitExceededError(ValueError):
    pass


class EmptyStorageObjectError(ValueError):
    pass


class StorageKeyError(ValueError):
    pass


class LocalStorageAdapter:
    def __init__(self, root: Path, *, chunk_size: int = 1024 * 1024) -> None:
        if not root.is_absolute():
            raise ValueError("storage root must be absolute")
        if chunk_size < 1:
            raise ValueError("chunk size must be positive")
        self._root = root.resolve()
        self._chunk_size = chunk_size

    def check_writable(self) -> None:
        health_dir = self._root / ".health"
        health_dir.mkdir(parents=True, exist_ok=True)
        source = health_dir / f"{uuid4()}.tmp"
        target = health_dir / f"{uuid4()}.ok"
        try:
            with source.open("wb") as handle:
                handle.write(b"ok")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(source, target)
        finally:
            source.unlink(missing_ok=True)
            target.unlink(missing_ok=True)

    def store_blob(self, source: BinaryIO, *, max_bytes: int) -> StoredBlob:
        if max_bytes < 1:
            raise ValueError("max bytes must be positive")
        upload_dir = self._root / ".uploading"
        upload_dir.mkdir(parents=True, exist_ok=True)
        temporary_path = upload_dir / f"{uuid4()}.part"
        digest = sha256()
        size_bytes = 0
        try:
            with temporary_path.open("xb") as handle:
                while chunk := source.read(self._chunk_size):
                    size_bytes += len(chunk)
                    if size_bytes > max_bytes:
                        raise StorageLimitExceededError("source exceeds maximum size")
                    digest.update(chunk)
                    handle.write(chunk)
                if size_bytes == 0:
                    raise EmptyStorageObjectError("source is empty")
                handle.flush()
                os.fsync(handle.fileno())

            hash_value = digest.hexdigest()
            storage_key = f"blobs/{hash_value[:2]}/{hash_value}"
            target_path = self._resolve_key(storage_key)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            if target_path.exists():
                temporary_path.unlink()
            else:
                os.replace(temporary_path, target_path)
            return StoredBlob(
                storage_key=storage_key,
                sha256=hash_value,
                size_bytes=size_bytes,
            )
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise

    def open_binary(self, storage_key: str) -> BinaryIO:
        return self._resolve_key(storage_key).open("rb")

    def delete(self, storage_key: str) -> None:
        self._resolve_key(storage_key).unlink(missing_ok=True)

    def exists(self, storage_key: str) -> bool:
        return self._resolve_key(storage_key).is_file()

    def _resolve_key(self, storage_key: str) -> Path:
        if (
            not storage_key
            or "\\" in storage_key
            or storage_key.startswith("/")
            or any(part in {"", ".", ".."} or ":" in part for part in storage_key.split("/"))
        ):
            raise StorageKeyError("invalid storage key")
        resolved = (self._root / Path(*storage_key.split("/"))).resolve()
        if not resolved.is_relative_to(self._root):
            raise StorageKeyError("storage key escapes root")
        return resolved
