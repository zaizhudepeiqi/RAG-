from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pytest
from app.infrastructure.storage.local import (
    EmptyStorageObjectError,
    LocalStorageAdapter,
    StorageKeyError,
    StorageLimitExceededError,
)


class FailingStream(BytesIO):
    def __init__(self, initial_bytes: bytes, *, fail_after_reads: int) -> None:
        super().__init__(initial_bytes)
        self._fail_after_reads = fail_after_reads
        self._reads = 0

    def read(self, size: int = -1) -> bytes:
        self._reads += 1
        if self._reads > self._fail_after_reads:
            raise OSError("simulated upload failure")
        return super().read(size)


def uploading_files(root: Path) -> list[Path]:
    directory = root / ".uploading"
    return list(directory.glob("*")) if directory.exists() else []


def test_store_blob_streams_to_content_addressed_atomic_path(tmp_path: Path) -> None:
    storage = LocalStorageAdapter(tmp_path)
    content = b"0123456789" * 300_000

    stored = storage.store_blob(BytesIO(content), max_bytes=len(content))

    digest = sha256(content).hexdigest()
    assert stored.sha256 == digest
    assert stored.size_bytes == len(content)
    assert stored.storage_key == f"blobs/{digest[:2]}/{digest}"
    with storage.open_binary(stored.storage_key) as handle:
        assert handle.read() == content
    assert uploading_files(tmp_path) == []


def test_duplicate_content_reuses_one_physical_blob(tmp_path: Path) -> None:
    storage = LocalStorageAdapter(tmp_path)
    content = b"duplicate-content"

    first = storage.store_blob(BytesIO(content), max_bytes=100)
    second = storage.store_blob(BytesIO(content), max_bytes=100)

    assert first == second
    assert len(list((tmp_path / "blobs").rglob(first.sha256))) == 1
    assert uploading_files(tmp_path) == []


@pytest.mark.parametrize(
    ("stream", "max_bytes", "error_type"),
    [
        (BytesIO(b""), 10, EmptyStorageObjectError),
        (BytesIO(b"too large"), 3, StorageLimitExceededError),
        (FailingStream(b"read then fail", fail_after_reads=1), 100, OSError),
    ],
)
def test_failed_store_removes_temporary_file(
    tmp_path: Path,
    stream: BytesIO,
    max_bytes: int,
    error_type: type[Exception],
) -> None:
    storage = LocalStorageAdapter(tmp_path, chunk_size=4)

    with pytest.raises(error_type):
        storage.store_blob(stream, max_bytes=max_bytes)

    assert uploading_files(tmp_path) == []
    assert not (tmp_path / "blobs").exists()


@pytest.mark.parametrize(
    "storage_key",
    ["", "../secret", "/absolute", "C:/windows", "blobs\\escape", "blobs/./file"],
)
def test_storage_key_cannot_escape_root(tmp_path: Path, storage_key: str) -> None:
    storage = LocalStorageAdapter(tmp_path)

    with pytest.raises(StorageKeyError):
        storage.open_binary(storage_key)
