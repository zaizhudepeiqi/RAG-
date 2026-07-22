from enum import StrEnum
from uuid import UUID


class ModelType(StrEnum):
    LLM = "llm"
    EMBEDDING = "embedding"
    RERANK = "rerank"
    VISION = "vision"


class VerificationStatus(StrEnum):
    UNTESTED = "untested"
    PASSED = "passed"
    FAILED = "failed"
    STALE = "stale"


def provider_credential_aad(provider_id: UUID) -> bytes:
    return f"model-provider:{provider_id}:credential:v1".encode("ascii")


def mask_credential(value: str) -> str:
    if len(value) < 8:
        return "****"
    return f"{value[:4]}...{value[-4:]}"
