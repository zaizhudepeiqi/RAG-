from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Protocol
from uuid import UUID

from app.modules.models.adapters import ModelProviderError
from app.modules.retrieval.fusion import RetrievalCandidate


@dataclass(frozen=True)
class RerankScore:
    candidate_id: UUID
    score: float


class RerankAdapter(Protocol):
    def rerank(
        self,
        query: str,
        candidates: tuple[RetrievalCandidate, ...],
        *,
        model_id: UUID | None,
        params: Mapping[str, object],
    ) -> tuple[RerankScore, ...]: ...


@dataclass(frozen=True)
class RerankResult:
    candidates: tuple[RetrievalCandidate, ...]
    applied: bool
    degraded: bool
    warning_code: str | None


class RerankError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class RerankService:
    def __init__(self, adapters: Mapping[str, RerankAdapter]) -> None:
        self._adapters = adapters

    def apply(
        self,
        query: str,
        candidates: tuple[RetrievalCandidate, ...],
        *,
        code: str,
        model_id: UUID | None,
        params: Mapping[str, object],
    ) -> RerankResult:
        if code == "off":
            return RerankResult(candidates, False, False, None)
        candidate_limit, top_k, score_threshold = _limits(params)
        adapter = self._adapters.get(code)
        if adapter is None or model_id is None:
            raise RerankError("RERANK_CONFIG_INVALID")
        limited = candidates[:candidate_limit]
        try:
            scores = adapter.rerank(
                query,
                limited,
                model_id=model_id,
                params=params,
            )
        except ModelProviderError as error:
            if error.retryable:
                return RerankResult(limited[:top_k], False, True, "RERANK_DEGRADED")
            raise RerankError("RERANK_FAILED") from error
        except (ConnectionError, OSError, TimeoutError):
            return RerankResult(limited[:top_k], False, True, "RERANK_DEGRADED")
        except (RerankError, ValueError) as error:
            raise RerankError("RERANK_FAILED") from error
        except RuntimeError as error:
            raise RerankError("RERANK_FAILED") from error

        indexed = {item.chunk_id: item for item in limited}
        if len(scores) != len(limited):
            raise RerankError("RERANK_FAILED")
        ranked: list[RetrievalCandidate] = []
        seen: set[UUID] = set()
        for item in scores:
            candidate = indexed.get(item.candidate_id)
            if candidate is None or item.candidate_id in seen:
                raise RerankError("RERANK_FAILED")
            if not math.isfinite(item.score) or not 0 <= item.score <= 1:
                raise RerankError("RERANK_FAILED")
            seen.add(item.candidate_id)
            ranked.append(replace(candidate, rerank_score=item.score))
        if seen != set(indexed):
            raise RerankError("RERANK_FAILED")
        ranked.sort(key=lambda item: (-(item.rerank_score or 0), str(item.chunk_id)))
        filtered = [item for item in ranked if (item.rerank_score or 0) >= score_threshold]
        final = tuple(
            replace(item, rerank_rank=rank) for rank, item in enumerate(filtered[:top_k], start=1)
        )
        return RerankResult(final, True, False, None)


def _limits(params: Mapping[str, object]) -> tuple[int, int, float]:
    candidate_limit = _int_param(params.get("candidateLimit"))
    top_k = _int_param(params.get("topK"))
    threshold = params.get("scoreThreshold")
    if candidate_limit is None or not 2 <= candidate_limit <= 100:
        raise RerankError("RERANK_CONFIG_INVALID")
    if top_k is None or not 1 <= top_k <= candidate_limit:
        raise RerankError("RERANK_CONFIG_INVALID")
    if isinstance(threshold, bool) or not isinstance(threshold, int | float):
        raise RerankError("RERANK_CONFIG_INVALID")
    threshold_value = float(threshold)
    if not math.isfinite(threshold_value) or not 0 <= threshold_value <= 1:
        raise RerankError("RERANK_CONFIG_INVALID")
    return candidate_limit, top_k, threshold_value


def _int_param(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value
