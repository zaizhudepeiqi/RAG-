import random
import time
from collections.abc import Mapping

from pydantic import SecretStr

from app.infrastructure.model_providers.base import (
    Jitter,
    ProviderHttpTransport,
    ProviderJsonResponse,
    Sleeper,
)
from app.modules.models.adapters import (
    DiscoveredModel,
    DiscoverModelsRequest,
    EmbeddingRequest,
    EmbeddingResult,
    ModelProviderError,
    ModelTypeMismatchError,
    ModelVerificationRequest,
    ProviderConnectionRequest,
    ProviderConnectionResult,
    ProviderDescriptor,
    RerankRequest,
    RerankResult,
    TextGenerationRequest,
    TextGenerationResult,
    VerificationResult,
)
from app.modules.models.domain import ModelType

MINIMAL_TEST_IMAGE = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class OpenAICompatibleAdapter:
    def __init__(
        self,
        descriptor: ProviderDescriptor,
        *,
        sleeper: Sleeper = time.sleep,
        jitter: Jitter = random.random,
        transport: ProviderHttpTransport | None = None,
    ) -> None:
        self.descriptor = descriptor
        self._transport = transport or ProviderHttpTransport(sleeper=sleeper, jitter=jitter)

    def test_provider(self, request: ProviderConnectionRequest) -> ProviderConnectionResult:
        response = self._models_response(request.base_url, request.credential)
        models = self._model_items(response.payload)
        return ProviderConnectionResult(
            model_count=len(models),
            latency_ms=response.latency_ms,
            provider_request_id=response.provider_request_id,
        )

    def discover_models(self, request: DiscoverModelsRequest) -> tuple[DiscoveredModel, ...]:
        response = self._models_response(request.base_url, request.credential)
        discovered = []
        for item in self._model_items(response.payload):
            model_name = item.get("id")
            if not isinstance(model_name, str) or not model_name:
                raise ModelProviderError("MODEL_RESPONSE_INVALID", retryable=False)
            metadata: dict[str, object] = {}
            if isinstance(item.get("owned_by"), str):
                metadata["ownedBy"] = item["owned_by"]
            if isinstance(item.get("created"), int):
                metadata["created"] = item["created"]
            discovered.append(
                DiscoveredModel(
                    model_name=model_name,
                    suggested_types=(),
                    provider_status="available",
                    metadata_summary=metadata,
                )
            )
        return tuple(discovered)

    def verify_llm(self, request: ModelVerificationRequest) -> VerificationResult:
        path = self._path(ModelType.LLM, self.descriptor.llm_path)
        response = self._transport.request_json(
            "POST",
            base_url=request.base_url,
            path=path,
            credential=request.credential,
            json_body={
                **request.default_params,
                "model": request.model_name,
                "messages": [{"role": "user", "content": "请只回复 OK"}],
                "temperature": 0,
                "max_tokens": 8,
            },
        )
        return self._text_result(
            response.payload,
            response.provider_request_id,
            response.latency_ms,
        )

    def verify_embedding(self, request: ModelVerificationRequest) -> VerificationResult:
        path = self._path(ModelType.EMBEDDING, self.descriptor.embedding_path)
        response = self._transport.request_json(
            "POST",
            base_url=request.base_url,
            path=path,
            credential=request.credential,
            json_body={
                **request.default_params,
                "model": request.model_name,
                "input": "RAG knowledge base embedding connection test",
            },
        )
        data = response.payload.get("data")
        if not isinstance(data, list) or not data or not isinstance(data[0], Mapping):
            raise ModelProviderError("MODEL_RESPONSE_INVALID", retryable=False)
        embedding = self._number_tuple(data[0].get("embedding"))
        input_tokens, output_tokens = self._usage(response.payload)
        return VerificationResult(
            embedding=embedding,
            provider_request_id=response.provider_request_id,
            latency_ms=response.latency_ms,
            usage_input_tokens=input_tokens,
            usage_output_tokens=output_tokens,
        )

    def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        if not request.texts or any(not text.strip() for text in request.texts):
            raise ValueError("embedding texts must be non-empty")
        path = self._path(ModelType.EMBEDDING, self.descriptor.embedding_path)
        response = self._transport.request_json(
            "POST",
            base_url=request.base_url,
            path=path,
            credential=request.credential,
            json_body={
                **request.params,
                "model": request.model_name,
                "input": list(request.texts),
            },
        )
        vectors = self._indexed_embeddings(response.payload.get("data"), len(request.texts))
        input_tokens, _ = self._usage(response.payload)
        return EmbeddingResult(
            vectors=vectors,
            provider_request_id=response.provider_request_id,
            latency_ms=response.latency_ms,
            usage_input_tokens=input_tokens,
        )

    def generate_text(self, request: TextGenerationRequest) -> TextGenerationResult:
        if not request.prompt.strip() or request.max_tokens <= 0:
            raise ValueError("generation prompt and max_tokens must be valid")
        path = self._path(ModelType.LLM, self.descriptor.llm_path)
        response = self._transport.request_json(
            "POST",
            base_url=request.base_url,
            path=path,
            credential=request.credential,
            json_body={
                **request.params,
                "model": request.model_name,
                "messages": [{"role": "user", "content": request.prompt}],
                "temperature": request.temperature,
                "max_tokens": request.max_tokens,
            },
        )
        result = self._text_result(
            response.payload,
            response.provider_request_id,
            response.latency_ms,
        )
        if result.output_text is None:
            raise ModelProviderError("MODEL_RESPONSE_INVALID", retryable=False)
        return TextGenerationResult(
            text=result.output_text,
            provider_request_id=result.provider_request_id,
            latency_ms=result.latency_ms,
            usage_input_tokens=result.usage_input_tokens,
            usage_output_tokens=result.usage_output_tokens,
        )

    def rerank(self, request: RerankRequest) -> RerankResult:
        if not request.query.strip() or not request.documents:
            raise ValueError("rerank query and documents must be non-empty")
        path = self._path(ModelType.RERANK, self.descriptor.rerank_path)
        response = self._transport.request_json(
            "POST",
            base_url=request.base_url,
            path=path,
            credential=request.credential,
            json_body={
                **request.params,
                "model": request.model_name,
                "query": request.query,
                "documents": list(request.documents),
            },
        )
        indices, scores = self._rerank_values(response.payload.get("results"))
        return RerankResult(
            indices=indices,
            scores=scores,
            provider_request_id=response.provider_request_id,
            latency_ms=response.latency_ms,
        )

    def verify_rerank(self, request: ModelVerificationRequest) -> VerificationResult:
        path = self._path(ModelType.RERANK, self.descriptor.rerank_path)
        response = self._transport.request_json(
            "POST",
            base_url=request.base_url,
            path=path,
            credential=request.credential,
            json_body={
                **request.default_params,
                "model": request.model_name,
                "query": "企业知识库如何检索文档",
                "documents": ["知识库可以检索文档", "今天的天气晴朗"],
            },
        )
        indices, scores = self._rerank_values(response.payload.get("results"))
        return VerificationResult(
            rerank_indices=indices,
            rerank_scores=scores,
            provider_request_id=response.provider_request_id,
            latency_ms=response.latency_ms,
        )

    @staticmethod
    def _rerank_values(value: object) -> tuple[tuple[int, ...], tuple[float, ...]]:
        if not isinstance(value, list) or not value:
            raise ModelProviderError("MODEL_RESPONSE_INVALID", retryable=False)
        indices = []
        scores = []
        for item in value:
            if not isinstance(item, Mapping):
                raise ModelProviderError("MODEL_RESPONSE_INVALID", retryable=False)
            score = item.get("relevance_score", item.get("score"))
            if isinstance(score, bool) or not isinstance(score, int | float):
                raise ModelProviderError("MODEL_RESPONSE_INVALID", retryable=False)
            index = item.get("index")
            if isinstance(index, bool) or not isinstance(index, int):
                raise ModelProviderError("MODEL_RESPONSE_INVALID", retryable=False)
            indices.append(index)
            scores.append(float(score))
        return tuple(indices), tuple(scores)

    def verify_vision(self, request: ModelVerificationRequest) -> VerificationResult:
        path = self._path(ModelType.VISION, self.descriptor.vision_path)
        response = self._transport.request_json(
            "POST",
            base_url=request.base_url,
            path=path,
            credential=request.credential,
            json_body={
                **request.default_params,
                "model": request.model_name,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "请简短描述图片"},
                            {"type": "image_url", "image_url": {"url": MINIMAL_TEST_IMAGE}},
                        ],
                    }
                ],
                "max_tokens": 8,
            },
        )
        return self._text_result(
            response.payload,
            response.provider_request_id,
            response.latency_ms,
        )

    def _models_response(self, base_url: str, credential: SecretStr) -> ProviderJsonResponse:
        path = self.descriptor.discovery_path
        if path is None:
            raise ModelTypeMismatchError
        return self._transport.request_json(
            "GET",
            base_url=base_url,
            path=path,
            credential=credential,
        )

    def _path(self, model_type: ModelType, path: str | None) -> str:
        if model_type not in self.descriptor.supported_model_types or path is None:
            raise ModelTypeMismatchError
        return path

    @staticmethod
    def _model_items(payload: Mapping[str, object]) -> list[Mapping[str, object]]:
        data = payload.get("data")
        if not isinstance(data, list) or not all(isinstance(item, Mapping) for item in data):
            raise ModelProviderError("MODEL_RESPONSE_INVALID", retryable=False)
        return data

    @classmethod
    def _text_result(
        cls,
        payload: Mapping[str, object],
        request_id: str | None,
        latency_ms: int,
    ) -> VerificationResult:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
            raise ModelProviderError("MODEL_RESPONSE_INVALID", retryable=False)
        message = choices[0].get("message")
        content = message.get("content") if isinstance(message, Mapping) else None
        if not isinstance(content, str) or not content.strip():
            raise ModelProviderError("MODEL_RESPONSE_INVALID", retryable=False)
        input_tokens, output_tokens = cls._usage(payload)
        return VerificationResult(
            output_text=content,
            provider_request_id=request_id,
            latency_ms=latency_ms,
            usage_input_tokens=input_tokens,
            usage_output_tokens=output_tokens,
        )

    @staticmethod
    def _usage(payload: Mapping[str, object]) -> tuple[int | None, int | None]:
        usage = payload.get("usage")
        if not isinstance(usage, Mapping):
            return None, None
        input_tokens = usage.get("prompt_tokens")
        output_tokens = usage.get("completion_tokens")
        normalized_input = (
            input_tokens
            if isinstance(input_tokens, int) and not isinstance(input_tokens, bool)
            else None
        )
        normalized_output = (
            output_tokens
            if isinstance(output_tokens, int) and not isinstance(output_tokens, bool)
            else None
        )
        return normalized_input, normalized_output

    @staticmethod
    def _number_tuple(value: object) -> tuple[float, ...]:
        if not isinstance(value, list) or not value:
            raise ModelProviderError("MODEL_RESPONSE_INVALID", retryable=False)
        numbers = []
        for item in value:
            if isinstance(item, bool) or not isinstance(item, int | float):
                raise ModelProviderError("MODEL_RESPONSE_INVALID", retryable=False)
            numbers.append(float(item))
        return tuple(numbers)

    @classmethod
    def _indexed_embeddings(
        cls, value: object, expected_count: int
    ) -> tuple[tuple[float, ...], ...]:
        if not isinstance(value, list) or len(value) != expected_count:
            raise ModelProviderError("MODEL_RESPONSE_INVALID", retryable=False)
        indexed: dict[int, tuple[float, ...]] = {}
        for fallback_index, item in enumerate(value):
            if not isinstance(item, Mapping):
                raise ModelProviderError("MODEL_RESPONSE_INVALID", retryable=False)
            index = item.get("index", item.get("text_index", fallback_index))
            if isinstance(index, bool) or not isinstance(index, int):
                raise ModelProviderError("MODEL_RESPONSE_INVALID", retryable=False)
            if index < 0 or index >= expected_count or index in indexed:
                raise ModelProviderError("MODEL_RESPONSE_INVALID", retryable=False)
            indexed[index] = cls._number_tuple(item.get("embedding"))
        if len(indexed) != expected_count:
            raise ModelProviderError("MODEL_RESPONSE_INVALID", retryable=False)
        return tuple(indexed[index] for index in range(expected_count))


class QwenAdapter(OpenAICompatibleAdapter):
    def verify_embedding(self, request: ModelVerificationRequest) -> VerificationResult:
        path = self._path(ModelType.EMBEDDING, self.descriptor.embedding_path)
        response = self._transport.request_json(
            "POST",
            base_url=request.base_url,
            path=path,
            credential=request.credential,
            json_body={
                "model": request.model_name,
                "input": {"texts": ["RAG knowledge base embedding connection test"]},
                "parameters": dict(request.default_params),
            },
        )
        output = response.payload.get("output")
        embeddings = output.get("embeddings") if isinstance(output, Mapping) else None
        first = embeddings[0] if isinstance(embeddings, list) and embeddings else None
        embedding = first.get("embedding") if isinstance(first, Mapping) else None
        return VerificationResult(
            embedding=self._number_tuple(embedding),
            provider_request_id=response.provider_request_id,
            latency_ms=response.latency_ms,
        )

    def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        if not request.texts or any(not text.strip() for text in request.texts):
            raise ValueError("embedding texts must be non-empty")
        path = self._path(ModelType.EMBEDDING, self.descriptor.embedding_path)
        response = self._transport.request_json(
            "POST",
            base_url=request.base_url,
            path=path,
            credential=request.credential,
            json_body={
                "model": request.model_name,
                "input": {"texts": list(request.texts)},
                "parameters": dict(request.params),
            },
        )
        output = response.payload.get("output")
        embeddings = output.get("embeddings") if isinstance(output, Mapping) else None
        return EmbeddingResult(
            vectors=self._indexed_embeddings(embeddings, len(request.texts)),
            provider_request_id=response.provider_request_id,
            latency_ms=response.latency_ms,
        )

    def verify_rerank(self, request: ModelVerificationRequest) -> VerificationResult:
        path = self._path(ModelType.RERANK, self.descriptor.rerank_path)
        response = self._transport.request_json(
            "POST",
            base_url=request.base_url,
            path=path,
            credential=request.credential,
            json_body={
                "model": request.model_name,
                "input": {
                    "query": "企业知识库如何检索文档",
                    "documents": ["知识库可以检索文档", "今天的天气晴朗"],
                },
                "parameters": dict(request.default_params),
            },
        )
        output = response.payload.get("output")
        results = output.get("results") if isinstance(output, Mapping) else None
        if not isinstance(results, list) or not results:
            raise ModelProviderError("MODEL_RESPONSE_INVALID", retryable=False)
        indices = []
        scores = []
        for item in results:
            score = item.get("relevance_score") if isinstance(item, Mapping) else None
            if isinstance(score, bool) or not isinstance(score, int | float):
                raise ModelProviderError("MODEL_RESPONSE_INVALID", retryable=False)
            index = item.get("index") if isinstance(item, Mapping) else None
            if isinstance(index, bool) or not isinstance(index, int):
                raise ModelProviderError("MODEL_RESPONSE_INVALID", retryable=False)
            indices.append(index)
            scores.append(float(score))
        return VerificationResult(
            rerank_indices=tuple(indices),
            rerank_scores=tuple(scores),
            provider_request_id=response.provider_request_id,
            latency_ms=response.latency_ms,
        )

    def rerank(self, request: RerankRequest) -> RerankResult:
        if not request.query.strip() or not request.documents:
            raise ValueError("rerank query and documents must be non-empty")
        path = self._path(ModelType.RERANK, self.descriptor.rerank_path)
        response = self._transport.request_json(
            "POST",
            base_url=request.base_url,
            path=path,
            credential=request.credential,
            json_body={
                "model": request.model_name,
                "input": {
                    "query": request.query,
                    "documents": list(request.documents),
                },
                "parameters": dict(request.params),
            },
        )
        output = response.payload.get("output")
        results = output.get("results") if isinstance(output, Mapping) else None
        indices, scores = self._rerank_values(results)
        return RerankResult(
            indices=indices,
            scores=scores,
            provider_request_id=response.provider_request_id,
            latency_ms=response.latency_ms,
        )
