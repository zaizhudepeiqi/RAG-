import re
import stat
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import BinaryIO, cast
from zipfile import BadZipFile, ZipFile, ZipInfo

MAX_ARCHIVE_ENTRIES = 100
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
MAX_ARCHIVE_ENTRY_BYTES = 200 * 1024 * 1024
MAX_ARCHIVE_COMPRESSION_RATIO = 100
MAX_ARCHIVE_PATH_LENGTH = 1024

_DRIVE_PATH = re.compile(r"^[A-Za-z]:")
_ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
_OOXML_EXTENSIONS = {"docx", "pptx", "xlsx"}


class UnsafeArchiveError(ValueError):
    pass


@dataclass(frozen=True)
class ArchiveEntry:
    source_path: str
    original_file_name: str
    info: ZipInfo


@dataclass(frozen=True)
class SafeArchive:
    entries: tuple[ArchiveEntry, ...]
    _archive: ZipFile

    def open_entry(self, entry: ArchiveEntry) -> BinaryIO:
        return cast(BinaryIO, self._archive.open(entry.info, "r"))


def validate_archive_directory(infos: Iterable[ZipInfo]) -> tuple[ArchiveEntry, ...]:
    entries: list[ArchiveEntry] = []
    seen_paths: set[str] = set()
    total_size = 0

    for info in infos:
        source_path = _safe_source_path(info.filename, is_directory=info.is_dir())
        _validate_entry_type(info)
        if info.flag_bits & 0x1:
            raise UnsafeArchiveError("encrypted ZIP entries are not supported")
        if info.is_dir():
            continue
        if source_path in seen_paths:
            raise UnsafeArchiveError("duplicate ZIP entry path")
        seen_paths.add(source_path)

        if PurePosixPath(source_path).suffix.casefold() == ".zip":
            raise UnsafeArchiveError("nested ZIP entries are not supported")
        if info.file_size < 0 or info.file_size > MAX_ARCHIVE_ENTRY_BYTES:
            raise UnsafeArchiveError("ZIP entry exceeds size limit")
        if info.file_size > 0 and (
            info.compress_size <= 0
            or info.file_size > info.compress_size * MAX_ARCHIVE_COMPRESSION_RATIO
        ):
            raise UnsafeArchiveError("ZIP entry exceeds compression ratio limit")

        total_size += info.file_size
        if total_size > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
            raise UnsafeArchiveError("ZIP content exceeds total size limit")
        entries.append(
            ArchiveEntry(
                source_path=source_path,
                original_file_name=PurePosixPath(source_path).name,
                info=info,
            )
        )
        if len(entries) > MAX_ARCHIVE_ENTRIES:
            raise UnsafeArchiveError("ZIP contains too many files")

    if not entries:
        raise UnsafeArchiveError("ZIP contains no files")
    return tuple(entries)


@contextmanager
def open_safe_archive(source: BinaryIO) -> Iterator[SafeArchive]:
    original_position = source.tell()
    archive: ZipFile | None = None
    try:
        source.seek(0, 2)
        if source.tell() > MAX_ARCHIVE_ENTRY_BYTES:
            raise UnsafeArchiveError("ZIP archive exceeds size limit")
        source.seek(0)
        archive = ZipFile(source)
        entries = validate_archive_directory(archive.infolist())
        _reject_disguised_nested_archives(archive, entries)
    except UnsafeArchiveError:
        if archive is not None:
            archive.close()
        source.seek(original_position)
        raise
    except (BadZipFile, EOFError, OSError, RuntimeError) as error:
        if archive is not None:
            archive.close()
        source.seek(original_position)
        raise UnsafeArchiveError("ZIP archive is invalid") from error

    try:
        yield SafeArchive(entries=entries, _archive=archive)
    finally:
        archive.close()
        source.seek(original_position)


def _safe_source_path(name: str, *, is_directory: bool) -> str:
    normalized = name.replace("\\", "/")
    if (
        not normalized
        or "\x00" in normalized
        or len(normalized) > MAX_ARCHIVE_PATH_LENGTH
        or normalized.startswith("/")
        or _DRIVE_PATH.match(normalized)
    ):
        raise UnsafeArchiveError("ZIP entry path is unsafe")

    parts = normalized.split("/")
    if is_directory and parts[-1] == "":
        parts = parts[:-1]
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise UnsafeArchiveError("ZIP entry path is unsafe")
    return "/".join(parts)


def _validate_entry_type(info: ZipInfo) -> None:
    if info.create_system != 3:
        return
    mode = (info.external_attr >> 16) & 0xFFFF
    file_type = stat.S_IFMT(mode)
    expected = stat.S_IFDIR if info.is_dir() else stat.S_IFREG
    if file_type not in {0, expected}:
        raise UnsafeArchiveError("ZIP entry is not a regular file")


def _reject_disguised_nested_archives(
    archive: ZipFile,
    entries: tuple[ArchiveEntry, ...],
) -> None:
    for entry in entries:
        with archive.open(entry.info, "r") as handle:
            signature = handle.read(4)
        extension = PurePosixPath(entry.source_path).suffix.lstrip(".").casefold()
        if signature in _ZIP_SIGNATURES and extension not in _OOXML_EXTENSIONS:
            raise UnsafeArchiveError("nested ZIP entries are not supported")
