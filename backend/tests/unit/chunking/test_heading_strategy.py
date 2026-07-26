from app.modules.chunking.strategies import HeadingChunkStrategy
from factories import make_context, make_unit


def test_heading_strategy_groups_sections_and_injects_truncated_heading_path() -> None:
    units = (
        make_unit("alpha", index=0, heading_path=("制度", "总则", "范围")),
        make_unit("beta", index=1, heading_path=("制度", "总则", "范围")),
        make_unit("gamma", index=2, heading_path=("制度", "职责")),
    )

    result = HeadingChunkStrategy(2, 30, True).chunk(make_context("heading-v1"), units)

    assert [chunk.heading_path for chunk in result.chunks] == [("制度", "总则"), ("制度", "职责")]
    assert result.chunks[0].text == "制度 > 总则\nalpha\n\nbeta"
    assert result.chunks[1].text == "制度 > 职责\ngamma"
    assert all(chunk.token_count.value <= 30 for chunk in result.chunks)


def test_heading_strategy_recognizes_markdown_headings() -> None:
    units = (
        make_unit("# Policy\nalpha", index=0),
        make_unit("## Scope\nbeta", index=1),
    )

    result = HeadingChunkStrategy(3, 30, True).chunk(make_context(), units)

    assert result.warnings == ()
    assert [chunk.heading_path for chunk in result.chunks] == [
        ("Policy",),
        ("Policy", "Scope"),
    ]
    assert result.chunks[0].text == "Policy\nalpha"
    assert result.chunks[1].text == "Policy > Scope\nbeta"


def test_heading_strategy_falls_back_to_paragraphs_with_warning() -> None:
    result = HeadingChunkStrategy(3, 20, True).chunk(make_context(), (make_unit("alpha\n\nbeta"),))

    assert result.warnings == ("CHUNK_HEADING_FALLBACK",)
    assert result.chunks[0].text == "alpha\n\nbeta"


def test_heading_strategy_keeps_injected_heading_within_hard_limit() -> None:
    result = HeadingChunkStrategy(2, 10, True).chunk(
        make_context(),
        (make_unit("abcdefghijkl", heading_path=("H",)),),
    )

    assert len(result.chunks) == 2
    assert all(chunk.text.startswith("H\n") for chunk in result.chunks)
    assert all(chunk.token_count.value <= 10 for chunk in result.chunks)
