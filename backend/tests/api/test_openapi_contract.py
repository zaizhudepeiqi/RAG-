import base64
import json
from pathlib import Path

from app.bootstrap.application import create_app
from app.core.config import Settings

EXPECTED_OPERATIONS = {
    ("post", "/api/v1/auth/login", "authLogin"),
    ("post", "/api/v1/auth/logout", "authLogout"),
    ("get", "/api/v1/auth/me", "authMe"),
    ("post", "/api/v1/auth/change-password", "authChangePassword"),
    ("get", "/api/v1/health/live", "healthLive"),
    ("get", "/api/v1/health/ready", "healthReady"),
    ("get", "/api/v1/health/dependencies", "healthDependencies"),
    ("get", "/api/v1/capabilities", "capabilitiesList"),
    (
        "get",
        "/api/v1/capabilities/{code}/versions/{version}",
        "capabilitiesGetVersion",
    ),
    ("get", "/api/v1/knowledge-bases", "knowledgeBasesList"),
    ("post", "/api/v1/knowledge-bases", "knowledgeBasesCreate"),
    (
        "get",
        "/api/v1/knowledge-bases/{knowledgeBaseId}",
        "knowledgeBasesGet",
    ),
    (
        "patch",
        "/api/v1/knowledge-bases/{knowledgeBaseId}/metadata",
        "knowledgeBasesUpdateMetadata",
    ),
    (
        "post",
        "/api/v1/knowledge-bases/{knowledgeBaseId}:enable",
        "knowledgeBasesEnable",
    ),
    (
        "post",
        "/api/v1/knowledge-bases/{knowledgeBaseId}:disable",
        "knowledgeBasesDisable",
    ),
    (
        "delete",
        "/api/v1/knowledge-bases/{knowledgeBaseId}",
        "knowledgeBasesDelete",
    ),
    ("get", "/api/v1/operations", "operationsList"),
    ("get", "/api/v1/operations/{operationId}", "operationsGet"),
    ("post", "/api/v1/operations/{operationId}:cancel", "operationsCancel"),
    ("post", "/api/v1/operations/{operationId}:retry", "operationsRetry"),
    ("get", "/api/v1/model-providers", "modelProvidersList"),
    ("post", "/api/v1/model-providers", "modelProvidersCreate"),
    ("get", "/api/v1/model-providers/{providerId}", "modelProvidersGet"),
    ("patch", "/api/v1/model-providers/{providerId}", "modelProvidersUpdate"),
    ("delete", "/api/v1/model-providers/{providerId}", "modelProvidersDelete"),
    ("post", "/api/v1/model-providers/{providerId}:test", "modelProvidersTest"),
    (
        "post",
        "/api/v1/model-providers/{providerId}:discover-models",
        "modelProvidersDiscover",
    ),
    (
        "get",
        "/api/v1/model-providers/{providerId}/discovered-models",
        "modelProvidersDiscoveredModelsList",
    ),
    ("get", "/api/v1/models", "modelsList"),
    ("post", "/api/v1/models", "modelsCreate"),
    ("get", "/api/v1/models/{modelId}", "modelsGet"),
    ("patch", "/api/v1/models/{modelId}", "modelsUpdate"),
    ("post", "/api/v1/models/{modelId}:verify", "modelsVerify"),
    ("post", "/api/v1/models/{modelId}:enable", "modelsEnable"),
    ("post", "/api/v1/models/{modelId}:disable", "modelsDisable"),
    ("get", "/api/v1/models/{modelId}/references", "modelsReferences"),
    ("delete", "/api/v1/models/{modelId}", "modelsDelete"),
    ("get", "/api/v1/settings/mineru", "mineruSettingsGet"),
    ("patch", "/api/v1/settings/mineru", "mineruSettingsUpdate"),
    ("post", "/api/v1/settings/mineru:test", "mineruSettingsTest"),
    ("get", "/api/v1/data-sources", "dataSourcesList"),
    ("post", "/api/v1/data-sources/uploads", "dataSourcesUpload"),
    ("get", "/api/v1/data-sources/{dataSourceId}", "dataSourcesGet"),
    ("patch", "/api/v1/data-sources/{dataSourceId}", "dataSourcesUpdate"),
    ("delete", "/api/v1/data-sources/{dataSourceId}", "dataSourcesDelete"),
    ("post", "/api/v1/data-sources/{dataSourceId}/parse", "dataSourcesParse"),
    (
        "get",
        "/api/v1/data-sources/{dataSourceId}/original",
        "dataSourcesOriginal",
    ),
    (
        "get",
        "/api/v1/data-sources/{dataSourceId}/references",
        "dataSourcesReferences",
    ),
    (
        "get",
        "/api/v1/parsed-source-versions/{parsedSourceVersionId}",
        "parsedSourceVersionsGet",
    ),
    (
        "post",
        "/api/v1/parsed-source-versions/{parsedSourceVersionId}:resume-provider-query",
        "parsedSourceVersionsResumeProviderQuery",
    ),
    (
        "post",
        "/api/v1/parsed-source-versions/{parsedSourceVersionId}:create-reparse",
        "parsedSourceVersionsCreateReparse",
    ),
    (
        "get",
        "/api/v1/parsed-source-versions/{parsedSourceVersionId}/markdown",
        "parsedSourceVersionsMarkdown",
    ),
    (
        "get",
        "/api/v1/parsed-source-versions/{parsedSourceVersionId}/blocks",
        "parsedSourceVersionsBlocks",
    ),
    (
        "get",
        "/api/v1/parsed-source-versions/{parsedSourceVersionId}/assets",
        "parsedSourceVersionsAssets",
    ),
    (
        "get",
        "/api/v1/parsed-source-versions/{parsedSourceVersionId}/assets/{assetId}",
        "parsedSourceVersionsAssetContent",
    ),
    (
        "get",
        "/api/v1/parsed-source-versions/{parsedSourceVersionId}/artifacts",
        "parsedSourceVersionsArtifacts",
    ),
    (
        "get",
        "/api/v1/parsed-source-versions/{parsedSourceVersionId}/references",
        "parsedSourceVersionsReferences",
    ),
    (
        "delete",
        "/api/v1/parsed-source-versions/{parsedSourceVersionId}",
        "parsedSourceVersionsDelete",
    ),
}


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        app_env="test",
        database_url="postgresql+psycopg://openapi-user:openapi-password@127.0.0.1/openapi",
        redis_url="redis://127.0.0.1:6379/15",
        storage_root=tmp_path / "openapi-storage-sentinel",
        jwt_signing_key="openapi-test-only-jwt-signing-key",
        credential_encryption_key=base64.b64encode(b"openapi-test-credential-key-0001").decode(),
        initial_admin_password="OpenAPI-Test-Only-Password-03!",
    )


def test_openapi_operations_are_explicit_and_stable(tmp_path: Path) -> None:
    schema = create_app(_settings(tmp_path)).openapi()
    actual = {
        (method, path, operation["operationId"])
        for path, path_item in schema["paths"].items()
        for method, operation in path_item.items()
        if method in {"get", "post", "put", "patch", "delete"}
    }

    assert actual == EXPECTED_OPERATIONS


def test_openapi_schema_does_not_expose_configuration_secrets(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    rendered = json.dumps(create_app(settings).openapi(), ensure_ascii=False)
    forbidden = {
        "INITIAL_ADMIN_PASSWORD",
        "JWT_SIGNING_KEY",
        "CREDENTIAL_ENCRYPTION_KEY",
        "DATABASE_URL",
        settings.database_url,
        str(settings.storage_root),
        settings.jwt_signing_key.get_secret_value(),
        settings.credential_encryption_key.get_secret_value(),
        settings.initial_admin_password.get_secret_value(),
    }

    assert not [value for value in forbidden if value in rendered]
