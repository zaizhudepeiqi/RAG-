from dataclasses import replace
from uuid import uuid4

import pytest
from app.modules.chunking.domain import ChunkDraft
from app.modules.chunking.index_structures import (
    ChunkIndexStructure,
    ParentChildIndexStructure,
)
from app.modules.chunking.strategies import ChunkingContext, TokenChunkStrategy
from factories import make_context, make_unit


def _strategy_chunks(*texts: str) -> tuple[ChunkingContext, tuple[ChunkDraft, ...]]:
    context = make_context("structure-v1")
    units = tuple(make_unit(text, index=index) for index, text in enumerate(texts))
    return context, TokenChunkStrategy(5, 0).chunk(context, units).chunks


def test_chunk_structure_uses_the_same_chunks_for_index_and_context() -> None:
    context, chunks = _strategy_chunks("alpha", "beta")

    result = ChunkIndexStructure().assemble(context, chunks)

    assert result.all_chunks == result.indexable_chunks == result.context_chunks
    assert all(chunk.chunk_kind == "chunk" for chunk in result.all_chunks)
    assert result.all_chunks[0].next_chunk_id == result.all_chunks[1].id


def test_parent_child_indexes_only_children_and_keeps_parent_context() -> None:
    context, chunks = _strategy_chunks("aaaa", "bbbb", "cccc", "dddd")

    result = ParentChildIndexStructure(12, 5, 1).assemble(context, chunks)

    assert all(chunk.chunk_kind == "parent" for chunk in result.context_chunks)
    assert all(chunk.chunk_kind == "child" for chunk in result.indexable_chunks)
    assert result.all_chunks == (*result.context_chunks, *result.indexable_chunks)
    assert all(chunk.token_count.value <= 12 for chunk in result.context_chunks)
    assert all(chunk.token_count.value <= 5 for chunk in result.indexable_chunks)
    parent_ids = {chunk.id for chunk in result.context_chunks}
    assert {chunk.parent_chunk_id for chunk in result.indexable_chunks} <= parent_ids


def test_child_overlap_is_deterministic_and_links_never_cross_parent() -> None:
    context, chunks = _strategy_chunks("abcdefghij", "klmnopqrst")
    structure = ParentChildIndexStructure(12, 4, 1)

    first = structure.assemble(context, chunks)
    second = structure.assemble(context, chunks)

    assert [chunk.id for chunk in first.all_chunks] == [chunk.id for chunk in second.all_chunks]
    first_parent_children = [
        chunk
        for chunk in first.indexable_chunks
        if chunk.parent_chunk_id == first.context_chunks[0].id
    ]
    assert all(chunk.token_count.value <= 4 for chunk in first_parent_children)
    assert first_parent_children[0].text[-1] == first_parent_children[1].text[0]
    assert first_parent_children[-1].next_chunk_id is None
    second_parent_first_child = next(
        chunk
        for chunk in first.indexable_chunks
        if chunk.parent_chunk_id == first.context_chunks[1].id
    )
    assert second_parent_first_child.previous_chunk_id is None


def test_parent_assembly_deduplicates_exact_input_and_unions_provenance() -> None:
    context, chunks = _strategy_chunks("alpha", "beta")
    duplicate = replace(chunks[0], id=uuid4(), order_index=99)

    result = ParentChildIndexStructure(20, 8, 1).assemble(
        context, (chunks[0], duplicate, chunks[1])
    )

    parent = result.context_chunks[0]
    assert parent.text == "alpha\n\nbeta"
    assert parent.source_block_ids == (
        *chunks[0].source_block_ids,
        *chunks[1].source_block_ids,
    )
    assert parent.asset_ids == (*chunks[0].asset_ids, *chunks[1].asset_ids)


def test_parent_and_children_keep_search_supplements_and_page_union() -> None:
    context = make_context("structure-v1")
    units = (
        make_unit("alpha", index=0, page_numbers=(1,), searchable_text="alpha\nOCR one"),
        make_unit("beta", index=1, page_numbers=(2,), searchable_text="beta\nOCR two"),
    )
    chunks = TokenChunkStrategy(5, 0).chunk(context, units).chunks

    result = ParentChildIndexStructure(20, 5, 1).assemble(context, chunks)

    assert result.context_chunks[0].page_numbers == (1, 2)
    assert "OCR one" in result.context_chunks[0].searchable_text
    assert "OCR two" in result.context_chunks[0].searchable_text
    first_source_id = units[0].source_block_ids[0]
    second_source_id = units[1].source_block_ids[0]
    first_only_child = next(
        child for child in result.indexable_chunks if child.source_block_ids == (first_source_id,)
    )
    assert second_source_id not in first_only_child.source_block_ids
    assert "OCR one" in first_only_child.searchable_text
    assert "OCR two" not in first_only_child.searchable_text


def test_parent_heading_path_is_a_true_common_prefix() -> None:
    context = make_context("structure-v1")
    units = (
        make_unit("alpha", index=0, heading_path=("A", "Shared")),
        make_unit("beta", index=1, heading_path=("B", "Shared")),
    )
    chunks = TokenChunkStrategy(5, 0).chunk(context, units).chunks

    parent = ParentChildIndexStructure(20, 8, 1).assemble(context, chunks).context_chunks[0]

    assert parent.heading_path == ()


def test_index_structure_rejects_cross_version_chunks_and_invalid_sizes() -> None:
    context, chunks = _strategy_chunks("alpha")
    wrong_version = replace(chunks[0], parsed_source_version_id=uuid4())

    with pytest.raises(ValueError, match="cannot cross"):
        ChunkIndexStructure().assemble(context, (wrong_version,))
    with pytest.raises(ValueError, match="at least twice"):
        ParentChildIndexStructure(7, 4, 0)
    with pytest.raises(ValueError, match="smaller than child"):
        ParentChildIndexStructure(8, 4, 4)
