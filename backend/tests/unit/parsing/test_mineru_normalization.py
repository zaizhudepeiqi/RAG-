import json
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from app.modules.parsing.normalization import (
    MinerUNormalizationError,
    normalize_mineru_archive,
)


def archive(entries: dict[str, bytes]) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as bundle:
        for path, content in entries.items():
            bundle.writestr(path, content)
    return output.getvalue()


def content_list(items: list[dict[str, object]]) -> bytes:
    return json.dumps(items, ensure_ascii=False).encode("utf-8")


def test_known_mineru_markdown_and_content_list_preserve_source_mapping() -> None:
    document = normalize_mineru_archive(
        archive(
            {
                "contract/auto/contract.md": (
                    b"# Contract\n\nClause body\n\n![Chart](images/chart.png)\n"
                ),
                "contract/auto/contract_content_list.json": content_list(
                    [
                        {
                            "type": "text",
                            "text": "Contract",
                            "text_level": 1,
                            "page_idx": 0,
                            "bbox": [10, 20, 100, 40],
                        },
                        {
                            "type": "text",
                            "text": "Clause body",
                            "page_idx": 0,
                            "bbox": [10, 50, 100, 80],
                        },
                        {
                            "type": "image",
                            "img_path": "images/chart.png",
                            "image_caption": ["Quarterly chart"],
                            "page_idx": 1,
                            "bbox": [20, 30, 180, 160],
                        },
                    ]
                ),
                "contract/auto/images/chart.png": b"\x89PNG\r\n\x1a\nfixture",
            }
        )
    )

    assert document.markdown.startswith("# Contract")
    assert document.quality_level == "full"
    assert document.page_count == 2
    assert len(document.blocks) == 3
    assert document.blocks[0].heading_level == 1
    assert document.blocks[0].page_number == 1
    assert document.blocks[0].bounding_box == {
        "x0": 10.0,
        "y0": 20.0,
        "x1": 100.0,
        "y1": 40.0,
    }
    assert document.blocks[0].raw_locator == {
        "artifactPath": "contract/auto/contract_content_list.json",
        "itemIndex": 0,
        "providerPageIndex": 0,
    }
    assert document.blocks[2].asset_source_paths == ("contract/auto/images/chart.png",)
    assert len(document.assets) == 1
    assert document.assets[0].mime_type == "image/png"
    assert document.assets[0].caption == "Quarterly chart"
    assert document.feature_flags["hasBoundingBoxes"] is True
    assert document.feature_flags["hasAssets"] is True


def test_missing_coordinates_are_null_and_mark_document_degraded() -> None:
    document = normalize_mineru_archive(
        archive(
            {
                "result.md": b"Body",
                "result_content_list.json": content_list(
                    [{"type": "text", "text": "Body", "page_idx": 0}]
                ),
            }
        )
    )

    assert document.quality_level == "degraded"
    assert document.blocks[0].page_number == 1
    assert document.blocks[0].bounding_box is None
    assert document.feature_flags["hasBoundingBoxes"] is False


def test_markdown_only_and_content_feature_detection_are_supported_fallbacks() -> None:
    markdown_only = normalize_mineru_archive(archive({"unknown/output.md": b"Fallback body"}))
    feature_detected = normalize_mineru_archive(
        archive(
            {
                "unknown/result.json": content_list(
                    [
                        {
                            "type": "text",
                            "text": "Detected body",
                            "page_idx": 0,
                            "bbox": [1, 2, 3, 4],
                        }
                    ]
                )
            }
        )
    )

    assert markdown_only.markdown == "Fallback body"
    assert markdown_only.quality_level == "degraded"
    assert markdown_only.blocks[0].raw_locator == {"artifactPath": "unknown/output.md"}
    assert feature_detected.markdown == "Detected body"
    assert feature_detected.blocks[0].raw_locator == {
        "artifactPath": "unknown/result.json",
        "itemIndex": 0,
        "providerPageIndex": 0,
    }


def test_content_list_prefers_its_own_markdown_and_asset_directory() -> None:
    document = normalize_mineru_archive(
        archive(
            {
                "a/readme.md": b"Wrong markdown",
                "a/images/chart.png": b"\x89PNG\r\n\x1a\nwrong",
                "z/document.md": b"Correct markdown",
                "z/document_content_list.json": content_list(
                    [
                        {
                            "type": "image",
                            "img_path": "images/chart.png",
                            "image_caption": ["Chart"],
                            "page_idx": 0,
                            "bbox": [1, 2, 3, 4],
                        }
                    ]
                ),
                "z/images/chart.png": b"\x89PNG\r\n\x1a\ncorrect",
            }
        )
    )

    assert document.markdown == "Correct markdown"
    assert document.assets[0].content.endswith(b"correct")


@pytest.mark.parametrize(
    ("payload", "expected_code"),
    [
        (b"not-a-zip", "PARSER_ARCHIVE_INVALID"),
        (archive({}), "PARSER_OUTPUT_EMPTY"),
        (archive({"unknown.bin": b"opaque"}), "PARSER_OUTPUT_UNSUPPORTED"),
        (
            archive(
                {
                    "empty.md": b"",
                    "empty_content_list.json": content_list([]),
                }
            ),
            "PARSER_OUTPUT_EMPTY",
        ),
        (
            archive({"known_content_list.json": b"{invalid"}),
            "PARSER_NORMALIZATION_FAILED",
        ),
    ],
)
def test_invalid_empty_and_unsupported_archives_have_stable_errors(
    payload: bytes,
    expected_code: str,
) -> None:
    with pytest.raises(MinerUNormalizationError) as captured:
        normalize_mineru_archive(payload)

    assert captured.value.code == expected_code


def test_unsafe_archive_path_is_rejected() -> None:
    with pytest.raises(MinerUNormalizationError) as captured:
        normalize_mineru_archive(archive({"../escape.md": b"unsafe"}))

    assert captured.value.code == "PARSER_ARCHIVE_UNSAFE"
