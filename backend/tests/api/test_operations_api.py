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
def operations_client(
    tmp_path: Path,
    migrated_database_url: str,
    database_engine: Engine,
) -> Iterator[tuple[TestClient, Engine]]:
    with database_engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE audit_logs, api_idempotency_records, task_outbox, operation_items, "
                "operations, administrators CASCADE"
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
        csrf = logged_in.json()["csrfToken"]
        changed = client.post(
            "/api/v1/auth/change-password",
            headers={"X-CSRF-Token": csrf},
            json={
                "oldPassword": INITIAL_CREDENTIAL,
                "newPassword": CURRENT_CREDENTIAL,
                "confirmPassword": CURRENT_CREDENTIAL,
            },
        )
        assert changed.status_code == 200
        yield client, database_engine


def insert_operation(engine: Engine, *, status: str, retryable: bool = False) -> UUID:
    operation_id = uuid4()
    now = datetime.now(UTC)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO operations (
                    id, task_type, target_type, target_id, status,
                    business_idempotency_key, retryable, queued_at, created_at, expires_at
                ) VALUES (
                    :id, 'unregistered_task', 'test_target', :target_id, :status,
                    :business_key, :retryable, :now, :now, :expires_at
                )
                """
            ),
            {
                "id": operation_id,
                "target_id": uuid4(),
                "status": status,
                "business_key": uuid4().hex * 2,
                "retryable": retryable,
                "now": now,
                "expires_at": now + timedelta(days=90),
            },
        )
    return operation_id


def test_operations_list_detail_and_cancel(operations_client: tuple[TestClient, Engine]) -> None:
    client, engine = operations_client
    operation_id = insert_operation(engine, status="queued")
    csrf = client.cookies.get("rag_csrf")

    listing = client.get("/api/v1/operations")
    detail = client.get(f"/api/v1/operations/{operation_id}")
    cancelled = client.post(
        f"/api/v1/operations/{operation_id}:cancel",
        headers={"X-CSRF-Token": csrf or ""},
    )

    assert listing.status_code == 200
    assert listing.json()["items"][0]["operationId"] == str(operation_id)
    assert detail.status_code == 200
    assert "cancel" in detail.json()["allowedActions"]
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"


def test_retry_rejects_unregistered_task_type(
    operations_client: tuple[TestClient, Engine],
) -> None:
    client, engine = operations_client
    operation_id = insert_operation(engine, status="failed", retryable=True)

    response = client.post(
        f"/api/v1/operations/{operation_id}:retry",
        headers={
            "X-CSRF-Token": client.cookies.get("rag_csrf") or "",
            "Idempotency-Key": "retry-command-idempotency-0001",
        },
    )

    assert response.status_code == 409
    assert response.json()["code"] == "OPERATION_NOT_RETRYABLE"
