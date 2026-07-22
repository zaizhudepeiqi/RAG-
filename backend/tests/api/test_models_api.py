from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

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
def models_client(
    tmp_path: Path,
    migrated_database_url: str,
    database_engine: Engine,
) -> Iterator[tuple[TestClient, Engine]]:
    with database_engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE audit_logs, model_verifications, task_outbox, operations, "
                "model_providers, administrators CASCADE"
            )
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
        yield client, database_engine


def csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get("rag_csrf") or ""}


def create_provider(
    client: TestClient,
    *,
    provider_type: str = "openai",
    display_name: str = "Model Provider",
) -> dict[str, object]:
    response = client.post(
        "/api/v1/model-providers",
        headers=csrf(client),
        json={
            "providerType": provider_type,
            "displayName": display_name,
            "baseUrl": "https://8.8.8.8/v1",
            "credential": "sk-model-secret-1234",
        },
    )
    assert response.status_code == 201
    return response.json()


def create_model(
    client: TestClient,
    provider_id: object,
    *,
    model_name: str = "gpt-model-v1",
    display_name: str = "GPT Model",
    model_type: str = "llm",
) -> object:
    return client.post(
        "/api/v1/models",
        headers=csrf(client),
        json={
            "providerId": str(provider_id),
            "modelName": model_name,
            "displayName": display_name,
            "modelType": model_type,
            "contextWindow": 8192,
            "maxOutputTokens": 2048,
            "defaultParams": {"temperature": 0.2},
        },
    )


def insert_passed_verification(
    engine: Engine,
    *,
    model_id: UUID,
    provider_id: UUID,
    model_revision: int = 1,
    provider_revision: int = 1,
    credential_revision: int = 1,
) -> None:
    operation_id = uuid4()
    now = datetime.now(UTC)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO operations (
                    id, task_type, target_type, target_id, target_revision,
                    status, business_idempotency_key, queued_at, finished_at,
                    created_at, expires_at
                ) VALUES (
                    :operation_id, 'model_verification', 'model', :model_id, :model_revision,
                    'succeeded', :business_key, :now, :now, :now, :expires_at
                )
                """
            ),
            {
                "operation_id": operation_id,
                "model_id": model_id,
                "model_revision": model_revision,
                "business_key": uuid4().hex * 2,
                "now": now,
                "expires_at": now + timedelta(days=90),
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO model_verifications (
                    id, model_id, operation_id, tested_model_revision,
                    tested_provider_revision, tested_credential_revision,
                    status, latency_ms, provider_request_id, response_summary, tested_at
                ) VALUES (
                    :id, :model_id, :operation_id, :model_revision,
                    :provider_revision, :credential_revision,
                    'succeeded', 12, 'req-model-verify',
                    '{"outputPresent": true}'::jsonb, :now
                )
                """
            ),
            {
                "id": uuid4(),
                "model_id": model_id,
                "operation_id": operation_id,
                "model_revision": model_revision,
                "provider_revision": provider_revision,
                "credential_revision": credential_revision,
                "now": now,
            },
        )
        connection.execute(
            text("UPDATE model_configs SET verification_status = 'passed' WHERE id = :model_id"),
            {"model_id": model_id},
        )


def test_create_list_and_get_model_defaults(models_client: tuple[TestClient, Engine]) -> None:
    client, _engine = models_client
    provider = create_provider(client)

    created = create_model(client, provider["id"])

    assert created.status_code == 201, created.json()
    body = created.json()
    model_id = body["id"]
    assert body["provider"] == {"id": provider["id"], "displayName": "Model Provider"}
    assert body["modelName"] == "gpt-model-v1"
    assert body["displayName"] == "GPT Model"
    assert body["modelType"] == "llm"
    assert body["enabled"] is False
    assert body["verificationStatus"] == "untested"
    assert body["capabilityVersion"] == "1"
    assert body["defaultParams"] == {"temperature": 0.2}
    assert body["configSchema"] == {"type": "object", "additionalProperties": False}
    assert body["lastVerification"] is None
    assert body["usedByKnowledgeBaseCount"] == body["usedByBotCount"] == 0
    assert body["revision"] == 1

    listing = client.get(
        "/api/v1/models",
        params={
            "providerId": provider["id"],
            "modelType": "llm",
            "enabled": "false",
            "verificationStatus": "untested",
            "search": "gpt",
            "page": 1,
            "pageSize": 20,
            "sort": "display_name",
        },
    )
    detail = client.get(f"/api/v1/models/{model_id}")

    assert listing.status_code == 200
    assert listing.json()["items"] == [body]
    assert listing.json()["total"] == 1
    assert detail.status_code == 200
    assert detail.json() == body


def test_create_rejects_missing_disabled_unsupported_or_duplicate_provider_model(
    models_client: tuple[TestClient, Engine],
) -> None:
    client, engine = models_client
    openai = create_provider(client, display_name="OpenAI Models")
    deepseek = create_provider(
        client,
        provider_type="deepseek",
        display_name="DeepSeek Models",
    )

    first = create_model(client, openai["id"])
    duplicate = create_model(client, openai["id"])
    missing = create_model(client, uuid4())
    unsupported = create_model(
        client,
        deepseek["id"],
        model_name="deepseek-embedding",
        model_type="embedding",
    )
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE model_providers SET enabled = false WHERE id = :provider_id"),
            {"provider_id": UUID(str(openai["id"]))},
        )
    disabled = create_model(client, openai["id"], model_name="another-model")
    existing_detail = client.get(f"/api/v1/models/{first.json()['id']}")

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "MODEL_CONFLICT"
    assert missing.status_code == 404
    assert missing.json()["code"] == "MODEL_PROVIDER_NOT_FOUND"
    assert unsupported.status_code == 422
    assert unsupported.json()["code"] == "MODEL_TYPE_MISMATCH"
    assert disabled.status_code == 409
    assert disabled.json()["code"] == "MODEL_PROVIDER_DISABLED"
    assert existing_detail.status_code == 200


def test_callable_update_stales_model_but_display_rename_does_not_change_revision(
    models_client: tuple[TestClient, Engine],
) -> None:
    client, engine = models_client
    provider = create_provider(client)
    created = create_model(client, provider["id"]).json()
    model_id = UUID(created["id"])
    insert_passed_verification(
        engine,
        model_id=model_id,
        provider_id=UUID(str(provider["id"])),
    )

    renamed = client.patch(
        f"/api/v1/models/{model_id}",
        headers=csrf(client),
        json={"expectedRevision": 1, "displayName": "Renamed GPT"},
    )
    changed = client.patch(
        f"/api/v1/models/{model_id}",
        headers=csrf(client),
        json={
            "expectedRevision": 1,
            "defaultParams": {"temperature": 0.1},
            "configSchema": {"type": "object", "additionalProperties": True},
        },
    )

    assert renamed.status_code == 200
    assert renamed.json()["displayName"] == "Renamed GPT"
    assert renamed.json()["verificationStatus"] == "passed"
    assert renamed.json()["revision"] == 1
    assert changed.status_code == 200
    assert changed.json()["verificationStatus"] == "stale"
    assert changed.json()["revision"] == 2


def test_enable_requires_current_verification_and_disable_delete_are_soft(
    models_client: tuple[TestClient, Engine],
) -> None:
    client, engine = models_client
    provider = create_provider(client)
    created = create_model(client, provider["id"]).json()
    model_id = UUID(created["id"])

    unverified = client.post(
        f"/api/v1/models/{model_id}:enable",
        headers=csrf(client),
        json={"expectedRevision": 1},
    )
    insert_passed_verification(
        engine,
        model_id=model_id,
        provider_id=UUID(str(provider["id"])),
    )
    enabled = client.post(
        f"/api/v1/models/{model_id}:enable",
        headers=csrf(client),
        json={"expectedRevision": 1},
    )
    references = client.get(f"/api/v1/models/{model_id}/references")
    disabled = client.post(
        f"/api/v1/models/{model_id}:disable",
        headers=csrf(client),
        json={"expectedRevision": 1},
    )
    deleted = client.delete(
        f"/api/v1/models/{model_id}",
        params={"expectedRevision": 1},
        headers=csrf(client),
    )
    missing = client.get(f"/api/v1/models/{model_id}")

    assert unverified.status_code == 409
    assert unverified.json()["code"] == "MODEL_VERIFICATION_REQUIRED"
    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True
    assert enabled.json()["revision"] == 1
    assert references.status_code == 200
    assert references.json() == []
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    assert deleted.status_code == 204
    assert missing.status_code == 404
    assert missing.json()["code"] == "MODEL_NOT_FOUND"
