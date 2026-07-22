import random
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import BinaryIO, Literal, cast
from urllib.parse import urlsplit, urlunsplit

import httpx
from app.core.network_security import (
    AddressResolver,
    OutboundUrlPolicyError,
    validate_outbound_base_url,
)
from pydantic import SecretStr

MinerUState = Literal["waiting-file", "pending", "running", "converting", "done", "failed"]
Sleeper = Callable[[float], None]
Jitter = Callable[[], float]


class MinerUError(Exception):
    def __init__(self, code: str, *, retryable: bool) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class MinerUSubmitRequest:
    file_name: str
    data_id: str
    model_version: str
    language: str
    ocr_enabled: bool
    table_enabled: bool
    formula_enabled: bool
    page_ranges: str | None
    extra_formats: tuple[str, ...]
    force_provider_refresh: bool = False


@dataclass(frozen=True)
class MinerUSignedUpload:
    batch_id: str
    data_id: str
    upload_url: str
    trace_id: str | None


@dataclass(frozen=True)
class MinerUPollResult:
    batch_id: str
    data_id: str
    state: MinerUState
    full_zip_url: str | None
    error_message: str | None
    progress_current: int | None
    progress_total: int | None
    trace_id: str | None


class MinerUPrecisionAdapter:
    def __init__(
        self,
        *,
        base_url: str,
        credential: SecretStr,
        resolver: AddressResolver | None = None,
        sleeper: Sleeper = time.sleep,
        jitter: Jitter = random.random,
        client: httpx.Client | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._credential = credential
        self._resolver = resolver
        self._sleeper = sleeper
        self._jitter = jitter
        self._client = client or httpx.Client(timeout=60.0, follow_redirects=False)

    def request_upload(self, request: MinerUSubmitRequest) -> MinerUSignedUpload:
        file_item: dict[str, object] = {
            "name": request.file_name,
            "data_id": request.data_id,
            "is_ocr": request.ocr_enabled,
        }
        if request.page_ranges is not None:
            file_item["page_ranges"] = request.page_ranges
        body: dict[str, object] = {
            "files": [file_item],
            "model_version": request.model_version,
            "language": request.language,
            "enable_table": request.table_enabled,
            "enable_formula": request.formula_enabled,
            "extra_formats": list(request.extra_formats),
            "no_cache": request.force_provider_refresh,
        }
        payload = self._request_json(
            "POST",
            f"{self._base_url}/api/v4/file-urls/batch",
            json_body=body,
            authorized=True,
            error_code="MINERU_SUBMIT_FAILED",
        )
        data = _envelope_data(payload)
        batch_id = _required_string(data, "batch_id")
        file_urls = data.get("file_urls")
        if (
            not isinstance(file_urls, list)
            or len(file_urls) != 1
            or not isinstance(file_urls[0], str)
        ):
            raise MinerUError("MINERU_RESPONSE_INVALID", retryable=False)
        return MinerUSignedUpload(
            batch_id=batch_id,
            data_id=request.data_id,
            upload_url=file_urls[0],
            trace_id=_optional_string(payload, "trace_id"),
        )

    def upload(self, upload_url: str, source: BinaryIO) -> None:
        self._validate_target_url(upload_url)
        for attempt in range(3):
            source.seek(0)
            try:
                response = self._client.put(upload_url, content=_stream(source))
            except (httpx.TimeoutException, httpx.NetworkError) as error:
                if attempt < 2:
                    self._backoff(attempt)
                    continue
                raise MinerUError("MINERU_UPLOAD_FAILED", retryable=True) from error
            failure = _status_error(response.status_code, "MINERU_UPLOAD_FAILED")
            if failure is None:
                return
            if failure.retryable and attempt < 2:
                self._backoff(attempt)
                continue
            raise failure
        raise AssertionError("upload retry loop exhausted")

    def poll(self, batch_id: str, data_id: str) -> MinerUPollResult:
        payload = self._request_json(
            "GET",
            f"{self._base_url}/api/v4/extract-results/batch/{batch_id}",
            authorized=True,
            error_code="MINERU_POLL_FAILED",
        )
        data = _envelope_data(payload)
        results = data.get("extract_result")
        if not isinstance(results, list):
            raise MinerUError("MINERU_RESPONSE_INVALID", retryable=False)
        matched = next(
            (item for item in results if isinstance(item, dict) and item.get("data_id") == data_id),
            None,
        )
        if matched is None:
            raise MinerUError("MINERU_RESULT_NOT_FOUND", retryable=True)
        state = matched.get("state")
        if state not in {"waiting-file", "pending", "running", "converting", "done", "failed"}:
            raise MinerUError("MINERU_RESPONSE_INVALID", retryable=False)
        progress = matched.get("extract_progress")
        current = progress.get("extracted_pages") if isinstance(progress, dict) else None
        total = progress.get("total_pages") if isinstance(progress, dict) else None
        return MinerUPollResult(
            batch_id=_required_string(data, "batch_id"),
            data_id=data_id,
            state=state,
            full_zip_url=_optional_string(matched, "full_zip_url"),
            error_message=_optional_string(matched, "err_msg"),
            progress_current=current if isinstance(current, int) else None,
            progress_total=total if isinstance(total, int) else None,
            trace_id=_optional_string(payload, "trace_id"),
        )

    def download_result(self, url: str) -> bytes:
        self._validate_target_url(url)
        for attempt in range(3):
            try:
                response = self._client.get(url)
            except (httpx.TimeoutException, httpx.NetworkError) as error:
                if attempt < 2:
                    self._backoff(attempt)
                    continue
                raise MinerUError("MINERU_RESULT_DOWNLOAD_FAILED", retryable=True) from error
            failure = _status_error(response.status_code, "MINERU_RESULT_DOWNLOAD_FAILED")
            if failure is None:
                return response.content
            if failure.retryable and attempt < 2:
                self._backoff(attempt)
                continue
            raise failure
        raise AssertionError("download retry loop exhausted")

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        authorized: bool,
        json_body: Mapping[str, object] | None = None,
        error_code: str,
    ) -> dict[str, object]:
        self._validate_target_url(url)
        headers = {"Accept": "application/json"}
        if authorized:
            headers["Authorization"] = f"Bearer {self._credential.get_secret_value()}"
        for attempt in range(3):
            try:
                response = self._client.request(method, url, headers=headers, json=json_body)
            except (httpx.TimeoutException, httpx.NetworkError) as error:
                if attempt < 2:
                    self._backoff(attempt)
                    continue
                raise MinerUError(error_code, retryable=True) from error
            failure = _status_error(response.status_code, error_code)
            if failure is not None:
                if failure.retryable and attempt < 2:
                    self._backoff(attempt)
                    continue
                raise failure
            try:
                payload = response.json()
            except ValueError as error:
                raise MinerUError("MINERU_RESPONSE_INVALID", retryable=False) from error
            if not isinstance(payload, dict):
                raise MinerUError("MINERU_RESPONSE_INVALID", retryable=False)
            return payload
        raise AssertionError("request retry loop exhausted")

    def _validate_target_url(self, value: str) -> None:
        parsed = urlsplit(value)
        policy_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
        try:
            if self._resolver is None:
                validate_outbound_base_url(
                    policy_url,
                    app_env="test",
                    allow_local_http=False,
                )
            else:
                validate_outbound_base_url(
                    policy_url,
                    app_env="test",
                    allow_local_http=False,
                    resolver=self._resolver,
                )
        except OutboundUrlPolicyError as error:
            raise MinerUError("MINERU_RESULT_URL_FORBIDDEN", retryable=False) from error

    def _backoff(self, attempt: int) -> None:
        self._sleeper(float(2**attempt) + self._jitter())


def _stream(source: BinaryIO) -> Iterator[bytes]:
    while chunk := source.read(1024 * 1024):
        yield chunk


def _envelope_data(payload: Mapping[str, object]) -> Mapping[str, object]:
    code = payload.get("code")
    if code in {"A0202", "A0211"}:
        raise MinerUError("MINERU_AUTH_FAILED", retryable=False)
    if code in {-60018, -60019}:
        raise MinerUError("MINERU_QUOTA_EXCEEDED", retryable=False)
    data = payload.get("data")
    if code != 0 or not isinstance(data, dict):
        raise MinerUError("MINERU_REQUEST_FAILED", retryable=False)
    return cast(Mapping[str, object], data)


def _required_string(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise MinerUError("MINERU_RESPONSE_INVALID", retryable=False)
    return item


def _optional_string(value: Mapping[str, object], key: str) -> str | None:
    item = value.get(key)
    return item if isinstance(item, str) and item else None


def _status_error(status_code: int, default_code: str) -> MinerUError | None:
    if 200 <= status_code < 300:
        return None
    if status_code in {401, 403}:
        return MinerUError("MINERU_AUTH_FAILED", retryable=False)
    if status_code == 429:
        return MinerUError("MINERU_RATE_LIMITED", retryable=True)
    return MinerUError(default_code, retryable=status_code >= 500)
