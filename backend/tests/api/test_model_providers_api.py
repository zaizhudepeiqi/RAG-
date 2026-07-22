import json
from collections.abc import Iterator
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
PROVIDER_CREDENTIAL = "provider-test-credential-1234"


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
def provider_client(
    tmp_path: Path,
    migrated_database_url: str,
    database_engine: Engine,
) -> Iterator[tuple[TestClient, Engine]]:
    with database_engine.begin() as connection:
        connection.execute(text("TRUNCATE audit_logs, model_providers, administrators CASCADE"))
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


def create_provider(
    client: TestClient,
    *,
    display_name: str = "Primary OpenAI",
    credential: str = PROVIDER_CREDENTIAL,
) -> object:
    return client.post(
        "/api/v1/model-providers",
        headers={"X-CSRF-Token": client.cookies.get("rag_csrf") or ""},
        json={
            "providerType": "openai",
            "displayName": display_name,
            "baseUrl": "https://8.8.8.8/v1",
            "credential": credential,
        },
    )


def assert_no_secret_fields(payload: object, plaintexts: tuple[str, ...]) -> None:
    serialized = json.dumps(payload)
    for plaintext in plaintexts:
        assert plaintext not in serialized

    forbidden = {
        "credential",
        "credentialCiphertext",
        "credentialNonce",
        "credentialKeyVersion",
        "token",
        "ciphertext",
        "nonce",
    }

    def visit(value: object) -> None:
        if isinstance(value, dict):
            assert forbidden.isdisjoint(value)
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(payload)


def test_create_list_and_get_provider_without_secret_material(
    provider_client: tuple[TestClient, Engine],
) -> None:
    client, _engine = provider_client

    created = create_provider(client)

    assert created.status_code == 201, created.json()
    body = created.json()
    provider_id = body["id"]
    assert body == {
        "id": provider_id,
        "providerType": "openai",
        "displayName": "Primary OpenAI",
        "baseUrl": "https://8.8.8.8/v1",
        "credentialConfigured": True,
        "credentialMasked": "prov...1234",
        "enabled": True,
        "modelCount": 0,
        "revision": 1,
        "createdAt": body["createdAt"],
        "updatedAt": body["updatedAt"],
    }
    listing = client.get(
        "/api/v1/model-providers",
        params={"page": 1, "pageSize": 20, "sort": "display_name", "search": "primary"},
    )
    detail = client.get(f"/api/v1/model-providers/{provider_id}")

    assert listing.status_code == 200
    assert listing.json() == {
        "items": [body],
        "total": 1,
        "page": 1,
        "pageSize": 20,
    }
    assert detail.status_code == 200
    assert detail.json() == body
    assert_no_secret_fields([body, listing.json(), detail.json()], (PROVIDER_CREDENTIAL,))


def test_rename_and_rotate_credential_with_revision_guard(
    provider_client: tuple[TestClient, Engine],
) -> None:
    client, engine = provider_client
    created = create_provider(client).json()
    provider_id = UUID(created["id"])
    csrf = client.cookies.get("rag_csrf") or ""

    renamed = client.patch(
        f"/api/v1/model-providers/{provider_id}",
        headers={"X-CSRF-Token": csrf},
        json={"expectedRevision": 1, "displayName": "Production OpenAI"},
    )
    stale = client.patch(
        f"/api/v1/model-providers/{provider_id}",
        headers={"X-CSRF-Token": csrf},
        json={"expectedRevision": 1, "displayName": "Outdated Update"},
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO model_configs (
                    id, provider_id, model_name, display_name, model_type,
                    verification_status, capability_version
                ) VALUES (
                    :id, :provider_id, 'gpt-test', 'GPT Test', 'llm', 'passed', '1'
                )
                """
            ),
            {"id": uuid4(), "provider_id": provider_id},
        )
    replacement = "sk-rotated-secret-9876"
    rotated = client.patch(
        f"/api/v1/model-providers/{provider_id}",
        headers={"X-CSRF-Token": csrf},
        json={"expectedRevision": 2, "credential": replacement},
    )

    assert renamed.status_code == 200
    assert renamed.json()["displayName"] == "Production OpenAI"
    assert renamed.json()["revision"] == 2
    assert stale.status_code == 409
    assert stale.json()["code"] == "REVISION_CONFLICT"
    assert rotated.status_code == 200
    assert rotated.json()["credentialMasked"] == "sk-r...9876"
    assert rotated.json()["revision"] == 3
    assert_no_secret_fields(rotated.json(), (PROVIDER_CREDENTIAL, replacement))

    with engine.connect() as connection:
        stored = connection.execute(
            text(
                """
                SELECT credential_ciphertext, credential_nonce, credential_revision
                FROM model_providers WHERE id = :provider_id
                """
            ),
            {"provider_id": provider_id},
        ).one()
        model_status = connection.scalar(
            text("SELECT verification_status FROM model_configs WHERE provider_id = :provider_id"),
            {"provider_id": provider_id},
        )
    assert stored.credential_ciphertext != replacement.encode()
    assert replacement.encode() not in stored.credential_ciphertext
    assert len(stored.credential_nonce) == 12
    assert stored.credential_revision == 2
    assert model_status == "stale"


def test_duplicate_display_name_and_identity_patch_are_rejected(
    provider_client: tuple[TestClient, Engine],
) -> None:
    client, _engine = provider_client
    first = create_provider(client, display_name="Shared Provider")
    provider_id = first.json()["id"]

    duplicate = create_provider(client, display_name="shared provider")
    identity_patch = client.patch(
        f"/api/v1/model-providers/{provider_id}",
        headers={"X-CSRF-Token": client.cookies.get("rag_csrf") or ""},
        json={
            "expectedRevision": 1,
            "providerType": "deepseek",
            "baseUrl": "https://1.1.1.1",
        },
    )

    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "MODEL_PROVIDER_NAME_CONFLICT"
    assert identity_patch.status_code == 422


def test_delete_provider_and_reject_delete_when_models_exist(
    provider_client: tuple[TestClient, Engine],
) -> None:
    client, engine = provider_client
    deletable = create_provider(client, display_name="Delete Me").json()
    in_use = create_provider(client, display_name="In Use").json()
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO model_configs (
                    id, provider_id, model_name, display_name, model_type, capability_version
                ) VALUES (:id, :provider_id, 'gpt-test', 'GPT Test', 'llm', '1')
                """
            ),
            {"id": uuid4(), "provider_id": UUID(in_use["id"])},
        )
    csrf = client.cookies.get("rag_csrf") or ""

    deleted = client.delete(
        f"/api/v1/model-providers/{deletable['id']}",
        params={"expectedRevision": 1},
        headers={"X-CSRF-Token": csrf},
    )
    missing = client.get(f"/api/v1/model-providers/{deletable['id']}")
    blocked = client.delete(
        f"/api/v1/model-providers/{in_use['id']}",
        params={"expectedRevision": 1},
        headers={"X-CSRF-Token": csrf},
    )

    assert deleted.status_code == 204
    assert deleted.content == b""
    assert missing.status_code == 404
    assert missing.json()["code"] == "MODEL_PROVIDER_NOT_FOUND"
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "MODEL_PROVIDER_IN_USE"


def test_provider_writes_require_csrf_and_reads_require_authentication(
    provider_client: tuple[TestClient, Engine],
) -> None:
    client, _engine = provider_client

    without_csrf = client.post(
        "/api/v1/model-providers",
        json={
            "providerType": "openai",
            "displayName": "No CSRF",
            "baseUrl": "https://8.8.8.8/v1",
            "credential": PROVIDER_CREDENTIAL,
        },
    )
    client.cookies.delete("rag_admin_access")
    without_auth = client.get("/api/v1/model-providers")

    assert without_csrf.status_code == 403
    assert without_csrf.json()["code"] == "CSRF_INVALID"
    assert without_auth.status_code == 401
    assert without_auth.json()["code"] == "AUTH_UNAUTHORIZED"
