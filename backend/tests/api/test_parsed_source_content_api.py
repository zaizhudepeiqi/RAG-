import hashlib
import json
from collections.abc import Iterator
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from app.bootstrap.application import create_app
from app.core.config import Settings
from app.infrastructure.storage.local import LocalStorageAdapter
from redis import Redis
from sqlalchemy import Engine, text
from starlette.testclient import TestClient

pytestmark = pytest.mark.integration

INITIAL_CREDENTIAL = "Initial-Content-Admin-Password-01!"
CURRENT_CREDENTIAL = "Current-Content-Admin-Password-02!"


def settings(tmp_path: Path, database_url: str) -> Settings:
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
def content_client(
    tmp_path: Path,
    migrated_database_url: str,
    database_engine: Engine,
) -> Iterator[tuple[TestClient, dict[str, UUID], Path]]:
    with database_engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE parsed_block_assets, parsed_assets, parsed_artifacts, "
                "parsed_blocks, parsed_source_versions, data_sources, source_blobs, "
                "administrators CASCADE"
            )
        )
    redis_client = Redis.from_url("redis://127.0.0.1:6379/15")
    redis_client.flushdb()
    redis_client.close()

    app_settings = settings(tmp_path, migrated_database_url)
    ids = seed_content(database_engine, app_settings.storage_root)
    with TestClient(create_app(app_settings)) as client:
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
        yield client, ids, app_settings.storage_root


def seed_content(engine: Engine, storage_root: Path) -> dict[str, UUID]:
    storage = LocalStorageAdapter(storage_root)
    original = storage.store_blob(BytesIO(b"%PDF fixture"), max_bytes=1024)
    markdown = storage.store_blob(BytesIO(b"# Contract\n\nBody\n"), max_bytes=1024)
    asset = storage.store_blob(BytesIO(b"\x89PNG\r\n\x1a\nasset"), max_bytes=1024)
    raw = storage.store_blob(BytesIO(b"PK fixture"), max_bytes=1024)
    ids = {
        "blob": uuid4(),
        "source": uuid4(),
        "version": uuid4(),
        "queued_version": uuid4(),
        "block": uuid4(),
        "asset": uuid4(),
        "markdown_artifact": uuid4(),
        "raw_artifact": uuid4(),
    }
    config = json.dumps({"parserCode": "mineru_precision_api", "modelVersion": "pipeline"})
    flags = json.dumps(
        {
            "hasText": True,
            "hasPages": True,
            "hasHeadings": True,
            "hasBoundingBoxes": False,
            "hasAssets": True,
            "hasTables": False,
            "hasFormulas": False,
        }
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO source_blobs (
                    id, sha256, size_bytes, storage_key, mime_type, reference_count
                ) VALUES (:id, :sha256, :size_bytes, :storage_key, 'application/pdf', 1)
                """
            ),
            {
                "id": ids["blob"],
                "sha256": original.sha256,
                "size_bytes": original.size_bytes,
                "storage_key": original.storage_key,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO data_sources (
                    id, source_blob_id, display_name, source_path, original_file_name,
                    extension, mime_type, size_bytes, sha256, origin_type, origin_ref
                ) VALUES (
                    :id, :blob_id, 'Contract', 'contract.pdf', 'contract.pdf',
                    'pdf', 'application/pdf', :size_bytes, :sha256,
                    'admin_upload', '{}'::jsonb
                )
                """
            ),
            {
                "id": ids["source"],
                "blob_id": ids["blob"],
                "size_bytes": original.size_bytes,
                "sha256": original.sha256,
            },
        )
        for version_id, version_number, status, quality in (
            (ids["version"], 1, "degraded", "degraded"),
            (ids["queued_version"], 2, "queued", None),
        ):
            connection.execute(
                text(
                    """
                    INSERT INTO parsed_source_versions (
                        id, data_source_id, version_number, parser_code, parser_version,
                        normalizer_version, config_snapshot, config_hash, source_sha256,
                        status, quality_level, provider_batch_id, provider_task_id,
                        provider_data_id, provider_trace_id, raw_result_storage_key,
                        normalized_storage_key, page_count, block_count, asset_count,
                        markdown_char_count, feature_flags, finished_at
                    ) VALUES (
                        :id, :source_id, :version_number, 'mineru_precision_api', '1',
                        '1', CAST(:config AS jsonb), :config_hash, :source_sha256,
                        :status, :quality, 'batch-001', 'task-001', :data_id,
                        'trace-001', :raw_key, :markdown_key, :page_count, :block_count,
                        :asset_count, :markdown_chars, CAST(:flags AS jsonb),
                        CASE WHEN :status IN ('succeeded', 'degraded') THEN now() ELSE NULL END
                    )
                    """
                ),
                {
                    "id": version_id,
                    "source_id": ids["source"],
                    "version_number": version_number,
                    "config": config,
                    "config_hash": hashlib.sha256(config.encode()).hexdigest(),
                    "source_sha256": original.sha256,
                    "status": status,
                    "quality": quality,
                    "data_id": str(version_id),
                    "raw_key": raw.storage_key if status == "degraded" else None,
                    "markdown_key": markdown.storage_key if status == "degraded" else None,
                    "page_count": 1 if status == "degraded" else 0,
                    "block_count": 1 if status == "degraded" else 0,
                    "asset_count": 1 if status == "degraded" else 0,
                    "markdown_chars": len("# Contract\n\nBody\n") if status == "degraded" else 0,
                    "flags": flags
                    if status == "degraded"
                    else json.dumps(
                        {
                            "hasText": False,
                            "hasPages": False,
                            "hasHeadings": False,
                            "hasBoundingBoxes": False,
                            "hasAssets": False,
                            "hasTables": False,
                            "hasFormulas": False,
                        }
                    ),
                },
            )
        connection.execute(
            text(
                """
                INSERT INTO parsed_blocks (
                    id, parsed_source_version_id, block_type, order_index,
                    text_content, markdown_content, heading_level, heading_path,
                    page_number, bounding_box, raw_locator, content_hash
                ) VALUES (
                    :id, :version_id, 'text', 0, 'Body', 'Body', 1,
                    ARRAY['Contract'], 1, NULL,
                    CAST(:raw_locator AS jsonb),
                    :content_hash
                )
                """
            ),
            {
                "id": ids["block"],
                "version_id": ids["version"],
                "content_hash": hashlib.sha256(b"Body").hexdigest(),
                "raw_locator": json.dumps(
                    {
                        "artifactPath": "result_content_list.json",
                        "itemIndex": 0,
                    }
                ),
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO parsed_assets (
                    id, parsed_source_version_id, asset_type, mime_type, page_number,
                    bounding_box, storage_key, sha256, size_bytes, caption, ocr_text,
                    order_index
                ) VALUES (
                    :id, :version_id, 'image', 'image/png', 1, NULL, :storage_key,
                    :sha256, :size_bytes, 'Chart', 'Revenue', 0
                )
                """
            ),
            {
                "id": ids["asset"],
                "version_id": ids["version"],
                "storage_key": asset.storage_key,
                "sha256": asset.sha256,
                "size_bytes": asset.size_bytes,
            },
        )
        connection.execute(
            text(
                "INSERT INTO parsed_block_assets (block_id, asset_id) VALUES (:block_id, :asset_id)"
            ),
            {"block_id": ids["block"], "asset_id": ids["asset"]},
        )
        for artifact_id, artifact_type, name, stored, downloadable in (
            (ids["markdown_artifact"], "markdown", "normalized.md", markdown, True),
            (ids["raw_artifact"], "mineru_full_zip", "mineru-full.zip", raw, False),
        ):
            connection.execute(
                text(
                    """
                    INSERT INTO parsed_artifacts (
                        id, parsed_source_version_id, artifact_type, display_name,
                        storage_key, sha256, size_bytes, is_downloadable
                    ) VALUES (
                        :id, :version_id, :artifact_type, :display_name,
                        :storage_key, :sha256, :size_bytes, :downloadable
                    )
                    """
                ),
                {
                    "id": artifact_id,
                    "version_id": ids["version"],
                    "artifact_type": artifact_type,
                    "display_name": name,
                    "storage_key": stored.storage_key,
                    "sha256": stored.sha256,
                    "size_bytes": stored.size_bytes,
                    "downloadable": downloadable,
                },
            )
    return ids


def test_parsed_content_endpoints_return_traceable_content_without_storage_keys(
    content_client: tuple[TestClient, dict[str, UUID], Path],
) -> None:
    client, ids, storage_root = content_client
    version_id = ids["version"]

    detail = client.get(f"/api/v1/parsed-source-versions/{version_id}")
    markdown = client.get(f"/api/v1/parsed-source-versions/{version_id}/markdown")
    blocks = client.get(
        f"/api/v1/parsed-source-versions/{version_id}/blocks",
        params={"pageNumber": 1, "blockType": "text", "page": 1, "pageSize": 20},
    )
    assets = client.get(
        f"/api/v1/parsed-source-versions/{version_id}/assets",
        params={"page": 1, "pageSize": 20},
    )
    artifacts = client.get(f"/api/v1/parsed-source-versions/{version_id}/artifacts")
    downloaded = client.get(f"/api/v1/parsed-source-versions/{version_id}/assets/{ids['asset']}")

    assert detail.status_code == 200, detail.json()
    assert detail.json()["status"] == "degraded"
    assert detail.json()["selectable"] is True
    assert detail.json()["providerBatchId"] == "batch-001"
    assert detail.json()["providerTaskId"] == "task-001"
    assert markdown.json() == {
        "markdown": "# Contract\n\nBody\n",
        "markdownCharCount": len("# Contract\n\nBody\n"),
        "qualityLevel": "degraded",
    }
    assert blocks.json()["items"] == [
        {
            "id": str(ids["block"]),
            "blockType": "text",
            "orderIndex": 0,
            "textContent": "Body",
            "markdownContent": "Body",
            "headingLevel": 1,
            "headingPath": ["Contract"],
            "pageNumber": 1,
            "boundingBox": None,
            "assetIds": [str(ids["asset"])],
            "rawLocator": {
                "artifactPath": "result_content_list.json",
                "itemIndex": 0,
            },
        }
    ]
    assert blocks.json()["total"] == 1
    assert assets.json()["items"][0]["id"] == str(ids["asset"])
    assert (
        assets.json()["items"][0]["sha256"] == hashlib.sha256(b"\x89PNG\r\n\x1a\nasset").hexdigest()
    )
    assert [item["artifactType"] for item in artifacts.json()["items"]] == [
        "markdown",
        "mineru_full_zip",
    ]
    assert downloaded.status_code == 200
    assert downloaded.content == b"\x89PNG\r\n\x1a\nasset"
    assert downloaded.headers["content-type"].startswith("image/png")
    assert downloaded.headers["etag"] == f'"{assets.json()["items"][0]["sha256"]}"'

    serialized = json.dumps(
        [detail.json(), markdown.json(), blocks.json(), assets.json(), artifacts.json()]
    )
    assert "storageKey" not in serialized
    assert str(storage_root) not in serialized


def test_content_reads_require_terminal_version_ownership_and_authentication(
    content_client: tuple[TestClient, dict[str, UUID], Path],
) -> None:
    client, ids, _storage_root = content_client

    not_ready = client.get(f"/api/v1/parsed-source-versions/{ids['queued_version']}/markdown")
    wrong_owner = client.get(
        f"/api/v1/parsed-source-versions/{ids['queued_version']}/assets/{ids['asset']}"
    )
    client.cookies.clear()
    unauthenticated = client.get(f"/api/v1/parsed-source-versions/{ids['version']}")

    assert not_ready.status_code == 409
    assert not_ready.json()["code"] == "PARSED_VERSION_NOT_SELECTABLE"
    assert wrong_owner.status_code == 404
    assert unauthenticated.status_code == 401
