from collections.abc import Iterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from app.bootstrap.application import create_app
from app.core.config import Settings
from app.infrastructure.database.models.knowledge_bases import KnowledgeBaseModel
from app.infrastructure.database.models.parsing import ParsedSourceVersionModel
from redis import Redis
from sqlalchemy import Engine, func, select, text
from starlette.testclient import TestClient
from tests.api.test_models_api import insert_passed_verification
from tests.integration.database.test_models_schema import insert_model, insert_provider
from tests.integration.database.test_parsing_schema import (
    FEATURE_FLAGS,
    insert_blob,
    insert_source,
    insert_version,
)

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
def knowledge_base_client(
    tmp_path: Path,
    migrated_database_url: str,
    database_engine: Engine,
) -> Iterator[tuple[TestClient, Engine, UUID, tuple[UUID, UUID]]]:
    with database_engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE audit_logs, api_idempotency_records, task_outbox, operations, "
                "knowledge_bases, model_providers, administrators CASCADE"
            )
        )
        provider_id = insert_provider(
            connection,
            display_name=f"KB API provider {uuid4().hex}",
        )
        model_id = insert_model(
            connection,
            provider_id=provider_id,
            model_name=f"embedding-{uuid4().hex}",
            verification_status="passed",
        )
        versions: list[UUID] = []
        for index in range(2):
            blob_id = insert_blob(connection)
            source_id = insert_source(connection, blob_id=blob_id)
            versions.append(
                insert_version(
                    connection,
                    source_id=source_id,
                    status="succeeded",
                    quality_level="full",
                    feature_flags={**FEATURE_FLAGS, "hasText": True},
                    block_count=index + 1,
                )
            )
    insert_passed_verification(
        database_engine,
        model_id=model_id,
        provider_id=provider_id,
    )
    with database_engine.begin() as connection:
        connection.execute(
            text("UPDATE model_configs SET enabled = true WHERE id = :model_id"),
            {"model_id": model_id},
        )
    redis_client = Redis.from_url("redis://127.0.0.1:6379/15")
    redis_client.flushdb()
    redis_client.close()

    with TestClient(create_app(make_settings(tmp_path, migrated_database_url))) as client:
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
        yield client, database_engine, model_id, (versions[0], versions[1])


def csrf(client: TestClient, idempotency_key: str | None = None) -> dict[str, str]:
    headers = {"X-CSRF-Token": client.cookies.get("rag_csrf") or ""}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return headers


def create_payload(model_id: UUID, version_ids: tuple[UUID, UUID]) -> dict[str, object]:
    return {
        "name": f"Enterprise KB {uuid4().hex}",
        "description": "Internal policies",
        "parsedSourceVersionIds": [str(item) for item in version_ids],
        "buildConfig": {
            "embeddingModelId": str(model_id),
            "embeddingParams": {},
            "vectorStoreCode": "chroma",
            "vectorIndexCode": "hnsw",
            "vectorIndexParams": {"metric": "cosine"},
            "keywordStoreCode": "postgres_trigram",
            "indexStructure": "chunk",
            "indexStructureParams": {},
            "chunkStrategyCode": "token",
            "chunkParams": {"chunkSize": 512, "chunkOverlap": 64},
        },
        "retrievalConfig": {
            "retrievalType": "hybrid",
            "vector": {"topK": 20, "scoreThreshold": 0.3},
            "keyword": {"topK": 20, "scoreThreshold": 0.1},
            "hybrid": {
                "fusionStrategy": "rrf",
                "rrfK": 60,
                "finalScoreThreshold": 0,
            },
            "queryRewrite": {"strategyCode": "off", "params": {}},
            "rerank": {"strategyCode": "off", "params": {}},
            "contextWindow": 0,
            "finalTopK": 10,
        },
    }


def test_create_is_idempotent_and_exposes_list_and_detail(
    knowledge_base_client: tuple[TestClient, Engine, UUID, tuple[UUID, UUID]],
) -> None:
    client, engine, model_id, version_ids = knowledge_base_client
    payload = create_payload(model_id, version_ids)
    key = "knowledge-base-create-0001"

    created = client.post(
        "/api/v1/knowledge-bases",
        headers=csrf(client, key),
        json=payload,
    )
    repeated = client.post(
        "/api/v1/knowledge-bases",
        headers=csrf(client, key),
        json=payload,
    )

    assert created.status_code == 201, created.json()
    assert repeated.status_code == 201, repeated.json()
    body = created.json()
    assert repeated.json() == body
    detail = body["knowledgeBase"]
    assert detail["derivedDisplayStatus"] == "building"
    assert detail["sourceCount"] == 2
    assert detail["embeddingModelId"] == str(model_id)
    assert detail["indexStructure"] == "chunk"
    assert detail["retrievalType"] == "hybrid"
    assert "delete" not in detail["allowedActions"]
    assert body["operation"]["targetId"] == detail["id"]

    listed = client.get("/api/v1/knowledge-bases", params={"search": "Enterprise KB"})
    fetched = client.get(f"/api/v1/knowledge-bases/{detail['id']}")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert fetched.status_code == 200
    assert fetched.json() == detail
    with engine.begin() as connection:
        assert connection.scalar(select(func.count()).select_from(KnowledgeBaseModel)) == 1


def test_create_rejects_reusing_an_idempotency_key_for_a_different_request(
    knowledge_base_client: tuple[TestClient, Engine, UUID, tuple[UUID, UUID]],
) -> None:
    client, _engine, model_id, version_ids = knowledge_base_client
    payload = create_payload(model_id, version_ids)
    key = "knowledge-base-create-0002"
    first = client.post(
        "/api/v1/knowledge-bases",
        headers=csrf(client, key),
        json=payload,
    )
    payload["name"] = "A different knowledge base"

    reused = client.post(
        "/api/v1/knowledge-bases",
        headers=csrf(client, key),
        json=payload,
    )

    assert first.status_code == 201
    assert reused.status_code == 409
    assert reused.json()["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_metadata_and_enabled_state_use_revision_conflicts(
    knowledge_base_client: tuple[TestClient, Engine, UUID, tuple[UUID, UUID]],
) -> None:
    client, _engine, model_id, version_ids = knowledge_base_client
    created = client.post(
        "/api/v1/knowledge-bases",
        headers=csrf(client, "knowledge-base-create-0003"),
        json=create_payload(model_id, version_ids),
    ).json()["knowledgeBase"]

    updated = client.patch(
        f"/api/v1/knowledge-bases/{created['id']}/metadata",
        headers=csrf(client),
        json={
            "name": "Updated enterprise knowledge",
            "description": "Updated description",
            "expectedRevision": 1,
        },
    )
    disabled = client.post(
        f"/api/v1/knowledge-bases/{created['id']}:disable",
        headers=csrf(client),
        json={"expectedRevision": 2},
    )
    stale = client.post(
        f"/api/v1/knowledge-bases/{created['id']}:enable",
        headers=csrf(client),
        json={"expectedRevision": 2},
    )

    assert updated.status_code == 200
    assert updated.json()["revision"] == 2
    assert disabled.status_code == 200
    assert disabled.json()["revision"] == 3
    assert disabled.json()["derivedDisplayStatus"] == "disabled"
    assert stale.status_code == 409
    assert stale.json()["code"] == "REVISION_CONFLICT"


def test_delete_rejects_running_build_then_soft_deletes_without_deleting_sources(
    knowledge_base_client: tuple[TestClient, Engine, UUID, tuple[UUID, UUID]],
) -> None:
    client, engine, model_id, version_ids = knowledge_base_client
    created = client.post(
        "/api/v1/knowledge-bases",
        headers=csrf(client, "knowledge-base-create-0004"),
        json=create_payload(model_id, version_ids),
    ).json()["knowledgeBase"]

    blocked = client.delete(
        f"/api/v1/knowledge-bases/{created['id']}",
        headers=csrf(client, "knowledge-base-delete-0001"),
        params={"expectedRevision": 1},
    )
    assert blocked.status_code == 409
    assert blocked.json()["details"]["reason"] == "BUILD_RUNNING"

    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE index_generations SET status = 'failed' "
                "WHERE knowledge_base_id = :knowledge_base_id"
            ),
            {"knowledge_base_id": UUID(created["id"])},
        )

    deleted = client.delete(
        f"/api/v1/knowledge-bases/{created['id']}",
        headers=csrf(client, "knowledge-base-delete-0002"),
        params={"expectedRevision": 1},
    )
    repeated = client.delete(
        f"/api/v1/knowledge-bases/{created['id']}",
        headers=csrf(client, "knowledge-base-delete-0002"),
        params={"expectedRevision": 1},
    )

    assert deleted.status_code == 202
    assert repeated.status_code == 202
    assert repeated.json() == deleted.json()
    assert client.get(f"/api/v1/knowledge-bases/{created['id']}").status_code == 404
    with engine.begin() as connection:
        assert (
            connection.scalar(
                select(func.count())
                .select_from(ParsedSourceVersionModel)
                .where(ParsedSourceVersionModel.id.in_(version_ids))
            )
            == 2
        )
