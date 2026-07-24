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
MINERU_CREDENTIAL = "mineru-api-token-1234"
ROTATED_CREDENTIAL = "mineru-rotated-token-5678"
DEFAULT_PARSE_CONFIG = {
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
def mineru_client(
    tmp_path: Path,
    migrated_database_url: str,
    database_engine: Engine,
) -> Iterator[tuple[TestClient, Engine]]:
    with database_engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE audit_logs, api_idempotency_records, task_outbox, operations, "
                "mineru_settings, administrators CASCADE"
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


def update_payload(*, revision: int, token: str | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "expectedRevision": revision,
        "baseUrl": "https://8.8.8.8/api/v4",
        "defaultParseConfig": DEFAULT_PARSE_CONFIG,
        "pollTimeoutSeconds": 1800,
    }
    if token is not None:
        payload["token"] = token
    return payload


def test_get_returns_singleton_defaults_without_token(
    mineru_client: tuple[TestClient, Engine],
) -> None:
    client, engine = mineru_client

    first = client.get("/api/v1/settings/mineru")
    second = client.get("/api/v1/settings/mineru")

    assert first.status_code == 200
    assert second.status_code == 200
    assert (
        first.json()
        == second.json()
        == {
            "baseUrl": "https://mineru.net",
            "tokenConfigured": False,
            "tokenMasked": None,
            "defaultParseConfig": DEFAULT_PARSE_CONFIG,
            "pollTimeoutSeconds": 1800,
            "cloudProcessingConfirmedAt": None,
            "termsVersion": None,
            "revision": 1,
        }
    )
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM mineru_settings")) == 1


def test_first_token_requires_consent_and_is_encrypted(
    mineru_client: tuple[TestClient, Engine],
) -> None:
    client, engine = mineru_client
    client.get("/api/v1/settings/mineru")
    csrf = client.cookies.get("rag_csrf") or ""

    rejected = client.patch(
        "/api/v1/settings/mineru",
        headers={"X-CSRF-Token": csrf},
        json=update_payload(revision=1, token=MINERU_CREDENTIAL),
    )
    payload = update_payload(revision=1, token=MINERU_CREDENTIAL)
    payload["cloudProcessingConsent"] = {
        "accepted": True,
        "termsVersion": "mineru-cloud-v1",
    }
    accepted = client.patch(
        "/api/v1/settings/mineru",
        headers={"X-CSRF-Token": csrf},
        json=payload,
    )

    assert rejected.status_code == 422
    assert rejected.json()["code"] == "MINERU_CLOUD_CONSENT_REQUIRED"
    assert accepted.status_code == 200
    body = accepted.json()
    assert body["tokenConfigured"] is True
    assert body["tokenMasked"] == "mine...1234"
    assert body["termsVersion"] == "mineru-cloud-v1"
    assert body["cloudProcessingConfirmedAt"] is not None
    assert body["revision"] == 2
    assert MINERU_CREDENTIAL not in json.dumps(body)

    with engine.connect() as connection:
        stored = connection.execute(
            text(
                "SELECT token_ciphertext, token_nonce, token_revision, "
                "cloud_processing_confirmed_by FROM mineru_settings"
            )
        ).one()
        audits = (
            connection.execute(
                text(
                    "SELECT change_summary::text FROM audit_logs "
                    "WHERE event_code = 'mineru.settings.updated'"
                )
            )
            .scalars()
            .all()
        )
    assert stored.token_ciphertext != MINERU_CREDENTIAL.encode()
    assert MINERU_CREDENTIAL.encode() not in stored.token_ciphertext
    assert len(stored.token_nonce) == 12
    assert stored.token_revision == 1
    assert stored.cloud_processing_confirmed_by is not None
    assert MINERU_CREDENTIAL not in "".join(audits)


def test_empty_token_preserves_ciphertext_and_rotation_increments_revision(
    mineru_client: tuple[TestClient, Engine],
) -> None:
    client, engine = mineru_client
    client.get("/api/v1/settings/mineru")
    csrf = client.cookies.get("rag_csrf") or ""
    initial = update_payload(revision=1, token=MINERU_CREDENTIAL)
    initial["cloudProcessingConsent"] = {
        "accepted": True,
        "termsVersion": "mineru-cloud-v1",
    }
    assert (
        client.patch(
            "/api/v1/settings/mineru", headers={"X-CSRF-Token": csrf}, json=initial
        ).status_code
        == 200
    )

    with engine.connect() as connection:
        before = connection.execute(
            text("SELECT token_ciphertext, token_nonce, token_revision FROM mineru_settings")
        ).one()
    preserved_payload = update_payload(revision=2, token="")
    preserved = client.patch(
        "/api/v1/settings/mineru",
        headers={"X-CSRF-Token": csrf},
        json=preserved_payload,
    )
    with engine.connect() as connection:
        after_preserve = connection.execute(
            text("SELECT token_ciphertext, token_nonce, token_revision FROM mineru_settings")
        ).one()
    rotated = client.patch(
        "/api/v1/settings/mineru",
        headers={"X-CSRF-Token": csrf},
        json=update_payload(revision=3, token=ROTATED_CREDENTIAL),
    )
    with engine.connect() as connection:
        after_rotation = connection.execute(
            text("SELECT token_ciphertext, token_nonce, token_revision FROM mineru_settings")
        ).one()

    assert preserved.status_code == 200
    assert tuple(after_preserve) == tuple(before)
    assert rotated.status_code == 200
    assert after_rotation.token_ciphertext != before.token_ciphertext
    assert after_rotation.token_nonce != before.token_nonce
    assert after_rotation.token_revision == 2
    assert ROTATED_CREDENTIAL.encode() not in after_rotation.token_ciphertext


def test_stale_revision_and_extra_parse_config_fields_are_rejected(
    mineru_client: tuple[TestClient, Engine],
) -> None:
    client, _engine = mineru_client
    client.get("/api/v1/settings/mineru")
    csrf = client.cookies.get("rag_csrf") or ""
    valid = client.patch(
        "/api/v1/settings/mineru",
        headers={"X-CSRF-Token": csrf},
        json=update_payload(revision=1),
    )
    stale = client.patch(
        "/api/v1/settings/mineru",
        headers={"X-CSRF-Token": csrf},
        json=update_payload(revision=1),
    )
    invalid_payload = update_payload(revision=2)
    invalid_payload["defaultParseConfig"] = {
        **DEFAULT_PARSE_CONFIG,
        "providerPayload": {"unsafe": True},
    }
    invalid = client.patch(
        "/api/v1/settings/mineru",
        headers={"X-CSRF-Token": csrf},
        json=invalid_payload,
    )

    assert valid.status_code == 200
    assert stale.status_code == 409
    assert stale.json()["code"] == "REVISION_CONFLICT"
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "VALIDATION_ERROR"


def test_mineru_test_requires_configured_token_and_creates_idempotent_operation(
    mineru_client: tuple[TestClient, Engine],
) -> None:
    client, engine = mineru_client
    client.get("/api/v1/settings/mineru")
    operation_headers = {
        "X-CSRF-Token": client.cookies.get("rag_csrf") or "",
        "Idempotency-Key": "mineru-settings-test-0001",
    }

    unconfigured = client.post(
        "/api/v1/settings/mineru:test",
        headers=operation_headers,
        json={"expectedRevision": 1},
    )
    configured_payload = update_payload(revision=1, token=MINERU_CREDENTIAL)
    configured_payload["cloudProcessingConsent"] = {
        "accepted": True,
        "termsVersion": "mineru-cloud-v1",
    }
    configured = client.patch(
        "/api/v1/settings/mineru",
        headers={"X-CSRF-Token": client.cookies.get("rag_csrf") or ""},
        json=configured_payload,
    )
    tested = client.post(
        "/api/v1/settings/mineru:test",
        headers=operation_headers,
        json={"expectedRevision": 2},
    )
    repeated = client.post(
        "/api/v1/settings/mineru:test",
        headers=operation_headers,
        json={"expectedRevision": 2},
    )

    assert unconfigured.status_code == 409
    assert unconfigured.json()["code"] == "MINERU_AUTH_FAILED"
    assert configured.status_code == 200
    assert tested.status_code == repeated.status_code == 202
    assert tested.json() == repeated.json()
    assert tested.json()["targetType"] == "mineru_settings"
    with engine.connect() as connection:
        operation = connection.execute(
            text("SELECT task_type, target_revision FROM operations WHERE id = :operation_id"),
            {"operation_id": tested.json()["operationId"]},
        ).one()
        outbox = connection.execute(
            text(
                "SELECT event_type, payload::text FROM task_outbox "
                "WHERE operation_id = :operation_id"
            ),
            {"operation_id": tested.json()["operationId"]},
        ).one()
    assert operation.task_type == "mineru_connection_test"
    assert operation.target_revision == 2
    assert outbox.event_type == "parsing.mineru.test.requested"
    assert MINERU_CREDENTIAL not in outbox.payload
    assert not any(
        forbidden in outbox.payload.lower()
        for forbidden in ("token", "ciphertext", "nonce", "credential")
    )

    definition = client.app.state.dependencies.task_dispatch_registry.resolve(
        "parsing.mineru.test.requested",
        "1",
    )
    assert definition.celery_task_name == "app.tasks.maintenance.test_mineru"
    assert definition.queue == "maintenance"
