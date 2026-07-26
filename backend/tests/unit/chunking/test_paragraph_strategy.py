from app.modules.chunking.strategies import ParagraphChunkStrategy
from factories import make_context, make_unit


def test_paragraph_strategy_aggregates_short_paragraphs_and_overlaps_whole_paragraphs() -> None:
    strategy = ParagraphChunkStrategy(
        max_chunk_size=8,
        min_chunk_size=4,
        overlap_paragraphs=1,
    )

    result = strategy.chunk(make_context("paragraph-v1"), (make_unit("aa\n\nbb\n\ncc"),))

    assert [chunk.text for chunk in result.chunks] == ["aa\n\nbb", "bb\n\ncc"]
    assert all(chunk.token_count.value <= 8 for chunk in result.chunks)


def test_paragraph_strategy_hard_splits_an_oversized_paragraph() -> None:
    strategy = ParagraphChunkStrategy(5, 0, 0)

    result = strategy.chunk(make_context(), (make_unit("abcdefghijk"),))

    assert [chunk.text for chunk in result.chunks] == ["abcde", "fghij", "k"]
    assert all(chunk.token_count.value <= 5 for chunk in result.chunks)


def test_paragraph_strategy_does_not_duplicate_original_text_in_searchable_text() -> None:
    unit = make_unit("first\n\nsecond", searchable_text="first\n\nsecond\nOCR caption")

    chunks = ParagraphChunkStrategy(5, 0, 0).chunk(make_context(), (unit,)).chunks

    assert chunks[0].text == "first"
    assert "second" not in chunks[0].searchable_text
    assert chunks[0].searchable_text == "first\n\nOCR caption"
