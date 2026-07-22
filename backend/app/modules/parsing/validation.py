from dataclasses import dataclass
from pathlib import PurePath
from typing import BinaryIO
from zipfile import BadZipFile, ZipFile, is_zipfile

from app.modules.capabilities.registry import INPUT_TYPE_MIME_TYPES

SNIFF_BYTES = 64 * 1024
OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
JP2_SIGNATURE = b"\x00\x00\x00\x0cjP  \r\n\x87\n"


class SourceTypeUnsupportedError(ValueError):
    pass


class SourceTypeMismatchError(ValueError):
    pass


@dataclass(frozen=True)
class InspectedSource:
    extension: str
    mime_type: str


def inspect_source(file_name: str, declared_mime_type: str, stream: BinaryIO) -> InspectedSource:
    extension = _extension(file_name)
    mime_type = declared_mime_type.split(";", 1)[0].strip().lower()
    if mime_type not in INPUT_TYPE_MIME_TYPES[extension]:
        raise SourceTypeMismatchError("declared MIME type does not match extension")

    original_position = stream.tell()
    try:
        stream.seek(0)
        sample = stream.read(SNIFF_BYTES)
        stream.seek(0)
        if not _signature_matches(extension, sample, stream):
            raise SourceTypeMismatchError("file signature does not match extension")
    finally:
        stream.seek(original_position)
    return InspectedSource(extension=extension, mime_type=mime_type)


def _extension(file_name: str) -> str:
    if not file_name or len(file_name) > 255 or "/" in file_name or "\\" in file_name:
        raise SourceTypeUnsupportedError("invalid source file name")
    suffix = PurePath(file_name).suffix
    if not suffix:
        raise SourceTypeUnsupportedError("source file has no extension")
    extension = suffix[1:].lower()
    if extension not in INPUT_TYPE_MIME_TYPES:
        raise SourceTypeUnsupportedError("source type is unsupported")
    return extension


def _signature_matches(extension: str, sample: bytes, stream: BinaryIO) -> bool:
    if extension == "pdf":
        return sample.startswith(b"%PDF-")
    if extension == "png":
        return sample.startswith(b"\x89PNG\r\n\x1a\n")
    if extension in {"jpg", "jpeg"}:
        return sample.startswith(b"\xff\xd8\xff")
    if extension == "gif":
        return sample.startswith((b"GIF87a", b"GIF89a"))
    if extension == "bmp":
        return sample.startswith(b"BM")
    if extension == "webp":
        return len(sample) >= 12 and sample.startswith(b"RIFF") and sample[8:12] == b"WEBP"
    if extension == "jp2":
        return sample.startswith(JP2_SIGNATURE) or sample.startswith(b"\xff\x4f\xff\x51")
    if extension in {"doc", "xls", "ppt"}:
        return sample.startswith(OLE_SIGNATURE)
    if extension in {"docx", "xlsx", "pptx", "zip"}:
        return _zip_structure_matches(extension, stream)
    if extension in {"htm", "html"}:
        normalized = sample.decode("utf-8-sig", errors="ignore").lstrip().lower()
        return normalized.startswith(("<!doctype html", "<html", "<head", "<body"))
    if extension in {"txt", "md", "csv", "json"}:
        if b"\x00" in sample:
            return False
        try:
            decoded = sample.decode("utf-8-sig")
        except UnicodeDecodeError:
            return False
        if extension == "json":
            return decoded.lstrip().startswith(("{", "["))
        return True
    return False


def _zip_structure_matches(extension: str, stream: BinaryIO) -> bool:
    try:
        if not is_zipfile(stream):
            return False
        stream.seek(0)
        with ZipFile(stream) as archive:
            names = set(archive.namelist())
    except (BadZipFile, OSError):
        return False
    if extension == "zip":
        return True
    required_entry = {
        "docx": "word/document.xml",
        "xlsx": "xl/workbook.xml",
        "pptx": "ppt/presentation.xml",
    }[extension]
    return "[Content_Types].xml" in names and required_entry in names
