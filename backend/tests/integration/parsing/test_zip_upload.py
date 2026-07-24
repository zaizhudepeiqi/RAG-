import json
from collections.abc import Iterator
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from app.bootstrap.application import create_app
from app.core.config import Settings
from redis import Redis
from sqlalchemy import Engine, text
from starlette.testclient import TestClient

pytestmark = pytest.mark.integration

INITIAL_CREDENTIAL = "Initial-Zip-Admin-Password-01!"
CURRENT_CREDENTIAL = "Current-Zip-Admin-Password-02!"


def zip_bytes(entries: dict[str, bytes]) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return output.getvalue()


@pytest.fixture
def zip_client(
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
    settings = Settings(
        app_env="test",
        database_url=migrated_database_url,
        redis_url="redis://127.0.0.1:6379/15",
        storage_root=tmp_path / "storage",
        jwt_signing_key="j" * 48,
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
        yield client, database_engine, settings.storage_root


def upload_archive(client: TestClient, content: bytes) -> object:
    return client.post(
        "/api/v1/data-sources/uploads",
        headers={"X-CSRF-Token": client.cookies.get("rag_csrf") or ""},
        files=[("files", ("sources.zip", content, "application/zip"))],
        data={"options": json.dumps({})},
    )


def test_zip_upload_creates_only_valid_entries_with_posix_source_paths(
    zip_client: tuple[TestClient, Engine, Path],
) -> None:
    client, engine, _storage_root = zip_client
    response = upload_archive(
        client,
        zip_bytes(
            {
                "docs/readme.txt": b"hello archive",
                "data/value.json": b'{"value": 1}',
                "ignored.exe": b"MZbinary",
            }
        ),
    )

    assert response.status_code == 200, response.json()
    body = response.json()
    assert {item["dataSource"]["sourcePath"] for item in body["accepted"]} == {
        "docs/readme.txt",
        "data/value.json",
    }
    assert body["rejected"] == [
        {
            "fileName": "ignored.exe",
            "code": "SOURCE_TYPE_UNSUPPORTED",
            "message": "文件类型不受支持或与内容不匹配",
        }
    ]
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT source_path, original_file_name, extension "
                "FROM data_sources ORDER BY source_path"
            )
        ).all()
        blob_count = connection.scalar(text("SELECT count(*) FROM source_blobs"))

    assert [tuple(row) for row in rows] == [
        ("data/value.json", "value.json", "json"),
        ("docs/readme.txt", "readme.txt", "txt"),
    ]
    assert blob_count == 2


def test_unsafe_zip_is_rejected_before_any_source_or_blob_is_created(
    zip_client: tuple[TestClient, Engine, Path],
) -> None:
    client, engine, storage_root = zip_client
    response = upload_archive(
        client,
        zip_bytes({"valid.txt": b"valid", "../escape.txt": b"escape"}),
    )

    assert response.status_code == 422
    assert response.json()["details"]["rejected"] == [
        {
            "fileName": "sources.zip",
            "code": "SOURCE_ARCHIVE_UNSAFE",
            "message": "ZIP 文件未通过安全检查",
        }
    ]
    with engine.connect() as connection:
        source_count = connection.scalar(text("SELECT count(*) FROM data_sources"))
        blob_count = connection.scalar(text("SELECT count(*) FROM source_blobs"))

    assert source_count == 0
    assert blob_count == 0
    assert not (storage_root / "blobs").exists()
