import random
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal

import httpx
from pydantic import SecretStr

from app.core.network_security import AddressResolver, validate_outbound_base_url
from app.modules.models.adapters import ModelProviderError

Sleeper = Callable[[float], None]
Jitter = Callable[[], float]


@dataclass(frozen=True)
class ProviderJsonResponse:
    payload: Mapping[str, object]
    provider_request_id: str | None
    latency_ms: int


class ProviderHttpTransport:
    def __init__(
        self,
        *,
        app_env: Literal["development", "test", "production"] = "test",
        allow_local_http: bool = False,
        resolver: AddressResolver | None = None,
        sleeper: Sleeper = time.sleep,
        jitter: Jitter = random.random,
        client: httpx.Client | None = None,
    ) -> None:
        self._app_env = app_env
        self._allow_local_http = allow_local_http
        self._resolver = resolver
        self._sleeper = sleeper
        self._jitter = jitter
        self._client = client

    def request_json(
        self,
        method: str,
        *,
        base_url: str,
        path: str,
        credential: SecretStr,
        json_body: Mapping[str, object] | None = None,
    ) -> ProviderJsonResponse:
        url = self._url(base_url, path)
        headers = {
            "Authorization": f"Bearer {credential.get_secret_value()}",
            "Accept": "application/json",
        }
        if json_body is not None:
            headers["Content-Type"] = "application/json"

        for attempt in range(3):
            self._validate_base_url(base_url)
            started = time.perf_counter()
            try:
                response = self._http_client().request(
                    method,
                    url,
                    headers=headers,
                    json=dict(json_body) if json_body is not None else None,
                )
            except httpx.TimeoutException as error:
                failure = ModelProviderError("MODEL_TIMEOUT", retryable=True)
                if attempt < 2:
                    self._backoff(attempt)
                    continue
                raise failure from error
            except httpx.NetworkError as error:
                failure = ModelProviderError("MODEL_PROVIDER_ERROR", retryable=True)
                if attempt < 2:
                    self._backoff(attempt)
                    continue
                raise failure from error

            latency_ms = max(0, round((time.perf_counter() - started) * 1000))
            status_failure = self._status_error(response.status_code)
            if status_failure is not None:
                if status_failure.retryable and attempt < 2:
                    self._backoff(attempt)
                    continue
                raise status_failure
            try:
                payload = response.json()
            except ValueError as error:
                raise ModelProviderError("MODEL_RESPONSE_INVALID", retryable=False) from error
            if not isinstance(payload, dict):
                raise ModelProviderError("MODEL_RESPONSE_INVALID", retryable=False)
            return ProviderJsonResponse(
                payload=payload,
                provider_request_id=response.headers.get("x-request-id"),
                latency_ms=latency_ms,
            )

        raise AssertionError("provider request retry loop exhausted")

    def _http_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=60.0, follow_redirects=False)
        return self._client

    def _validate_base_url(self, base_url: str) -> None:
        if self._resolver is None:
            validate_outbound_base_url(
                base_url,
                app_env=self._app_env,
                allow_local_http=self._allow_local_http,
            )
        else:
            validate_outbound_base_url(
                base_url,
                app_env=self._app_env,
                allow_local_http=self._allow_local_http,
                resolver=self._resolver,
            )

    def _backoff(self, attempt: int) -> None:
        self._sleeper(float(2**attempt) + self._jitter())

    @staticmethod
    def _url(base_url: str, path: str) -> str:
        return f"{base_url.rstrip('/')}/{path.lstrip('/')}"

    @staticmethod
    def _status_error(status_code: int) -> ModelProviderError | None:
        if 200 <= status_code < 300:
            return None
        if status_code in {401, 403}:
            return ModelProviderError("MODEL_AUTH_FAILED", retryable=False)
        if status_code == 404:
            return ModelProviderError("MODEL_NOT_FOUND", retryable=False)
        if status_code in {400, 409, 422}:
            return ModelProviderError("MODEL_BAD_REQUEST", retryable=False)
        if status_code == 429:
            return ModelProviderError("MODEL_RATE_LIMITED", retryable=True)
        if status_code >= 500:
            return ModelProviderError("MODEL_PROVIDER_ERROR", retryable=True)
        return ModelProviderError("MODEL_PROVIDER_ERROR", retryable=False)
