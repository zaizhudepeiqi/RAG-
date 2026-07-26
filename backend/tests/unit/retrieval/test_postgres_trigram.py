import pytest
from app.infrastructure.keyword.postgres_trigram import (
    KEYWORD_SCORE_VERSION,
    keyword_score,
    normalize_keyword_query,
)


def test_query_normalization_is_unicode_stable_and_generates_bounded_chinese_ngrams() -> None:
    query = normalize_keyword_query("  \uff32\uff21\uff27\u3000企业知识库检索  ")

    assert query.text == "rag 企业知识库检索"
    assert query.terms[0] == query.text
    assert "rag" in query.terms
    assert "企业知" in query.terms
    assert "库检索" in query.terms
    assert len(query.terms) <= 16
    assert query.short_query_fallback is False


@pytest.mark.parametrize("value", ["企", "知识"])
def test_one_or_two_character_queries_use_explicit_fallback(value: str) -> None:
    query = normalize_keyword_query(value)

    assert query.terms == (value,)
    assert query.short_query_fallback is True


def test_empty_and_oversized_queries_are_rejected() -> None:
    with pytest.raises(ValueError, match="empty"):
        normalize_keyword_query(" \n ")
    with pytest.raises(ValueError, match="maximum"):
        normalize_keyword_query("a" * 513)


def test_keyword_score_is_reproducible_bounded_and_versioned() -> None:
    assert keyword_score(0.5, False, False) == 0.4
    assert keyword_score(0.5, True, False) == 0.55
    assert keyword_score(0.5, True, True) == pytest.approx(0.6)
    assert keyword_score(1.0, True, True) == 1.0
    assert KEYWORD_SCORE_VERSION == "postgres_trigram_v1"


@pytest.mark.parametrize("value", [-0.1, 1.1])
def test_keyword_score_rejects_invalid_similarity(value: float) -> None:
    with pytest.raises(ValueError, match="between"):
        keyword_score(value, False, False)
