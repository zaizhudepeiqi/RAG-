import base64
from pathlib import Path

from app.bootstrap.application import create_app
from app.core.config import Settings
from app.modules.observability.ports import DependencyStatus
from app.modules.observability.service import HealthService
from starlette.testclient import TestClient


class UnhealthyDatabase:
    code = "postgresql"
    required_for_readiness = True

    def check(self) -> DependencyStatus:
        return DependencyStatus(code=self.code, status="unhealthy", message="connection failed")


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        app_env="test",
        database_url="postgresql+psycopg://test:test@127.0.0.1:5432/rag_test",
        redis_url="redis://127.0.0.1:6379/15",
        storage_root=tmp_path / "storage",
        jwt_signing_key="j" * 48,
        credential_encryption_key=base64.b64encode(b"c" * 32).decode(),
        initial_admin_password="Initial-Admin-Password-01!",
    )


def test_dependency_failure_returns_503_with_trace_id(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    app.state.dependencies.health_service = HealthService(
        version="0.1.0",
        probes=[UnhealthyDatabase()],
    )

    response = TestClient(app).get("/api/v1/health/dependencies")

    assert response.status_code == 503
    assert response.json()["status"] == "unhealthy"
    assert response.json()["traceId"] == response.headers["X-Trace-Id"]
    assert "postgresql+psycopg" not in response.text
