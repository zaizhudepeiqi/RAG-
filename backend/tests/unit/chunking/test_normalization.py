from dataclasses import replace
from uuid import uuid4

import pytest
from app.modules.chunking.domain import ChunkDraft, SourceAsset, SourceBlock, TokenCount
from app.modules.chunking.ids import deterministic_chunk_id, link_adjacent_chunks
from app.modules.chunking.normalization import (
    normalize_blocks,
    normalize_text,
    split_paragraphs,
    split_sentences,
)
from app.modules.chunking.token_counter import Cl100kTokenCounter


def test_cl100k_counter_is_versioned_deterministic_and_round_trips() -> None:
    counter = Cl100kTokenCounter()
    text = "企业 RAG 知识库 keeps provenance."

    first = counter.count(text)
    second = counter.count(text)

    assert first == second
    assert first.value > 0
    assert first.counter_code == "tiktoken_cl100k_base"
    assert first.counter_version.startswith("tiktoken-0.12.0:")
    assert first.estimated is True
    assert counter.decode(counter.encode(text)) == text


def test_normalization_preserves_provenance_and_adds_asset_text_only_to_search() -> None:
    version_id = uuid4()
    block_id = uuid4()
    asset_id = uuid4()
    units = normalize_blocks(
        (
            SourceBlock(
                id=block_id,
                parsed_source_version_id=version_id,
                block_type="paragraph",
                order_index=1,
                text_content="\uff21\uff22\uff23\r\n  internal   policy ",
                markdown_content=None,
                heading_level=None,
                heading_path=("制度",),
                page_number=3,
                bounding_box={"x": 1},
                assets=(SourceAsset(asset_id, "流程图", "审批节点"),),
            ),
        )
    )

    assert len(units) == 1
    unit = units[0]
    assert unit.text == "ABC\ninternal policy"
    assert unit.searchable_text == "ABC\ninternal policy\n流程图\n审批节点"
    assert unit.source_block_ids == (block_id,)
    assert unit.asset_ids == (asset_id,)
    assert unit.page_numbers == (3,)
    assert unit.bounding_boxes == ({"x": 1},)


def test_empty_blocks_are_removed_and_versions_cannot_mix() -> None:
    version_id = uuid4()
    empty = SourceBlock(
        id=uuid4(),
        parsed_source_version_id=version_id,
        block_type="paragraph",
        order_index=0,
        text_content=" \n ",
        markdown_content=None,
        heading_level=None,
        heading_path=(),
        page_number=None,
        bounding_box=None,
    )
    assert normalize_blocks((empty,)) == ()
    with pytest.raises(ValueError, match="cannot cross"):
        normalize_blocks(
            (
                empty,
                replace(empty, id=uuid4(), parsed_source_version_id=uuid4()),
            )
        )


def test_paragraph_and_sentence_boundaries_are_stable() -> None:
    text = "第一句。第二句!\n\nSecond paragraph. Next Item."
    assert split_paragraphs(text) == ("第一句。第二句!", "Second paragraph. Next Item.")
    assert split_sentences(text) == ("第一句。", "第二句!", "Second paragraph.", "Next Item.")
    assert normalize_text("A\t  B\n\n\nC") == "A B\n\nC"


def test_chunk_ids_and_adjacent_links_are_deterministic_and_version_scoped() -> None:
    generation_id = uuid4()
    first_version = uuid4()
    second_version = uuid4()
    ids = [
        deterministic_chunk_id(generation_id, first_version, "chunk", 0, "token-v1"),
        deterministic_chunk_id(generation_id, first_version, "chunk", 1, "token-v1"),
        deterministic_chunk_id(generation_id, second_version, "chunk", 0, "token-v1"),
    ]
    assert ids[0] == deterministic_chunk_id(generation_id, first_version, "chunk", 0, "token-v1")
    count = TokenCount(1, "test", "1", True)
    chunks = tuple(
        ChunkDraft(
            id=chunk_id,
            parsed_source_version_id=version_id,
            chunk_kind="chunk",
            order_index=index,
            text=str(index),
            searchable_text=str(index),
            token_count=count,
            source_block_ids=(),
            asset_ids=(),
            heading_path=(),
            page_numbers=(),
            bounding_boxes=(),
        )
        for index, (chunk_id, version_id) in enumerate(
            zip(ids, (first_version, first_version, second_version), strict=True)
        )
    )
    linked = link_adjacent_chunks(chunks)
    assert linked[0].next_chunk_id == ids[1]
    assert linked[1].previous_chunk_id == ids[0]
    assert linked[1].next_chunk_id is None
    assert linked[2].previous_chunk_id is None
