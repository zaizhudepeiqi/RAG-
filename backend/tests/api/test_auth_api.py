from collections.abc import Iterator
from pathlib import Path

import pytest
from app.bootstrap.application import create_app
from app.core.config import Settings
from app.modules.auth.api import ACCESS_COOKIE, CSRF_COOKIE
from redis import Redis
from sqlalchemy import Engine, text
from starlette.testclient import TestClient

pytestmark = pytest.mark.integration

INITIAL_CREDENTIAL = "Initial-Admin-Password-01!"
NEW_CREDENTIAL = "Changed-Admin-Password-02!"


def make_settings(tmp_path: Path, database_url: str) -> Settings:
    return Settings(
        app_env="test",
        database_url=database_url,
        redis_url="redis://127.0.0.1:6379/15",
        storage_root=tmp_path / "storage",
        jwt_signing_key="j" * 48,
        credential_encryption_key="Y2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2M=",
        initial_admin_username="admin",
        initial_admin_password=INITIAL_CREDENTIAL,
        access_token_expire_minutes=60,
    )


@pytest.fixture
def auth_client(
    tmp_path: Path,
    migrated_database_url: str,
    database_engine: Engine,
) -> Iterator[TestClient]:
    with database_engine.begin() as connection:
        connection.execute(
            text("TRUNCATE audit_logs, api_idempotency_records, administrators CASCADE")
        )
    redis_client = Redis.from_url("redis://127.0.0.1:6379/15")
    redis_client.flushdb()
    redis_client.close()

    with TestClient(create_app(make_settings(tmp_path, migrated_database_url))) as client:
        yield client


def login(client: TestClient, password: str = INITIAL_CREDENTIAL) -> dict[str, object]:
    response = client.post("/api/v1/auth/login", json={"username": "admin", "password": password})
    assert response.status_code == 200
    return response.json()


def test_login_error_does_not_reveal_unknown_username(auth_client: TestClient) -> None:
    unknown = auth_client.post(
        "/api/v1/auth/login",
        json={"username": "missing-admin", "password": "Wrong-Password-01!"},
    )
    wrong_password = auth_client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "Wrong-Password-01!"},
    )

    assert unknown.status_code == wrong_password.status_code == 401
    assert unknown.json()["code"] == wrong_password.json()["code"] == "AUTH_INVALID_CREDENTIALS"
    assert unknown.json()["message"] == wrong_password.json()["message"]
    assert "missing-admin" not in unknown.text


def test_first_login_can_only_change_password_logout_or_read_health(
    auth_client: TestClient,
) -> None:
    body = login(auth_client)

    me = auth_client.get("/api/v1/auth/me")
    logout = auth_client.post(
        "/api/v1/auth/logout",
        headers={"X-CSRF-Token": str(body["csrfToken"])},
    )

    assert me.status_code == 403
    assert me.json()["code"] == "AUTH_PASSWORD_CHANGE_REQUIRED"
    assert logout.status_code == 200


def test_logout_increments_auth_version_and_invalidates_current_token(
    auth_client: TestClient,
) -> None:
    body = login(auth_client)
    old_token = auth_client.cookies.get(ACCESS_COOKIE)

    response = auth_client.post(
        "/api/v1/auth/logout",
        headers={"X-CSRF-Token": str(body["csrfToken"])},
    )
    auth_client.cookies.set(ACCESS_COOKIE, old_token)
    old_session = auth_client.get("/api/v1/auth/me")

    assert response.status_code == 200
    assert old_session.status_code == 401
    assert old_session.json()["code"] == "AUTH_UNAUTHORIZED"


def test_password_change_invalidates_old_tokens_and_issues_current_token(
    auth_client: TestClient,
) -> None:
    body = login(auth_client)
    old_token = auth_client.cookies.get(ACCESS_COOKIE)

    changed = auth_client.post(
        "/api/v1/auth/change-password",
        headers={"X-CSRF-Token": str(body["csrfToken"])},
        json={
            "oldPassword": INITIAL_CREDENTIAL,
            "newPassword": NEW_CREDENTIAL,
            "confirmPassword": NEW_CREDENTIAL,
        },
    )
    new_token = auth_client.cookies.get(ACCESS_COOKIE)
    current_session = auth_client.get("/api/v1/auth/me")
    auth_client.cookies.set(ACCESS_COOKIE, old_token)
    old_session = auth_client.get("/api/v1/auth/me")

    assert changed.status_code == 200
    assert changed.json() == {"success": True}
    assert new_token != old_token
    assert current_session.status_code == 200
    assert current_session.json()["firstLoginRequired"] is False
    assert old_session.status_code == 401


def test_ten_failures_in_fifteen_minutes_return_429_and_retry_after(
    auth_client: TestClient,
) -> None:
    responses = [
        auth_client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "Wrong-Password-01!"},
        )
        for _ in range(10)
    ]

    assert all(response.status_code == 401 for response in responses[:9])
    assert responses[9].status_code == 429
    assert int(responses[9].headers["Retry-After"]) > 0


def test_write_without_matching_csrf_is_403(auth_client: TestClient) -> None:
    login(auth_client)

    response = auth_client.post("/api/v1/auth/logout")

    assert response.status_code == 403
    assert response.json()["code"] == "CSRF_INVALID"


def test_login_sets_access_and_csrf_cookie_contract(auth_client: TestClient) -> None:
    response = auth_client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": INITIAL_CREDENTIAL},
    )
    cookies = response.headers.get_list("set-cookie")
    access_cookie = next(value for value in cookies if value.startswith(f"{ACCESS_COOKIE}="))
    csrf_cookie = next(value for value in cookies if value.startswith(f"{CSRF_COOKIE}="))

    assert "HttpOnly" in access_cookie
    assert "SameSite=lax" in access_cookie
    assert "Path=/" in access_cookie
    assert "HttpOnly" not in csrf_cookie
    assert "SameSite=lax" in csrf_cookie
