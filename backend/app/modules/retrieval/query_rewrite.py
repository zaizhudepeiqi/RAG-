from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

from app.modules.models.adapters import ModelProviderError

MAX_REWRITE_TEXT_LENGTH = 8192


class RewriteModelPort(Protocol):
    def generate(self, prompt: str, *, max_tokens: int, temperature: float) -> str: ...


@dataclass(frozen=True)
class QueryRewriteResult:
    original_query: str
    queries: tuple[str, ...]
    generated_queries: tuple[str, ...]
    degraded: bool
    warning_code: str | None


class QueryRewriteError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class QueryRewriteService:
    def __init__(self, model: RewriteModelPort) -> None:
        self._model = model

    def rewrite(
        self,
        query: str,
        *,
        code: str,
        params: dict[str, object],
    ) -> QueryRewriteResult:
        original = " ".join(query.split()).strip()
        if not original:
            raise QueryRewriteError("QUERY_REWRITE_INVALID_QUERY")
        if code == "off":
            return QueryRewriteResult(original, (original,), (), False, None)
        if code not in {"hyde", "multi_query", "step_back"}:
            raise QueryRewriteError("QUERY_REWRITE_CONFIG_INVALID")
        max_tokens = _bounded_int(params, "rewriteMaxTokens", 256, 32, 1024)
        query_count = _bounded_int(params, "queryCount", 3, 2, 5)
        prompt = _prompt(code, original, query_count)
        try:
            raw = self._model.generate(prompt, max_tokens=max_tokens, temperature=0.0)
            generated = _parse_generated(raw, code=code, query_count=query_count)
        except ModelProviderError as error:
            if not error.retryable:
                raise QueryRewriteError("QUERY_REWRITE_FAILED") from error
            return QueryRewriteResult(original, (original,), (), True, "QUERY_REWRITE_DEGRADED")
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise QueryRewriteError("QUERY_REWRITE_FAILED") from error
        unique = _deduplicate((original, *generated))
        if len(unique) == 1:
            return QueryRewriteResult(original, unique, (), False, None)
        return QueryRewriteResult(original, unique, unique[1:], False, None)


def _prompt(code: str, query: str, query_count: int) -> str:
    if code == "hyde":
        return f"请为以下问题生成一段用于检索的假设性文档, 只输出正文:\n{query}"
    if code == "step_back":
        return f"请将以下问题改写为更抽象的通用问题, 只输出一个问题:\n{query}"
    return f"请为以下问题生成 {query_count} 个不同的检索问题, 每行一个, 不要编号:\n{query}"


def _parse_generated(raw: str, *, code: str, query_count: int) -> tuple[str, ...]:
    if not isinstance(raw, str) or not raw.strip() or len(raw) > MAX_REWRITE_TEXT_LENGTH:
        raise ValueError("rewrite output is empty or too long")
    values: tuple[str, ...]
    if code in {"hyde", "step_back"}:
        values = (raw.strip(),)
    else:
        decoded: object = raw
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            pass
        if isinstance(decoded, list):
            values = tuple(item for item in decoded if isinstance(item, str))
        else:
            values = tuple(line.strip() for line in raw.splitlines() if line.strip())
        values = values[:query_count]
    cleaned = tuple(" ".join(value.split()) for value in values if value.strip())
    if not cleaned:
        raise ValueError("rewrite output contains no usable query")
    return cleaned


def _deduplicate(values: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.casefold()
        if key not in seen:
            seen.add(key)
            result.append(value)
    return tuple(result)


def _bounded_int(
    params: dict[str, object], key: str, default: int, minimum: int, maximum: int
) -> int:
    value = params.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise QueryRewriteError("QUERY_REWRITE_CONFIG_INVALID")
    return value
