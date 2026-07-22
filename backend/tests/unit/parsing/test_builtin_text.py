import pytest
from app.infrastructure.parsers.builtin_text import BuiltinTextParser, ParserInputError
from app.infrastructure.parsers.registry import ParserRegistry


@pytest.mark.parametrize(
    ("extension", "content", "expected_markdown"),
    [
        ("txt", "第一行\n第二行\n".encode(), "第一行\n第二行\n"),
        ("md", b"# Heading\n\nParagraph\n", "# Heading\n\nParagraph\n"),
        (
            "csv",
            b'name,note\nalpha,"one|two"\nbeta,"line 1\nline 2"\n',
            "| name | note |\n| --- | --- |\n| alpha | one\\|two |\n| beta | line 1<br>line 2 |",
        ),
        (
            "json",
            '{"z":1,"name":"知识","items":[true,null]}'.encode(),
            '{\n  "items": [\n    true,\n    null\n  ],\n  "name": "知识",\n  "z": 1\n}',
        ),
    ],
)
def test_builtin_text_produces_deterministic_markdown(
    extension: str,
    content: bytes,
    expected_markdown: str,
) -> None:
    parsed = BuiltinTextParser().parse(content, extension)

    assert parsed.markdown == expected_markdown
    assert parsed.blocks
    assert parsed.feature_flags["hasText"] is True
    assert parsed.feature_flags["hasBoundingBoxes"] is False


@pytest.mark.parametrize(
    ("extension", "content", "code"),
    [
        ("txt", b"invalid-utf8-\xff", "PARSER_INPUT_ENCODING_INVALID"),
        ("json", b'{"a": 1,}', "PARSER_INPUT_JSON_INVALID"),
        ("json", b'{"a": 1, "a": 2}', "PARSER_INPUT_JSON_INVALID"),
        ("csv", b"a,b\n1\n", "PARSER_INPUT_CSV_INVALID"),
    ],
)
def test_builtin_text_reports_stable_input_errors(
    extension: str,
    content: bytes,
    code: str,
) -> None:
    with pytest.raises(ParserInputError) as captured:
        BuiltinTextParser().parse(content, extension)

    assert captured.value.code == code


def test_parser_registry_rejects_duplicates_and_input_mismatch() -> None:
    parser = BuiltinTextParser()
    registry = ParserRegistry()
    registry.register(parser)

    assert registry.require("builtin_text", "1", "txt") is parser
    with pytest.raises(ValueError, match="already registered"):
        registry.register(BuiltinTextParser())
    with pytest.raises(ValueError, match="does not support"):
        registry.require("builtin_text", "1", "pdf")
