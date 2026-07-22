import json
import math
from pathlib import Path

import pytest
import respx
from app.infrastructure.model_providers.openai_compatible import OpenAICompatibleAdapter
from app.infrastructure.model_providers.registry import OPENAI_DESCRIPTOR
from app.modules.models.adapters import ModelVerificationRequest, VerificationResult
from app.modules.models.domain import ModelType
from app.modules.models.verification import (
    VerificationValidationError,
    validate_verification_result,
)
from httpx import Request, Response
from pydantic import SecretStr

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "model_providers"


@pytest.mark.parametrize(
    ("model_type", "result", "existing_dimension"),
    [
        (ModelType.LLM, VerificationResult(output_text=""), None),
        (ModelType.EMBEDDING, VerificationResult(embedding=()), None),
        (ModelType.EMBEDDING, VerificationResult(embedding=(1.0, math.nan)), None),
        (ModelType.EMBEDDING, VerificationResult(embedding=(1.0, math.inf)), None),
        (ModelType.EMBEDDING, VerificationResult(embedding=(1.0, 2.0)), 3),
        (
            ModelType.RERANK,
            VerificationResult(rerank_indices=(0, 0), rerank_scores=(0.9, 0.1)),
            None,
        ),
        (
            ModelType.RERANK,
            VerificationResult(rerank_indices=(0, 1), rerank_scores=(0.9, math.inf)),
            None,
        ),
        (ModelType.VISION, VerificationResult(output_text="  "), None),
    ],
)
def test_invalid_type_specific_results_are_rejected(
    model_type: ModelType,
    result: VerificationResult,
    existing_dimension: int | None,
) -> None:
    with pytest.raises(VerificationValidationError) as captured:
        validate_verification_result(
            model_type,
            result,
            existing_embedding_dimension=existing_dimension,
        )

    assert captured.value.code == "MODEL_RESPONSE_INVALID"


@pytest.mark.parametrize(
    ("model_type", "result", "expected"),
    [
        (
            ModelType.LLM,
            VerificationResult(
                output_text="OK",
                usage_input_tokens=8,
                usage_output_tokens=1,
            ),
            {
                "modelType": "llm",
                "outputPresent": True,
                "embeddingDimension": None,
                "candidateCount": None,
                "usageInputTokens": 8,
                "usageOutputTokens": 1,
                "providerUsageReported": True,
            },
        ),
        (
            ModelType.EMBEDDING,
            VerificationResult(embedding=(0.1, -0.2, 0.3)),
            {
                "modelType": "embedding",
                "outputPresent": True,
                "embeddingDimension": 3,
                "candidateCount": None,
                "usageInputTokens": None,
                "usageOutputTokens": None,
                "providerUsageReported": False,
            },
        ),
        (
            ModelType.RERANK,
            VerificationResult(rerank_indices=(0, 1), rerank_scores=(0.9, 0.1)),
            {
                "modelType": "rerank",
                "outputPresent": True,
                "embeddingDimension": None,
                "candidateCount": 2,
                "usageInputTokens": None,
                "usageOutputTokens": None,
                "providerUsageReported": False,
            },
        ),
        (
            ModelType.VISION,
            VerificationResult(output_text="A single pixel"),
            {
                "modelType": "vision",
                "outputPresent": True,
                "embeddingDimension": None,
                "candidateCount": None,
                "usageInputTokens": None,
                "usageOutputTokens": None,
                "providerUsageReported": False,
            },
        ),
    ],
)
def test_valid_type_specific_results_produce_only_safe_summary(
    model_type: ModelType,
    result: VerificationResult,
    expected: dict[str, object],
) -> None:
    validated = validate_verification_result(
        model_type,
        result,
        existing_embedding_dimension=None,
    )

    assert validated.response_summary == expected
    assert set(validated.response_summary) == {
        "modelType",
        "outputPresent",
        "embeddingDimension",
        "candidateCount",
        "usageInputTokens",
        "usageOutputTokens",
        "providerUsageReported",
    }


@respx.mock
def test_llm_verification_fixed_prompt_and_limits_cannot_be_overridden() -> None:
    fixture = json.loads((FIXTURES / "openai_chat_completion_v1.json").read_text(encoding="utf-8"))
    captured_body: dict[str, object] = {}

    def respond(request: Request) -> Response:
        captured_body.update(json.loads(request.content))
        return Response(200, json=fixture)

    respx.post("https://8.8.8.8/v1/chat/completions").mock(side_effect=respond)
    adapter = OpenAICompatibleAdapter(OPENAI_DESCRIPTOR, sleeper=lambda _delay: None)

    adapter.verify_llm(
        ModelVerificationRequest(
            base_url="https://8.8.8.8/v1",
            credential=SecretStr("test-only-key"),
            model_name="gpt-4.1-mini",
            model_type=ModelType.LLM,
            default_params={
                "temperature": 1,
                "max_tokens": 999,
                "messages": [{"role": "user", "content": "override"}],
            },
        )
    )

    assert captured_body["temperature"] == 0
    assert captured_body["max_tokens"] == 8
    assert captured_body["messages"] == [{"role": "user", "content": "请只回复 OK"}]
