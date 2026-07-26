from dataclasses import replace
from uuid import uuid4

import pytest
from app.modules.chunking.strategies import TokenChunkStrategy
from app.modules.chunking.token_counter import Cl100kTokenCounter
from factories import make_context, make_unit


def test_token_strategy_prefers_sentence_boundaries_and_applies_overlap() -> None:
    context = make_context("token-v1")
    strategy = TokenChunkStrategy(chunk_size=12, chunk_overlap=5)

    result = strategy.chunk(context, (make_unit("AAAA。BBBB。CCCC。"),))

    assert [chunk.text for chunk in result.chunks] == ["AAAA。\n\nBBBB。", "BBBB。\n\nCCCC。"]
    assert all(chunk.token_count.value <= 12 for chunk in result.chunks)


def test_token_strategy_hard_splits_unicode_without_corruption() -> None:
    context = replace(make_context("token-v1"), counter=Cl100kTokenCounter())
    strategy = TokenChunkStrategy(chunk_size=3, chunk_overlap=1)

    result = strategy.chunk(context, (make_unit("知识库😀检索服务没有句子边界"),))

    assert len(result.chunks) > 1
    assert all(chunk.token_count.value <= 3 for chunk in result.chunks)
    assert all("�" not in chunk.text for chunk in result.chunks)


def test_token_strategy_preserves_provenance_stable_ids_and_links() -> None:
    context = make_context("token-v1")
    unit = make_unit("AAAA。BBBB。", searchable_text="AAAA。BBBB。\n图片 OCR")
    strategy = TokenChunkStrategy(chunk_size=5, chunk_overlap=0)

    first = strategy.chunk(context, (unit,)).chunks
    second = strategy.chunk(context, (unit,)).chunks

    assert [chunk.id for chunk in first] == [chunk.id for chunk in second]
    assert first[0].source_block_ids == unit.source_block_ids
    assert first[0].asset_ids == unit.asset_ids
    assert "图片 OCR" in first[0].searchable_text
    assert first[0].next_chunk_id == first[1].id
    assert first[1].previous_chunk_id == first[0].id


def test_token_strategy_rejects_cross_version_input() -> None:
    wrong_version = replace(make_unit("content"), parsed_source_version_id=uuid4())

    with pytest.raises(ValueError, match="cannot cross"):
        TokenChunkStrategy(10, 0).chunk(make_context(), (wrong_version,))
