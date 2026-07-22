from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from app.modules.parsing.validation import (
    SourceTypeMismatchError,
    SourceTypeUnsupportedError,
    inspect_source,
)


def zip_bytes(entries: dict[str, bytes]) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return output.getvalue()


VALID_SOURCES = [
    ("sample.pdf", "application/pdf", b"%PDF-1.7\nbody"),
    ("sample.png", "image/png", b"\x89PNG\r\n\x1a\ncontent"),
    ("sample.jpg", "image/jpeg", b"\xff\xd8\xff\xe0content"),
    ("sample.jpeg", "image/jpeg", b"\xff\xd8\xff\xe1content"),
    ("sample.gif", "image/gif", b"GIF89acontent"),
    ("sample.bmp", "image/bmp", b"BMcontent"),
    ("sample.webp", "image/webp", b"RIFF\x10\x00\x00\x00WEBPcontent"),
    ("sample.jp2", "image/jp2", b"\x00\x00\x00\x0cjP  \r\n\x87\ncontent"),
    ("sample.html", "text/html", b"<!doctype html><html></html>"),
    ("sample.htm", "text/html; charset=utf-8", b"<html><body>ok</body></html>"),
    ("sample.txt", "text/plain", "plain 知识".encode()),
    ("sample.md", "text/markdown", b"# Heading\n\nText"),
    ("sample.csv", "text/csv", b"name,value\nalpha,1\n"),
    ("sample.json", "application/json", b'{"name":"alpha"}'),
    (
        "sample.doc",
        "application/msword",
        b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1legacy",
    ),
    (
        "sample.xls",
        "application/vnd.ms-excel",
        b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1legacy",
    ),
    (
        "sample.ppt",
        "application/vnd.ms-powerpoint",
        b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1legacy",
    ),
    (
        "sample.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        zip_bytes({"[Content_Types].xml": b"<Types/>", "word/document.xml": b"<w/>"}),
    ),
    (
        "sample.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        zip_bytes({"[Content_Types].xml": b"<Types/>", "xl/workbook.xml": b"<x/>"}),
    ),
    (
        "sample.pptx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        zip_bytes({"[Content_Types].xml": b"<Types/>", "ppt/presentation.xml": b"<p/>"}),
    ),
    ("batch.zip", "application/zip", zip_bytes({"sample.txt": b"hello"})),
]


@pytest.mark.parametrize(("file_name", "mime_type", "content"), VALID_SOURCES)
def test_supported_source_requires_matching_extension_mime_and_signature(
    file_name: str,
    mime_type: str,
    content: bytes,
) -> None:
    stream = BytesIO(content)
    stream.seek(min(2, len(content)))
    original_position = stream.tell()

    inspected = inspect_source(file_name, mime_type, stream)

    assert inspected.extension == file_name.rsplit(".", 1)[1].lower()
    assert inspected.mime_type == mime_type.split(";", 1)[0]
    assert stream.tell() == original_position


@pytest.mark.parametrize(
    ("file_name", "mime_type", "content"),
    [
        ("fake.pdf", "application/pdf", b"not a pdf"),
        ("fake.png", "image/jpeg", b"\x89PNG\r\n\x1a\ncontent"),
        ("fake.docx", "application/zip", zip_bytes({"word/document.xml": b"<w/>"})),
        (
            "fake.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            zip_bytes({"xl/workbook.xml": b"<x/>"}),
        ),
        ("fake.json", "application/json", b"plain text"),
        ("fake.txt", "text/plain", b"contains\x00binary"),
    ],
)
def test_mismatched_source_type_is_rejected(
    file_name: str,
    mime_type: str,
    content: bytes,
) -> None:
    with pytest.raises(SourceTypeMismatchError):
        inspect_source(file_name, mime_type, BytesIO(content))


@pytest.mark.parametrize("file_name", ["sample.exe", "no-extension", f"a{'.txt':->256}"])
def test_unsupported_or_invalid_file_name_is_rejected(file_name: str) -> None:
    with pytest.raises(SourceTypeUnsupportedError):
        inspect_source(file_name, "application/octet-stream", BytesIO(b"content"))
