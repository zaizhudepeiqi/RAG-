import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from app.bootstrap.application import create_app
from app.core.config import Settings
from redis import Redis
from sqlalchemy import Engine, text
from starlette.testclient import TestClient

pytestmark = pytest.mark.integration

INITIAL_CREDENTIAL = "Initial-Admin-Password-01!"
CURRENT_CREDENTIAL = "Current-Admin-Password-02!"


def make_settings(tmp_path: Path, database_url: str) -> Settings:
    return Settings(
        app_env="test",
        database_url=database_url,
        redis_url="redis://127.0.0.1:6379/15",
        storage_root=tmp_path / "storage",
        jwt_signing_key="j" * 48,
        credential_encryption_key="Y2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2M=",
        initial_admin_password=INITIAL_CREDENTIAL,
    )


@pytest.fixture
def source_client(
    tmp_path: Path,
    migrated_database_url: str,
    database_engine: Engine,
) -> Iterator[tuple[TestClient, Engine, Path]]:
    with database_engine.begin() as connection:
        connection.execute(
            text("TRUNCATE audit_logs, data_sources, source_blobs, administrators CASCADE")
        )
    redis_client = Redis.from_url("redis://127.0.0.1:6379/15")
    redis_client.flushdb()
    redis_client.close()

    settings = make_settings(tmp_path, migrated_database_url)
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
        yield client, database_engine, settings.storage_root


def csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get("rag_csrf") or ""}


def upload_text(
    client: TestClient,
    *,
    name: str = "example.txt",
    content: bytes = b"hello source",
    options: dict[str, object] | None = None,
) -> object:
    return client.post(
        "/api/v1/data-sources/uploads",
        headers=csrf(client),
        files=[("files", (name, content, "text/plain"))],
        data={"options": json.dumps(options or {})},
    )


def test_upload_returns_partial_success_and_never_exposes_storage_key(
    source_client: tuple[TestClient, Engine, Path],
) -> None:
    client, engine, storage_root = source_client

    response = client.post(
        "/api/v1/data-sources/uploads",
        headers=csrf(client),
        files=[
            ("files", ("accepted.txt", b"hello source", "text/plain")),
            ("files", ("rejected.exe", b"MZbinary", "application/octet-stream")),
        ],
        data={"options": "{}"},
    )

    assert response.status_code == 200, response.json()
    body = response.json()
    assert len(body["accepted"]) == 1
    assert body["accepted"][0]["dataSource"]["displayName"] == "accepted.txt"
    assert len(body["accepted"][0]["dataSource"]["sha256Short"]) == 12
    assert body["accepted"][0]["dataSource"]["latestParsedVersion"] is None
    assert body["rejected"] == [
        {
            "fileName": "rejected.exe",
            "code": "SOURCE_TYPE_UNSUPPORTED",
            "message": "文件类型不受支持或与内容不匹配",
        }
    ]
    assert "storageKey" not in json.dumps(body)
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT storage_key, reference_count FROM source_blobs")
        ).one()
    assert row.reference_count == 1
    assert (storage_root / Path(*row.storage_key.split("/"))).is_file()


def test_all_invalid_files_return_422_and_batch_over_20_returns_413(
    source_client: tuple[TestClient, Engine, Path],
) -> None:
    client, _engine, _storage_root = source_client

    invalid = client.post(
        "/api/v1/data-sources/uploads",
        headers=csrf(client),
        files=[("files", ("fake.pdf", b"not-pdf", "application/pdf"))],
        data={"options": "{}"},
    )
    too_many = client.post(
        "/api/v1/data-sources/uploads",
        headers=csrf(client),
        files=[("files", (f"{index}.txt", b"ok", "text/plain")) for index in range(21)],
        data={"options": "{}"},
    )

    assert invalid.status_code == 422
    assert invalid.json()["code"] == "SOURCE_UPLOAD_REJECTED"
    assert too_many.status_code == 413
    assert too_many.json()["code"] == "SOURCE_UPLOAD_BATCH_TOO_LARGE"


def test_duplicate_reuses_source_by_default_and_alias_increments_blob_reference(
    source_client: tuple[TestClient, Engine, Path],
) -> None:
    client, engine, storage_root = source_client

    first = upload_text(client).json()["accepted"][0]
    reused = upload_text(client).json()["accepted"][0]
    aliased_response = upload_text(
        client,
        name="alias.txt",
        options={"duplicateAction": "create_alias"},
    )

    assert aliased_response.status_code == 200
    aliased = aliased_response.json()["accepted"][0]
    assert reused["dataSource"]["id"] == first["dataSource"]["id"]
    assert reused["duplicateOfDataSourceId"] == first["dataSource"]["id"]
    assert aliased["dataSource"]["id"] != first["dataSource"]["id"]
    assert aliased["duplicateOfDataSourceId"] == first["dataSource"]["id"]
    with engine.connect() as connection:
        source_count = connection.scalar(text("SELECT count(*) FROM data_sources"))
        blob = connection.execute(
            text("SELECT storage_key, reference_count FROM source_blobs")
        ).one()
    assert source_count == 2
    assert blob.reference_count == 2
    assert len(list((storage_root / "blobs").rglob("*"))) == 2  # hash directory + file


def test_list_get_rename_and_original_download(
    source_client: tuple[TestClient, Engine, Path],
) -> None:
    client, _engine, _storage_root = source_client
    created = upload_text(client, content=b"download me").json()["accepted"][0]["dataSource"]
    source_id = created["id"]

    listing = client.get(
        "/api/v1/data-sources",
        params={"extension": "txt", "search": "example", "page": 1, "pageSize": 20},
    )
    detail = client.get(f"/api/v1/data-sources/{source_id}")
    renamed = client.patch(
        f"/api/v1/data-sources/{source_id}",
        headers=csrf(client),
        json={"expectedRevision": 1, "displayName": "Renamed source"},
    )
    stale = client.patch(
        f"/api/v1/data-sources/{source_id}",
        headers=csrf(client),
        json={"expectedRevision": 1, "displayName": "Stale"},
    )
    downloaded = client.get(f"/api/v1/data-sources/{source_id}/original")

    assert listing.status_code == 200
    assert listing.json()["items"] == [created]
    assert detail.status_code == 200
    assert detail.json()["sha256"].startswith(created["sha256Short"])
    assert detail.json()["latestVersions"] == []
    assert detail.json()["references"] == []
    assert renamed.status_code == 200
    assert renamed.json()["displayName"] == "Renamed source"
    assert renamed.json()["revision"] == 2
    assert stale.status_code == 409
    assert stale.json()["code"] == "REVISION_CONFLICT"
    assert downloaded.status_code == 200
    assert downloaded.content == b"download me"
    assert downloaded.headers["content-type"].startswith("text/plain")
    assert downloaded.headers["x-content-type-options"] == "nosniff"
    assert "attachment" in downloaded.headers["content-disposition"]


def test_upload_requires_csrf_and_source_reads_require_authentication(
    source_client: tuple[TestClient, Engine, Path],
) -> None:
    client, _engine, _storage_root = source_client

    missing_csrf = client.post(
        "/api/v1/data-sources/uploads",
        files=[("files", ("example.txt", b"hello", "text/plain"))],
        data={"options": "{}"},
    )
    client.cookies.clear()
    unauthenticated = client.get("/api/v1/data-sources")

    assert missing_csrf.status_code == 403
    assert unauthenticated.status_code == 401
