import base64
from pathlib import Path

from app.bootstrap.application import create_app
from app.core.config import Settings
from app.modules.auth.dependencies import require_admin
from app.modules.capabilities.domain import CapabilityOption
from app.modules.capabilities.registry import CapabilityRegistry
from app.modules.capabilities.service import CapabilityService
from starlette.testclient import TestClient


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        app_env="test",
        database_url="postgresql+psycopg://test:test@127.0.0.1:5432/rag_test",
        redis_url="redis://127.0.0.1:6379/15",
        storage_root=tmp_path / "storage",
        jwt_signing_key="j" * 32,
        credential_encryption_key=base64.b64encode(b"c" * 32).decode(),
        initial_admin_password="Initial-Admin-Password-01!",
    )


def test_api_serializes_config_and_ui_schema_without_unknown_fields(tmp_path: Path) -> None:
    registry = CapabilityRegistry()
    registry.register(
        CapabilityOption(
            code="token",
            name="Token 分块",
            description="按 Token 数量切分文档",
            enabled=True,
            visible=True,
            version="1",
            category="chunk_strategy",
            unavailable_reason=None,
            config_schema={
                "type": "object",
                "properties": {"size": {"type": "integer", "minimum": 1}},
            },
            ui_schema={"size": {"ui:widget": "number"}},
            required_source_features=("text",),
            preferred_source_features=("headings",),
        )
    )
    app = create_app(make_settings(tmp_path))
    app.state.dependencies.capability_service = CapabilityService(registry)
    app.dependency_overrides[require_admin] = lambda: None
    client = TestClient(app)

    response = client.get(
        "/api/v1/capabilities",
        params={"category": "chunk_strategy", "includeDisabled": "true"},
    )

    assert response.status_code == 200
    assert response.json() == [
        {
            "code": "token",
            "name": "Token 分块",
            "description": "按 Token 数量切分文档",
            "enabled": True,
            "visible": True,
            "version": "1",
            "category": "chunk_strategy",
            "unavailableReason": None,
            "configSchema": {
                "type": "object",
                "properties": {"size": {"type": "integer", "minimum": 1}},
            },
            "uiSchema": {"size": {"ui:widget": "number"}},
            "requiredSourceFeatures": ["text"],
            "preferredSourceFeatures": ["headings"],
        }
    ]
    client.close()


def test_unknown_capability_version_returns_stable_not_found(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    app.dependency_overrides[require_admin] = lambda: None
    client = TestClient(app)

    response = client.get(
        "/api/v1/capabilities/token/versions/999",
        params={"category": "chunk_strategy"},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "CAPABILITY_NOT_FOUND"
    client.close()


def test_production_catalog_can_drive_chunk_strategy_dropdown(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    app.dependency_overrides[require_admin] = lambda: None
    client = TestClient(app)

    response = client.get(
        "/api/v1/capabilities",
        params={"category": "chunk_strategy"},
    )

    assert response.status_code == 200
    options = response.json()
    assert {option["code"] for option in options} == {
        "token",
        "paragraph",
        "heading",
        "page",
        "semantic",
    }
    page = next(option for option in options if option["code"] == "page")
    assert page["requiredSourceFeatures"] == ["hasText", "hasPages"]
    assert page["configSchema"]["properties"]["maxChunkSize"]["default"] == 1024
    client.close()
