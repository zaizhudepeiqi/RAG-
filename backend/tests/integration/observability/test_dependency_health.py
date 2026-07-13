from pathlib import Path

import pytest
from app.bootstrap.dependencies import build_application_dependencies
from app.core.config import Settings


@pytest.mark.integration
def test_real_foundation_dependencies_report_without_sensitive_configuration(
    tmp_path: Path,
    migrated_database_url: str,
) -> None:
    settings = Settings(
        app_env="test",
        database_url=migrated_database_url,
        redis_url="redis://127.0.0.1:6379/15",
        chroma_host="127.0.0.1",
        chroma_port=8000,
        storage_root=tmp_path / "storage",
        jwt_signing_key="j" * 48,
        credential_encryption_key="Y2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2M=",
        initial_admin_password="Initial-Admin-Password-01!",
    )
    dependencies = build_application_dependencies(settings)
    try:
        response = dependencies.health_service.dependencies()
        statuses = {item.code: item.status for item in response.dependencies}

        assert statuses["postgresql"] == "healthy"
        assert statuses["redis"] == "healthy"
        assert statuses["chroma"] == "healthy"
        assert statuses["storage"] == "healthy"
        assert statuses["mineru"] == "not_configured"
        assert statuses["models"] == "not_configured"
        rendered = response.model_dump_json()
        assert "local-dev-only" not in rendered
        assert str(tmp_path) not in rendered
    finally:
        dependencies.close()
