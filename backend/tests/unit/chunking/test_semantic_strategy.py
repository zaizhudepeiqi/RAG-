from collections.abc import Sequence

import pytest
from app.modules.chunking.strategies import SemanticChunkStrategy
from factories import make_context, make_unit


class StaticEmbeddings:
    def __init__(self, vectors: Sequence[Sequence[float]]) -> None:
        self.vectors = vectors
        self.requests: list[tuple[str, ...]] = []

    def embed_documents(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        self.requests.append(tuple(texts))
        return self.vectors


def test_semantic_strategy_splits_below_threshold_and_keeps_threshold_boundary() -> None:
    embeddings = StaticEmbeddings(((1.0, 0.0), (0.75, 0.6614378), (0.0, 1.0)))
    strategy = SemanticChunkStrategy(1, 20, 0.75, 2, embeddings)

    chunks = strategy.chunk(make_context("semantic-v1"), (make_unit("AAAA。BBBB。CCCC。"),)).chunks

    assert [chunk.text for chunk in chunks] == ["AAAA。\n\nBBBB。", "CCCC。"]
    assert embeddings.requests == [("AAAA。\nBBBB。", "BBBB。\nCCCC。", "CCCC。")]


def test_semantic_strategy_merges_too_small_groups_forward() -> None:
    embeddings = StaticEmbeddings(((1.0, 0.0), (0.0, 1.0), (1.0, 0.0), (0.0, 1.0)))
    strategy = SemanticChunkStrategy(10, 13, 0.9, 1, embeddings)

    chunks = strategy.chunk(make_context(), (make_unit("AAAA。BBBB。CCCC。DDDD。"),)).chunks

    assert [chunk.text for chunk in chunks] == ["AAAA。\n\nBBBB。", "CCCC。\n\nDDDD。"]
    assert all(chunk.token_count.value <= 13 for chunk in chunks)


def test_semantic_strategy_hard_splits_oversized_sentences() -> None:
    strategy = SemanticChunkStrategy(1, 4, 0.5, 1, StaticEmbeddings(((1.0,),)))

    chunks = strategy.chunk(make_context(), (make_unit("abcdefghij"),)).chunks

    assert [chunk.text for chunk in chunks] == ["abcd", "efgh", "ij"]


@pytest.mark.parametrize(
    ("vectors", "message"),
    [
        (((1.0,),), "response count"),
        (((1.0,), (1.0, 2.0)), "same non-zero dimension"),
        (((float("nan"),), (1.0,)), "finite values"),
    ],
)
def test_semantic_strategy_rejects_invalid_embedding_responses(
    vectors: Sequence[Sequence[float]], message: str
) -> None:
    strategy = SemanticChunkStrategy(1, 20, 0.5, 1, StaticEmbeddings(vectors))

    with pytest.raises(ValueError, match=message):
        strategy.chunk(make_context(), (make_unit("AAAA。BBBB。"),))
