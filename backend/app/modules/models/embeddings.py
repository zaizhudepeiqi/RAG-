import math

from app.modules.models.adapters import EmbeddingResult, ModelProviderError


def validate_embedding_result(
    result: EmbeddingResult,
    *,
    expected_count: int,
    expected_dimension: int,
) -> tuple[tuple[float, ...], ...]:
    if expected_count <= 0 or expected_dimension <= 0:
        raise ValueError("expected embedding count and dimension must be positive")
    if len(result.vectors) != expected_count:
        raise ModelProviderError("MODEL_RESPONSE_INVALID", retryable=False)
    if any(len(vector) != expected_dimension for vector in result.vectors):
        raise ModelProviderError("MODEL_RESPONSE_INVALID", retryable=False)
    if any(not math.isfinite(value) for vector in result.vectors for value in vector):
        raise ModelProviderError("MODEL_RESPONSE_INVALID", retryable=False)
    return result.vectors
