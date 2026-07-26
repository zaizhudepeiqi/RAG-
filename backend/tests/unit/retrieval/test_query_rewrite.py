import pytest
from app.modules.models.adapters import ModelProviderError
from app.modules.retrieval.query_rewrite import (
    QueryRewriteError,
    QueryRewriteService,
)


class FakeRewriteModel:
    def __init__(self, output: str = "") -> None:
        self.output = output
        self.calls: list[tuple[str, int, float]] = []

    def generate(self, prompt: str, *, max_tokens: int, temperature: float) -> str:
        self.calls.append((prompt, max_tokens, temperature))
        return self.output


def test_off_preserves_query_without_calling_model() -> None:
    model = FakeRewriteModel("must not be used")

    result = QueryRewriteService(model).rewrite("  企业政策  ", code="off", params={})

    assert result.queries == ("企业政策",)
    assert result.degraded is False
    assert model.calls == []


@pytest.mark.parametrize("code", ["hyde", "step_back"])
def test_single_rewrite_preserves_original_and_deduplicates(code: str) -> None:
    model = FakeRewriteModel("企业政策")

    result = QueryRewriteService(model).rewrite(
        "企业政策", code=code, params={"rewriteMaxTokens": 128}
    )

    assert result.queries == ("企业政策",)
    assert result.generated_queries == ()
    assert model.calls[0][1:] == (128, 0.0)


def test_multi_query_parses_bounded_lines_and_removes_duplicates() -> None:
    model = FakeRewriteModel("企业制度\n企业流程\n企业制度\n\n企业安全")

    result = QueryRewriteService(model).rewrite(
        "企业政策",
        code="multi_query",
        params={"queryCount": 3, "rewriteMaxTokens": 128},
    )

    assert result.queries == ("企业政策", "企业制度", "企业流程")
    assert result.generated_queries == ("企业制度", "企业流程")


def test_retryable_model_failure_degrades_to_original_query() -> None:
    class FailingModel(FakeRewriteModel):
        def generate(self, prompt: str, *, max_tokens: int, temperature: float) -> str:
            raise ModelProviderError("MODEL_RATE_LIMITED", retryable=True)

    result = QueryRewriteService(FailingModel()).rewrite("企业政策", code="hyde", params={})

    assert result.queries == ("企业政策",)
    assert result.degraded is True
    assert result.warning_code == "QUERY_REWRITE_DEGRADED"


def test_nonretryable_model_failure_is_not_hidden() -> None:
    class FailingModel(FakeRewriteModel):
        def generate(self, prompt: str, *, max_tokens: int, temperature: float) -> str:
            raise ModelProviderError("MODEL_AUTH_FAILED", retryable=False)

    with pytest.raises(QueryRewriteError, match="QUERY_REWRITE_FAILED"):
        QueryRewriteService(FailingModel()).rewrite("企业政策", code="hyde", params={})
