import pytest
from app.modules.chunking.strategies import PageChunkStrategy
from factories import make_context, make_unit


def test_page_strategy_does_not_cross_ordinary_page_boundaries() -> None:
    units = (
        make_unit("page one", index=0, page_numbers=(1,)),
        make_unit("page two", index=1, page_numbers=(2,)),
    )

    chunks = PageChunkStrategy(30, 5).chunk(make_context("page-v1"), units).chunks

    assert [chunk.page_numbers for chunk in chunks] == [(1,), (2,)]
    assert [chunk.text for chunk in chunks] == ["page one", "page two"]


def test_page_strategy_preserves_explicit_cross_page_range_and_metadata() -> None:
    cross_page = make_unit("continued paragraph", page_numbers=(3, 4))

    chunk = PageChunkStrategy(30, 0).chunk(make_context(), (cross_page,)).chunks[0]

    assert chunk.page_numbers == (3, 4)
    assert chunk.source_block_ids == cross_page.source_block_ids
    assert chunk.asset_ids == cross_page.asset_ids
    assert chunk.bounding_boxes == cross_page.bounding_boxes


def test_page_strategy_rejects_any_unit_without_page_metadata() -> None:
    units = (make_unit("page one"), make_unit("unknown", index=1, page_numbers=()))

    with pytest.raises(ValueError, match="requires page numbers"):
        PageChunkStrategy(30, 0).chunk(make_context(), units)


def test_page_overlap_never_leaks_into_the_next_page() -> None:
    units = (
        make_unit("AAAA。BBBB。", index=0, page_numbers=(1,)),
        make_unit("CCCC。", index=1, page_numbers=(2,)),
    )

    chunks = PageChunkStrategy(5, 3).chunk(make_context(), units).chunks

    page_two = next(chunk for chunk in chunks if chunk.page_numbers == (2,))
    assert page_two.text == "CCCC。"
    assert "BBBB" not in page_two.text
