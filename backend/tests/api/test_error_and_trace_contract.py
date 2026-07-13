import base64
from pathlib import Path
from uuid import UUID

from app.bootstrap.application import create_app
from app.core.config import Settings
from app.core.errors import AppError
from fastapi import FastAPI
from starlette.testclient import TestClient


def make_settings(tmp_path: Path, *, app_env: str = "test") -> Settings:
    return Settings(
        app_env=app_env,
        database_url="postgresql+psycopg://test:test@127.0.0.1:5432/rag_test",
        redis_url="redis://127.0.0.1:6379/15",
        storage_root=tmp_path / "storage",
        jwt_signing_key="j" * 32,
        credential_encryption_key=base64.b64encode(b"c" * 32).decode(),
        initial_admin_password="Initial-Admin-Password-01!",
    )


def add_contract_routes(app: FastAPI) -> None:
    @app.get("/_contract/success")
    def success() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/_contract/conflict")
    def conflict() -> None:
        raise AppError(
            code="RESOURCE_REVISION_CONFLICT",
            message="测试冲突",
            status_code=409,
            details={"current": "old"},
        )

    @app.get("/_contract/validation")
    def validation(count: int) -> dict[str, int]:
        return {"count": count}

    @app.get("/_contract/unhandled")
    def unhandled() -> None:
        raise RuntimeError("sensitive local failure")


def test_app_error_matches_stable_contract(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    add_contract_routes(app)
    response = TestClient(app).get("/_contract/conflict")

    trace_id = response.json()["traceId"]
    assert response.status_code == 409
    assert response.headers["X-Trace-Id"] == trace_id
    assert UUID(trace_id)
    assert response.json() == {
        "code": "RESOURCE_REVISION_CONFLICT",
        "message": "测试冲突",
        "traceId": trace_id,
        "details": {"current": "old"},
    }


def test_valid_trace_header_is_reused_and_security_headers_are_added(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    add_contract_routes(app)
    trace_id = "2777136d-608c-4c26-8b7a-bc6e15cd9158"

    response = TestClient(app).get("/_contract/success", headers={"X-Trace-Id": trace_id})

    assert response.status_code == 200
    assert response.headers["X-Trace-Id"] == trace_id
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Content-Security-Policy"] == "frame-ancestors 'none'"


def test_invalid_trace_header_is_replaced(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    add_contract_routes(app)

    response = TestClient(app).get(
        "/_contract/success", headers={"X-Trace-Id": "log-injection\nvalue"}
    )

    assert response.status_code == 200
    assert UUID(response.headers["X-Trace-Id"])
    assert response.headers["X-Trace-Id"] != "log-injection\nvalue"


def test_validation_errors_have_field_details_and_trace_id(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    add_contract_routes(app)

    response = TestClient(app).get("/_contract/validation", params={"count": "not-int"})

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert response.headers["X-Trace-Id"] == response.json()["traceId"]
    assert response.json()["details"]["fieldErrors"][0]["field"] == "query.count"


def test_unhandled_errors_do_not_expose_exception_or_local_path(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    add_contract_routes(app)

    response = TestClient(app, raise_server_exceptions=False).get("/_contract/unhandled")

    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert response.headers["X-Trace-Id"] == response.json()["traceId"]
    rendered = response.text.lower()
    assert "sensitive local failure" not in rendered
    assert str(tmp_path).lower() not in rendered


def test_cors_allows_only_the_configured_frontend_origin(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    add_contract_routes(app)
    client = TestClient(app)
    headers = {
        "Origin": "http://127.0.0.1:5173",
        "Access-Control-Request-Method": "GET",
    }

    allowed = client.options("/_contract/success", headers=headers)
    denied = client.options(
        "/_contract/success", headers={**headers, "Origin": "https://evil.example"}
    )

    assert allowed.status_code == 200
    assert allowed.headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:5173"
    assert denied.status_code == 400
    assert "Access-Control-Allow-Origin" not in denied.headers


def test_production_disables_openapi_by_default(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path, app_env="production"))

    assert app.openapi_url is None
    assert app.docs_url is None
    assert app.redoc_url is None
