import csv
import json
from io import StringIO
from typing import Any

from app.modules.parsing.normalization import NormalizedBlock, NormalizedDocument


class ParserInputError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _DuplicateJsonKeyError(ValueError):
    pass


class BuiltinTextParser:
    code = "builtin_text"
    version = "1"
    supported_extensions = frozenset({"csv", "json", "md", "txt"})

    def parse(self, content: bytes, extension: str) -> NormalizedDocument:
        extension = extension.casefold()
        if extension not in self.supported_extensions:
            raise ValueError(f"builtin_text does not support {extension}")
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise ParserInputError("PARSER_INPUT_ENCODING_INVALID") from error
        if extension == "csv":
            markdown = self._csv_markdown(text)
            block_type = "table"
        elif extension == "json":
            markdown = self._json_markdown(text)
            block_type = "code"
        else:
            if not text:
                raise ParserInputError("PARSER_OUTPUT_EMPTY")
            markdown = text
            block_type = "markdown" if extension == "md" else "text"
        return NormalizedDocument(
            markdown=markdown,
            blocks=(
                NormalizedBlock(
                    block_type=block_type,
                    order_index=0,
                    text_content=markdown,
                    markdown_content=markdown,
                ),
            ),
            feature_flags={
                "hasText": bool(markdown),
                "hasPages": False,
                "hasHeadings": extension == "md"
                and any(line.startswith("#") for line in markdown.splitlines()),
                "hasBoundingBoxes": False,
                "hasAssets": False,
                "hasTables": extension == "csv",
                "hasFormulas": False,
            },
        )

    @staticmethod
    def _csv_markdown(text: str) -> str:
        try:
            rows = list(csv.reader(StringIO(text, newline=""), strict=True))
        except csv.Error as error:
            raise ParserInputError("PARSER_INPUT_CSV_INVALID") from error
        if not rows or not rows[0] or any(len(row) != len(rows[0]) for row in rows):
            raise ParserInputError("PARSER_INPUT_CSV_INVALID")
        escaped = [[_escape_markdown_cell(cell) for cell in row] for row in rows]
        lines = [
            f"| {' | '.join(escaped[0])} |",
            f"| {' | '.join('---' for _ in escaped[0])} |",
        ]
        lines.extend(f"| {' | '.join(row)} |" for row in escaped[1:])
        return "\n".join(lines)

    @staticmethod
    def _json_markdown(text: str) -> str:
        try:
            value = json.loads(text, object_pairs_hook=_unique_object)
        except (json.JSONDecodeError, _DuplicateJsonKeyError) as error:
            raise ParserInputError("PARSER_INPUT_JSON_INVALID") from error
        return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKeyError
        result[key] = value
    return result


def _escape_markdown_cell(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("\r\n", "<br>")
        .replace("\n", "<br>")
        .replace("\r", "<br>")
    )
