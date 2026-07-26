import json
import math
from collections.abc import Sequence
from typing import Literal

import pytest
import respx
from app.infrastructure.model_providers.openai_compatible import (
    OpenAICompatibleAdapter,
    QwenAdapter,
)
from app.infrastructure.model_providers.registry import OPENAI_DESCRIPTOR, QWEN_DESCRIPTOR
from app.modules.models.adapters import (
    EmbeddingRequest,
    EmbeddingResult,
    ModelProviderError,
)
from app.modules.models.embeddings import validate_embedding_result
from httpx import Request, Response
from pydantic import SecretStr


def request(*, purpose: Literal["document", "query"] = "document") -> EmbeddingRequest:
    return EmbeddingRequest(
        base_url="https://8.8.8.8/v1",
        credential=SecretStr("test-only-key"),
        model_name="embedding-model",
        texts=("first", "second"),
        purpose=purpose,
        params={"dimensions": 2, "model": "override", "input": "override"},
    )


@respx.mock
def test_openai_batch_embedding_restores_index_order_and_protects_core_fields() -> None:
    captured: dict[str, object] = {}

    def respond(http_request: Request) -> Response:
        captured.update(json.loads(http_request.content))
        return Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.0, 1.0]},
                    {"index": 0, "embedding": [1.0, 0.0]},
                ],
                "usage": {"prompt_tokens": 4},
            },
            headers={"x-request-id": "embed-1"},
        )

    respx.post("https://8.8.8.8/v1/embeddings").mock(side_effect=respond)
    adapter = OpenAICompatibleAdapter(OPENAI_DESCRIPTOR, sleeper=lambda _delay: None)

    result = adapter.embed(request())

    assert result.vectors == ((1.0, 0.0), (0.0, 1.0))
    assert result.usage_input_tokens == 4
    assert result.provider_request_id == "embed-1"
    assert captured["model"] == "embedding-model"
    assert captured["input"] == ["first", "second"]
    assert captured["dimensions"] == 2


@respx.mock
def test_qwen_batch_embedding_uses_provider_specific_shape() -> None:
    captured: dict[str, object] = {}

    def respond(http_request: Request) -> Response:
        captured.update(json.loads(http_request.content))
        return Response(
            200,
            json={
                "output": {
                    "embeddings": [
                        {"text_index": 0, "embedding": [1.0, 0.0]},
                        {"text_index": 1, "embedding": [0.0, 1.0]},
                    ]
                }
            },
        )

    respx.post("https://8.8.8.8/v1/api/v1/services/embeddings/text-embedding/text-embedding").mock(
        side_effect=respond
    )
    adapter = QwenAdapter(QWEN_DESCRIPTOR, sleeper=lambda _delay: None)

    result = adapter.embed(request(purpose="query"))

    assert result.vectors == ((1.0, 0.0), (0.0, 1.0))
    assert captured["input"] == {"texts": ["first", "second"]}
    assert captured["parameters"] == {
        "dimensions": 2,
        "model": "override",
        "input": "override",
    }


@pytest.mark.parametrize(
    "vectors",
    [
        ((1.0, 0.0),),
        ((1.0,), (0.0, 1.0)),
        ((math.nan, 0.0), (0.0, 1.0)),
    ],
)
def test_embedding_validation_rejects_count_dimension_and_non_finite_values(
    vectors: Sequence[Sequence[float]],
) -> None:
    result = EmbeddingResult(tuple(tuple(vector) for vector in vectors))

    with pytest.raises(ModelProviderError) as captured:
        validate_embedding_result(result, expected_count=2, expected_dimension=2)

    assert captured.value.code == "MODEL_RESPONSE_INVALID"
    assert captured.value.retryable is False


def test_embedding_validation_returns_immutable_vectors() -> None:
    vectors = ((1.0, 0.0), (0.0, 1.0))

    assert (
        validate_embedding_result(EmbeddingResult(vectors), expected_count=2, expected_dimension=2)
        == vectors
    )
