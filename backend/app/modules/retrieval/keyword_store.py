from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session


@dataclass(frozen=True)
class KeywordHit:
    chunk_id: UUID
    parsed_source_version_id: UUID
    chunk_kind: str
    parent_chunk_id: UUID | None
    document: str
    raw_similarity: float
    phrase_match: bool
    heading_match: bool
    keyword_score: float
    keyword_score_version: str
    short_query_fallback: bool


class KeywordStoreAdapter(Protocol):
    def query(
        self,
        session: Session,
        *,
        generation_id: UUID,
        query: str,
        top_k: int,
        score_threshold: float,
        candidate_limit: int,
    ) -> tuple[KeywordHit, ...]: ...
