import stat
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest
from app.modules.parsing.archive import (
    UnsafeArchiveError,
    open_safe_archive,
    validate_archive_directory,
)

MIB = 1024 * 1024


class ReportedSizeStream(BytesIO):
    def __init__(self, content: bytes, reported_size: int) -> None:
        super().__init__(content)
        self._reported_size = reported_size
        self._report_end = False

    def seek(self, offset: int, whence: int = 0) -> int:
        self._report_end = whence == 2 and offset == 0
        position = super().seek(offset, whence)
        return self._reported_size if self._report_end else position

    def tell(self) -> int:
        return self._reported_size if self._report_end else super().tell()


def archive_info(
    name: str,
    *,
    size_bytes: int = 10,
    compressed_bytes: int = 10,
) -> ZipInfo:
    info = ZipInfo(name)
    info.file_size = size_bytes
    info.compress_size = compressed_bytes
    return info


def zip_bytes(entries: dict[str, bytes]) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return output.getvalue()


@pytest.mark.parametrize(
    "name",
    [
        "../escape.txt",
        "safe/../../escape.txt",
        "/absolute.txt",
        "C:/drive.txt",
        "\\server\\share.txt",
        f"{'a' * 1021}.txt",
    ],
)
def test_archive_rejects_unsafe_or_oversized_paths(name: str) -> None:
    with pytest.raises(UnsafeArchiveError):
        validate_archive_directory([archive_info(name)])


@pytest.mark.parametrize("file_type", [stat.S_IFLNK, stat.S_IFCHR, stat.S_IFBLK])
def test_archive_rejects_links_and_device_entries(file_type: int) -> None:
    info = archive_info("unsafe.txt")
    info.create_system = 3
    info.external_attr = (file_type | 0o644) << 16

    with pytest.raises(UnsafeArchiveError):
        validate_archive_directory([info])


def test_archive_rejects_encrypted_and_nested_entries() -> None:
    encrypted = archive_info("encrypted.txt")
    encrypted.flag_bits |= 0x1

    with pytest.raises(UnsafeArchiveError):
        validate_archive_directory([encrypted])
    with pytest.raises(UnsafeArchiveError):
        validate_archive_directory([archive_info("folder/inner.ZIP")])


def test_archive_rejects_entry_count_and_size_limits() -> None:
    with pytest.raises(UnsafeArchiveError):
        validate_archive_directory([archive_info(f"{index}.txt") for index in range(101)])
    with pytest.raises(UnsafeArchiveError):
        validate_archive_directory([archive_info("large.txt", size_bytes=201 * MIB)])
    with pytest.raises(UnsafeArchiveError):
        validate_archive_directory(
            [
                archive_info(
                    f"{index}.txt",
                    size_bytes=180 * MIB,
                    compressed_bytes=180 * MIB,
                )
                for index in range(6)
            ]
        )


def test_archive_rejects_compression_ratio_over_100_to_1() -> None:
    with pytest.raises(UnsafeArchiveError):
        validate_archive_directory(
            [archive_info("compressed.txt", size_bytes=101, compressed_bytes=1)]
        )


def test_archive_rejects_oversized_container_before_opening_directory() -> None:
    stream = ReportedSizeStream(zip_bytes({"valid.txt": b"valid"}), 201 * MIB)

    with pytest.raises(UnsafeArchiveError):
        with open_safe_archive(stream):
            pass

    assert stream.tell() == 0


def test_archive_preserves_safe_posix_paths_and_skips_directories() -> None:
    entries = validate_archive_directory(
        [archive_info("folder/", size_bytes=0, compressed_bytes=0), archive_info("folder/a.txt")]
    )

    assert [entry.source_path for entry in entries] == ["folder/a.txt"]
    assert entries[0].original_file_name == "a.txt"


def test_archive_rejects_nested_zip_magic_with_a_disguised_extension() -> None:
    inner = zip_bytes({"nested.txt": b"nested"})
    outer = zip_bytes({"disguised.txt": inner})

    with pytest.raises(UnsafeArchiveError):
        with open_safe_archive(BytesIO(outer)):
            pass


def test_archive_allows_ooxml_container_entries() -> None:
    document = zip_bytes({"[Content_Types].xml": b"<Types/>", "word/document.xml": b"<w/>"})
    outer = zip_bytes({"documents/example.docx": document})

    with open_safe_archive(BytesIO(outer)) as archive:
        assert [entry.source_path for entry in archive.entries] == ["documents/example.docx"]
