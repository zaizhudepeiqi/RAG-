import math
from dataclasses import dataclass

from app.modules.models.adapters import VerificationResult
from app.modules.models.domain import ModelType


class VerificationValidationError(ValueError):
    code = "MODEL_RESPONSE_INVALID"


@dataclass(frozen=True)
class ValidatedVerification:
    response_summary: dict[str, object]
    embedding_dimension: int | None


def validate_verification_result(
    model_type: ModelType,
    result: VerificationResult,
    *,
    existing_embedding_dimension: int | None,
) -> ValidatedVerification:
    embedding_dimension: int | None = None
    candidate_count: int | None = None
    if model_type in {ModelType.LLM, ModelType.VISION}:
        if result.output_text is None or not result.output_text.strip():
            raise VerificationValidationError
    elif model_type is ModelType.EMBEDDING:
        embedding = result.embedding
        if embedding is None or not embedding or not all(math.isfinite(item) for item in embedding):
            raise VerificationValidationError
        embedding_dimension = len(embedding)
        if (
            existing_embedding_dimension is not None
            and existing_embedding_dimension != embedding_dimension
        ):
            raise VerificationValidationError
    elif model_type is ModelType.RERANK:
        indices = result.rerank_indices
        scores = result.rerank_scores
        if (
            indices is None
            or scores is None
            or len(indices) != 2
            or len(scores) != 2
            or set(indices) != {0, 1}
            or not all(math.isfinite(item) for item in scores)
        ):
            raise VerificationValidationError
        candidate_count = len(scores)
    else:
        raise VerificationValidationError

    input_tokens = result.usage_input_tokens
    output_tokens = result.usage_output_tokens
    return ValidatedVerification(
        response_summary={
            "modelType": model_type.value,
            "outputPresent": True,
            "embeddingDimension": embedding_dimension,
            "candidateCount": candidate_count,
            "usageInputTokens": input_tokens,
            "usageOutputTokens": output_tokens,
            "providerUsageReported": input_tokens is not None or output_tokens is not None,
        },
        embedding_dimension=embedding_dimension,
    )
