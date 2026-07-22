from collections.abc import Iterator
from pathlib import Path

import pytest
from app.bootstrap.application import create_app
from app.core.config import Settings
from redis import Redis
from sqlalchemy import Engine, text
from starlette.testclient import TestClient

pytestmark = pytest.mark.integration

INITIAL_CREDENTIAL = "Initial-Parse-Admin-Password-01!"
CURRENT_CREDENTIAL = "Current-Parse-Admin-Password-02!"


@pytest.fixture
def parse_client(
    tmp_path: Path,
    migrated_database_url: str,
    database_engine: Engine,
) -> Iterator[tuple[TestClient, Engine]]:
    with database_engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE audit_logs, task_outbox, parsed_source_versions, operations, "
                "data_sources, source_blobs, administrators CASCADE"
            )
        )
    redis_client = Redis.from_url("redis://127.0.0.1:6379/15")
    redis_client.flushdb()
    redis_client.close()
    settings = Settings(
        app_env="test",
        database_url=migrated_database_url,
        redis_url="redis://127.0.0.1:6379/15",
        storage_root=tmp_path / "storage",
        jwt_signing_key="p" * 48,
        credential_encryption_key="Y2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2M=",
        initial_admin_password=INITIAL_CREDENTIAL,
    )
    with TestClient(create_app(settings)) as client:
        logged_in = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": INITIAL_CREDENTIAL},
        )
        changed = client.post(
            "/api/v1/auth/change-password",
            headers={"X-CSRF-Token": logged_in.json()["csrfToken"]},
            json={
                "oldPassword": INITIAL_CREDENTIAL,
                "newPassword": CURRENT_CREDENTIAL,
                "confirmPassword": CURRENT_CREDENTIAL,
            },
        )
        assert changed.status_code == 200
        yield client, database_engine


def csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get("rag_csrf") or ""}


def config() -> dict[str, object]:
    return {
        "parserCode": "mineru_precision_api",
        "modelVersion": "pipeline",
        "language": "ch",
        "ocrEnabled": False,
        "tableEnabled": True,
        "formulaEnabled": True,
        "pageRanges": None,
        "extraFormats": [],
        "forceProviderRefresh": False,
    }


def upload(client: TestClient, name: str, content: bytes, mime_type: str) -> str:
    response = client.post(
        "/api/v1/data-sources/uploads",
        headers=csrf(client),
        files=[("files", (name, content, mime_type))],
        data={"options": "{}"},
    )
    assert response.status_code == 200, response.json()
    return response.json()["accepted"][0]["dataSource"]["id"]


def request_parse(
    client: TestClient,
    source_id: str,
    *,
    expected_revision: int = 1,
    reuse_policy: str = "reuse_if_exact",
) -> object:
    return client.post(
        f"/api/v1/data-sources/{source_id}/parse",
        headers=csrf(client),
        json={
            "expectedRevision": expected_revision,
            "reusePolicy": reuse_policy,
            "config": config(),
        },
    )


def test_parse_request_routes_text_reuses_exact_and_force_creates_new_version(
    parse_client: tuple[TestClient, Engine],
) -> None:
    client, engine = parse_client
    source_id = upload(client, "source.txt", b"parse me", "text/plain")

    first = request_parse(client, source_id)
    reused = request_parse(client, source_id)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE parsed_source_versions SET status = 'failed' WHERE version_number = 1")
        )
    retried = request_parse(client, source_id)
    forced = request_parse(client, source_id, reuse_policy="force_new")

    assert first.status_code == 202, first.json()
    first_body = first.json()
    assert first_body["reused"] is False
    assert first_body["parsedSourceVersion"]["parserCode"] == "builtin_text"
    assert first_body["parsedSourceVersion"]["configSnapshot"]["modelVersion"] == "builtin"
    assert reused.status_code == 202
    assert reused.json()["reused"] is True
    assert reused.json()["parsedSourceVersion"]["id"] == first_body["parsedSourceVersion"]["id"]
    assert retried.status_code == 202
    assert retried.json()["parsedSourceVersion"]["versionNumber"] == 2
    assert (
        retried.json()["parsedSourceVersion"]["operationId"]
        != first_body["parsedSourceVersion"]["operationId"]
    )
    assert forced.status_code == 202
    assert forced.json()["parsedSourceVersion"]["versionNumber"] == 3
    assert forced.json()["parsedSourceVersion"]["configSnapshot"]["executionIntent"] == {
        "reusePolicy": "force_new",
        "noCache": True,
    }
    with engine.connect() as connection:
        version_count = connection.scalar(text("SELECT count(*) FROM parsed_source_versions"))
        operation_count = connection.scalar(text("SELECT count(*) FROM operations"))
        outbox_count = connection.scalar(text("SELECT count(*) FROM task_outbox"))
    assert (version_count, operation_count, outbox_count) == (3, 3, 3)


def test_parse_rejects_stale_revision_and_unconfirmed_mineru_cloud(
    parse_client: tuple[TestClient, Engine],
) -> None:
    client, engine = parse_client
    text_id = upload(client, "source.txt", b"parse me", "text/plain")
    pdf_id = upload(client, "source.pdf", b"%PDF-1.7\ncontent", "application/pdf")

    stale = request_parse(client, text_id, expected_revision=2)
    unconfirmed = request_parse(client, pdf_id)

    assert stale.status_code == 409
    assert stale.json()["code"] == "REVISION_CONFLICT"
    assert unconfirmed.status_code == 409
    assert unconfirmed.json()["code"] == "MINERU_CLOUD_CONSENT_REQUIRED"
    with engine.connect() as connection:
        version_count = connection.scalar(text("SELECT count(*) FROM parsed_source_versions"))
    assert version_count == 0
