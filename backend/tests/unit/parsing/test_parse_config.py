from dataclasses import replace

import pytest
from app.modules.parsing.domain import normalize_parse_config
from app.modules.parsing.settings_domain import DEFAULT_PARSE_CONFIG


def test_builtin_config_removes_mineru_only_fields_and_hashes_stably() -> None:
    first = normalize_parse_config("txt", DEFAULT_PARSE_CONFIG)
    second = normalize_parse_config(
        "txt",
        replace(
            DEFAULT_PARSE_CONFIG,
            language="en",
            ocr_enabled=True,
            page_ranges="1-3",
            extra_formats=("json",),
            force_provider_refresh=True,
        ),
    )

    assert first.snapshot == {
        "parserCode": "builtin_text",
        "parserVersion": "1",
        "normalizerVersion": "1",
        "modelVersion": "builtin",
    }
    assert first.config_hash == second.config_hash


def test_html_forces_mineru_html_and_drops_document_only_options() -> None:
    normalized = normalize_parse_config(
        "html",
        replace(DEFAULT_PARSE_CONFIG, ocr_enabled=True, page_ranges="1-2"),
    )

    assert normalized.snapshot == {
        "parserCode": "mineru_precision_api",
        "parserVersion": "1",
        "normalizerVersion": "1",
        "modelVersion": "MinerU-HTML",
        "extraFormats": [],
        "forceProviderRefresh": False,
    }


def test_mineru_document_config_is_canonical_and_force_new_sets_no_cache() -> None:
    requested = replace(
        DEFAULT_PARSE_CONFIG,
        page_ranges=" 1-3, 5 ",
        extra_formats=("latex", "docx", "latex"),
    )

    normalized = normalize_parse_config("pdf", requested, force_new=True)

    assert normalized.snapshot["pageRanges"] == "1-3,5"
    assert normalized.snapshot["extraFormats"] == ["docx", "latex"]
    assert normalized.snapshot["forceProviderRefresh"] is True
    assert len(normalized.config_hash) == 64


@pytest.mark.parametrize(
    ("extension", "page_ranges", "extra_formats"),
    [("pdf", "0-2", ()), ("pdf", "3-1", ()), ("pdf", None, ("xml",))],
)
def test_invalid_effective_config_is_rejected(
    extension: str,
    page_ranges: str | None,
    extra_formats: tuple[str, ...],
) -> None:
    with pytest.raises(ValueError):
        normalize_parse_config(
            extension,
            replace(
                DEFAULT_PARSE_CONFIG,
                page_ranges=page_ranges,
                extra_formats=extra_formats,
            ),
        )


def test_page_ranges_support_official_relative_end_syntax() -> None:
    normalized = normalize_parse_config(
        "pdf",
        replace(DEFAULT_PARSE_CONFIG, page_ranges="2--2"),
    )

    assert normalized.snapshot["pageRanges"] == "2--2"
