from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import Select, func, literal, or_, select
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.infrastructure.database.models.knowledge_bases import ChunkModel
from app.modules.retrieval.keyword_store import KeywordHit

KEYWORD_SCORE_VERSION = "postgres_trigram_v1"
MAX_QUERY_LENGTH = 512
MAX_QUERY_TERMS = 16
PHRASE_WEIGHT = 0.15
HEADING_WEIGHT = 0.05
SIMILARITY_WEIGHT = 0.80
TERM_BOUNDARY = re.compile(r"[^\w\u4e00-\u9fff]+", re.UNICODE)
CHINESE_RUN = re.compile(r"[\u4e00-\u9fff]{3,}")


@dataclass(frozen=True)
class NormalizedKeywordQuery:
    text: str
    terms: tuple[str, ...]
    short_query_fallback: bool


class PostgreSQLTrigramKeywordStoreAdapter:
    def query(
        self,
        session: Session,
        *,
        generation_id: UUID,
        query: str,
        top_k: int,
        score_threshold: float,
        candidate_limit: int,
    ) -> tuple[KeywordHit, ...]:
        _validate_limits(top_k, score_threshold, candidate_limit)
        normalized = normalize_keyword_query(query)
        statement = build_candidate_statement(
            generation_id,
            normalized,
            candidate_limit=candidate_limit,
        )
        candidates = tuple(
            _hit_from_row(row, normalized.short_query_fallback)
            for row in session.execute(statement).mappings()
        )
        filtered = (hit for hit in candidates if hit.keyword_score >= score_threshold)
        ordered = sorted(filtered, key=lambda hit: (-hit.keyword_score, str(hit.chunk_id)))
        return tuple(ordered[:top_k])


def normalize_keyword_query(value: str) -> NormalizedKeywordQuery:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = " ".join(normalized.split()).strip()
    if not normalized:
        raise ValueError("keyword query cannot be empty")
    if len(normalized) > MAX_QUERY_LENGTH:
        raise ValueError("keyword query exceeds maximum length")
    short_fallback = len(normalized.replace(" ", "")) <= 2
    if short_fallback:
        return NormalizedKeywordQuery(normalized, (normalized,), True)
    terms: list[str] = [normalized]
    terms.extend(term for term in TERM_BOUNDARY.split(normalized) if len(term) >= 3)
    for run in CHINESE_RUN.findall(normalized):
        terms.extend(run[index : index + 3] for index in range(len(run) - 2))
    return NormalizedKeywordQuery(
        normalized,
        tuple(dict.fromkeys(terms))[:MAX_QUERY_TERMS],
        False,
    )


def build_candidate_statement(
    generation_id: UUID,
    query: NormalizedKeywordQuery,
    *,
    candidate_limit: int,
) -> Select[tuple[UUID, UUID, str, UUID | None, str, float, bool, bool]]:
    if candidate_limit <= 0:
        raise ValueError("candidate_limit must be positive")
    searchable = ChunkModel.searchable_text
    folded_searchable = func.lower(searchable)
    heading = func.lower(func.coalesce(func.array_to_string(ChunkModel.heading_path, " "), ""))
    phrase_match = func.strpos(folded_searchable, query.text) > 0
    heading_match = func.strpos(heading, query.text) > 0
    raw_similarity: ColumnElement[float]
    candidate_condition: ColumnElement[bool]
    if query.short_query_fallback:
        raw_similarity = literal(0.0)
        candidate_condition = folded_searchable.contains(query.text)
    else:
        similarities = [func.similarity(searchable, term) for term in query.terms]
        raw_similarity = func.greatest(*similarities)
        candidate_condition = or_(*(searchable.op("%")(term) for term in query.terms))
    return (
        select(
            ChunkModel.id.label("chunk_id"),
            ChunkModel.parsed_source_version_id,
            ChunkModel.chunk_kind,
            ChunkModel.parent_chunk_id,
            ChunkModel.text_content.label("document"),
            raw_similarity.label("raw_similarity"),
            phrase_match.label("phrase_match"),
            heading_match.label("heading_match"),
        )
        .where(
            ChunkModel.index_generation_id == generation_id,
            ChunkModel.chunk_kind.in_(("chunk", "child")),
            candidate_condition,
        )
        .order_by(phrase_match.desc(), raw_similarity.desc(), ChunkModel.id.asc())
        .limit(candidate_limit)
    )


def keyword_score(raw_similarity: float, phrase_match: bool, heading_match: bool) -> float:
    if not 0 <= raw_similarity <= 1:
        raise ValueError("trigram similarity must be between zero and one")
    score = (
        raw_similarity * SIMILARITY_WEIGHT
        + float(phrase_match) * PHRASE_WEIGHT
        + float(heading_match) * HEADING_WEIGHT
    )
    return min(1.0, score)


def _hit_from_row(row: RowMapping, short_query_fallback: bool) -> KeywordHit:
    raw_value = row["raw_similarity"]
    if isinstance(raw_value, bool) or not isinstance(raw_value, int | float):
        raise ValueError("keyword similarity is invalid")
    raw_similarity = float(raw_value)
    phrase_match = bool(row["phrase_match"])
    heading_match = bool(row["heading_match"])
    return KeywordHit(
        chunk_id=_uuid(row["chunk_id"], "chunk id"),
        parsed_source_version_id=_uuid(row["parsed_source_version_id"], "parsed source version id"),
        chunk_kind=str(row["chunk_kind"]),
        parent_chunk_id=_optional_uuid(row["parent_chunk_id"], "parent chunk id"),
        document=str(row["document"]),
        raw_similarity=raw_similarity,
        phrase_match=phrase_match,
        heading_match=heading_match,
        keyword_score=keyword_score(raw_similarity, phrase_match, heading_match),
        keyword_score_version=KEYWORD_SCORE_VERSION,
        short_query_fallback=short_query_fallback,
    )


def _validate_limits(top_k: int, threshold: float, candidate_limit: int) -> None:
    if top_k <= 0 or candidate_limit < top_k:
        raise ValueError("candidate_limit must be at least top_k and both must be positive")
    if not 0 <= threshold <= 1:
        raise ValueError("score_threshold must be between zero and one")


def _uuid(value: object, field: str) -> UUID:
    if not isinstance(value, UUID):
        raise ValueError(f"keyword {field} is invalid")
    return value


def _optional_uuid(value: object, field: str) -> UUID | None:
    if value is None:
        return None
    return _uuid(value, field)
