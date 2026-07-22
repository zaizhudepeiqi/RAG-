import json
from io import BytesIO
from pathlib import Path

import httpx
import pytest
import respx
from app.infrastructure.parsers.mineru_precision import (
    MinerUError,
    MinerUPrecisionAdapter,
    MinerUSubmitRequest,
)
from pydantic import SecretStr

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "mineru"


def fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def adapter() -> MinerUPrecisionAdapter:
    return MinerUPrecisionAdapter(
        base_url="https://mineru.example.com",
        credential=SecretStr("secret-token"),
        resolver=lambda _host: ("8.8.8.8",),
        sleeper=lambda _delay: None,
        jitter=lambda: 0.0,
    )


def request() -> MinerUSubmitRequest:
    return MinerUSubmitRequest(
        file_name="document.pdf",
        data_id="version-fixture-001",
        model_version="pipeline",
        language="ch",
        ocr_enabled=False,
        table_enabled=True,
        formula_enabled=True,
        page_ranges="1-2",
        extra_formats=("docx",),
    )


@respx.mock
def test_signed_upload_put_and_poll_use_official_batch_shapes() -> None:
    submit_route = respx.post("https://mineru.example.com/api/v4/file-urls/batch").mock(
        return_value=httpx.Response(200, json=fixture("signed_upload.json"))
    )
    upload_route = respx.put(
        "https://upload.example.com/api-upload/redacted?signature=fixture"
    ).mock(return_value=httpx.Response(200))
    poll_route = respx.get(
        "https://mineru.example.com/api/v4/extract-results/batch/batch-fixture-001"
    ).mock(return_value=httpx.Response(200, json=fixture("batch_running.json")))
    client = adapter()

    submitted = client.request_upload(request())
    client.upload(submitted.upload_url, BytesIO(b"%PDF fixture"))
    polled = client.poll(submitted.batch_id, request().data_id)

    assert submitted.batch_id == "batch-fixture-001"
    assert submitted.data_id == "version-fixture-001"
    assert polled.state == "running"
    assert polled.progress_current == 1
    assert polled.progress_total == 2
    assert submit_route.calls.last.request.headers["Authorization"] == "Bearer secret-token"
    submitted_body = json.loads(submit_route.calls.last.request.content)
    assert submitted_body["files"] == [
        {
            "name": "document.pdf",
            "data_id": "version-fixture-001",
            "is_ocr": False,
            "page_ranges": "1-2",
        }
    ]
    assert "Authorization" not in upload_route.calls.last.request.headers
    assert poll_route.called


@respx.mock
def test_done_failed_and_retry_mapping() -> None:
    route = respx.get("https://mineru.example.com/api/v4/extract-results/batch/batch-fixture-001")
    route.side_effect = [
        httpx.Response(500),
        httpx.Response(429),
        httpx.Response(200, json=fixture("batch_done.json")),
        httpx.Response(200, json=fixture("batch_failed.json")),
    ]
    client = adapter()

    done = client.poll("batch-fixture-001", "version-fixture-001")
    failed = client.poll("batch-fixture-001", "version-fixture-001")

    assert route.call_count == 4
    assert done.state == "done"
    assert done.full_zip_url == "https://download.example.com/result.zip"
    assert failed.state == "failed"
    assert failed.error_message == "Unsupported file format"


@respx.mock
def test_pending_and_converting_states_are_preserved_and_4xx_is_not_retried() -> None:
    poll_route = respx.get(
        "https://mineru.example.com/api/v4/extract-results/batch/batch-fixture-001"
    )
    pending = fixture("batch_running.json")
    converting = fixture("batch_running.json")
    pending["data"]["extract_result"][1]["state"] = "pending"  # type: ignore[index]
    converting["data"]["extract_result"][1]["state"] = "converting"  # type: ignore[index]
    poll_route.side_effect = [
        httpx.Response(200, json=pending),
        httpx.Response(200, json=converting),
    ]
    submit_route = respx.post("https://mineru.example.com/api/v4/file-urls/batch").mock(
        return_value=httpx.Response(400)
    )
    client = adapter()

    assert client.poll("batch-fixture-001", "version-fixture-001").state == "pending"
    assert client.poll("batch-fixture-001", "version-fixture-001").state == "converting"
    with pytest.raises(MinerUError) as captured:
        client.request_upload(request())

    assert captured.value.retryable is False
    assert submit_route.call_count == 1


def test_result_download_rejects_private_or_http_urls() -> None:
    with pytest.raises(MinerUError) as captured:
        adapter().download_result("http://127.0.0.1/result.zip")

    assert captured.value.code == "MINERU_RESULT_URL_FORBIDDEN"
