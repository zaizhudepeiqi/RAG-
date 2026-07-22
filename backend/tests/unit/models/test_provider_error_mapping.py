import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from app.infrastructure.model_providers.openai_compatible import OpenAICompatibleAdapter
from app.infrastructure.model_providers.registry import OPENAI_DESCRIPTOR
from app.modules.models.adapters import ModelProviderError, ModelVerificationRequest
from app.modules.models.domain import ModelType
from httpx import Response
from pydantic import SecretStr

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "model_providers"
CHAT_URL = "https://8.8.8.8/v1/chat/completions"


def verification_request() -> ModelVerificationRequest:
    return ModelVerificationRequest(
        base_url="https://8.8.8.8/v1",
        credential=SecretStr("test-only-provider-key"),
        model_name="gpt-4.1-mini",
        model_type=ModelType.LLM,
        default_params={},
    )


def error_body(code: str) -> dict[str, object]:
    return {
        "error": {
            "message": "Provider rejected the test request",
            "type": "invalid_request_error",
            "param": None,
            "code": code,
        }
    }


@pytest.mark.parametrize(
    ("status", "expected_code", "retryable", "attempts"),
    [
        (401, "MODEL_AUTH_FAILED", False, 1),
        (403, "MODEL_AUTH_FAILED", False, 1),
        (404, "MODEL_NOT_FOUND", False, 1),
        (400, "MODEL_BAD_REQUEST", False, 1),
        (422, "MODEL_BAD_REQUEST", False, 1),
        (429, "MODEL_RATE_LIMITED", True, 3),
        (500, "MODEL_PROVIDER_ERROR", True, 3),
        (503, "MODEL_PROVIDER_ERROR", True, 3),
    ],
)
@respx.mock
def test_http_statuses_map_to_stable_errors(
    status: int,
    expected_code: str,
    retryable: bool,
    attempts: int,
) -> None:
    delays: list[float] = []
    route = respx.post(CHAT_URL).mock(
        return_value=Response(status, json=error_body(expected_code.lower()))
    )
    adapter = OpenAICompatibleAdapter(
        OPENAI_DESCRIPTOR,
        sleeper=delays.append,
        jitter=lambda: 0.0,
    )

    with pytest.raises(ModelProviderError) as captured:
        adapter.verify_llm(verification_request())

    assert captured.value.code == expected_code
    assert captured.value.retryable is retryable
    assert route.call_count == attempts
    assert delays == ([1.0, 2.0] if attempts == 3 else [])


@pytest.mark.parametrize(
    ("exception", "expected_code"),
    [
        (httpx.ReadTimeout("provider timed out"), "MODEL_TIMEOUT"),
        (httpx.ConnectError("provider connection failed"), "MODEL_PROVIDER_ERROR"),
    ],
)
@respx.mock
def test_transport_failures_retry_without_real_sleep(
    exception: Exception,
    expected_code: str,
) -> None:
    delays: list[float] = []
    route = respx.post(CHAT_URL).mock(side_effect=exception)
    adapter = OpenAICompatibleAdapter(
        OPENAI_DESCRIPTOR,
        sleeper=delays.append,
        jitter=lambda: 0.0,
    )

    with pytest.raises(ModelProviderError) as captured:
        adapter.verify_llm(verification_request())

    assert captured.value.code == expected_code
    assert captured.value.retryable is True
    assert route.call_count == 3
    assert delays == [1.0, 2.0]


@pytest.mark.parametrize(
    "response",
    [
        Response(200, content=b"not-json", headers={"content-type": "application/json"}),
        Response(
            200,
            json={
                "id": "chatcmpl-invalid-001",
                "object": "chat.completion",
                "created": 1728933352,
                "model": "gpt-4.1-mini-2025-04-14",
                "choices": [],
                "usage": {
                    "prompt_tokens": 8,
                    "completion_tokens": 0,
                    "total_tokens": 8,
                },
            },
        ),
    ],
)
@respx.mock
def test_malformed_json_or_shape_is_not_retried(response: Response) -> None:
    route = respx.post(CHAT_URL).mock(return_value=response)
    adapter = OpenAICompatibleAdapter(OPENAI_DESCRIPTOR, sleeper=lambda _delay: None)

    with pytest.raises(ModelProviderError) as captured:
        adapter.verify_llm(verification_request())

    assert captured.value.code == "MODEL_RESPONSE_INVALID"
    assert captured.value.retryable is False
    assert route.call_count == 1


@respx.mock
def test_retryable_failures_can_recover_on_third_attempt() -> None:
    fixture: dict[str, Any] = json.loads(
        (FIXTURES / "openai_chat_completion_v1.json").read_text(encoding="utf-8")
    )
    delays: list[float] = []
    route = respx.post(CHAT_URL).mock(
        side_effect=[
            Response(500, json=error_body("server_error")),
            Response(429, json=error_body("rate_limit_exceeded")),
            Response(200, json=fixture, headers={"x-request-id": "req-chat-001"}),
        ]
    )
    adapter = OpenAICompatibleAdapter(
        OPENAI_DESCRIPTOR,
        sleeper=delays.append,
        jitter=lambda: 0.0,
    )

    result = adapter.verify_llm(verification_request())

    assert result.output_text == "OK"
    assert result.provider_request_id == "req-chat-001"
    assert result.usage_input_tokens == 8
    assert result.usage_output_tokens == 1
    assert route.call_count == 3
    assert delays == [1.0, 2.0]
