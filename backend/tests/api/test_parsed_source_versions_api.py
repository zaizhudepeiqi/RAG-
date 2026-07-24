from collections.abc import Iterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from app.bootstrap.application import create_app
from app.core.config import Settings
from app.modules.parsing.domain import ParsingReference
from redis import Redis
from sqlalchemy import Engine, text
from starlette.testclient import TestClient

pytestmark = pytest.mark.integration

INITIAL_CREDENTIAL = "Initial-Parse-Admin-Password-01!"
CURRENT_CREDENTIAL = "Current-Parse-Admin-Password-02!"


@pytest.fixture
def parse_client(
    tmp_path: Path,
    migrated_database_url: str,
    database_engine: Engine,
) -> Iterator[tuple[TestClient, Engine]]:
    with database_engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE audit_logs, task_outbox, parsed_source_versions, operations, "
                "data_sources, source_blobs, administrators CASCADE"
            )
        )
    redis_client = Redis.from_url("redis://127.0.0.1:6379/15")
    redis_client.flushdb()
    redis_client.close()
    settings = Settings(
        app_env="test",
        database_url=migrated_database_url,
        redis_url="redis://127.0.0.1:6379/15",
        storage_root=tmp_path / "storage",
        jwt_signing_key="j" * 48,
        credential_encryption_key="Y2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2M=",
        initial_admin_password=INITIAL_CREDENTIAL,
    )
    with TestClient(create_app(settings)) as client:
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


def config() -> dict[str, object]:
    return {
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


def upload(client: TestClient, name: str, content: bytes, mime_type: str) -> str:
    response = client.post(
        "/api/v1/data-sources/uploads",
        headers=csrf(client),
        files=[("files", (name, content, mime_type))],
        data={"options": "{}"},
    )
    assert response.status_code == 200, response.json()
    return response.json()["accepted"][0]["dataSource"]["id"]


def request_parse(
    client: TestClient,
    source_id: str,
    *,
    expected_revision: int = 1,
    reuse_policy: str = "reuse_if_exact",
) -> object:
    return client.post(
        f"/api/v1/data-sources/{source_id}/parse",
        headers=csrf(client),
        json={
            "expectedRevision": expected_revision,
            "reusePolicy": reuse_policy,
            "config": config(),
        },
    )


def test_parse_request_routes_text_reuses_exact_and_force_creates_new_version(
    parse_client: tuple[TestClient, Engine],
) -> None:
    client, engine = parse_client
    source_id = upload(client, "source.txt", b"parse me", "text/plain")

    first = request_parse(client, source_id)
    reused = request_parse(client, source_id)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE parsed_source_versions SET status = 'failed' WHERE version_number = 1")
        )
    retried = request_parse(client, source_id)
    forced = request_parse(client, source_id, reuse_policy="force_new")

    assert first.status_code == 202, first.json()
    first_body = first.json()
    assert first_body["reused"] is False
    assert first_body["parsedSourceVersion"]["parserCode"] == "builtin_text"
    assert first_body["parsedSourceVersion"]["configSnapshot"]["modelVersion"] == "builtin"
    assert reused.status_code == 202
    assert reused.json()["reused"] is True
    assert reused.json()["parsedSourceVersion"]["id"] == first_body["parsedSourceVersion"]["id"]
    assert retried.status_code == 202
    assert retried.json()["parsedSourceVersion"]["versionNumber"] == 2
    assert (
        retried.json()["parsedSourceVersion"]["operationId"]
        != first_body["parsedSourceVersion"]["operationId"]
    )
    assert forced.status_code == 202
    assert forced.json()["parsedSourceVersion"]["versionNumber"] == 3
    assert forced.json()["parsedSourceVersion"]["configSnapshot"]["executionIntent"] == {
        "reusePolicy": "force_new",
        "noCache": True,
    }
    with engine.connect() as connection:
        version_count = connection.scalar(text("SELECT count(*) FROM parsed_source_versions"))
        operation_count = connection.scalar(text("SELECT count(*) FROM operations"))
        outbox_count = connection.scalar(text("SELECT count(*) FROM task_outbox"))
    assert (version_count, operation_count, outbox_count) == (3, 3, 3)


def test_parse_rejects_stale_revision_and_unconfirmed_mineru_cloud(
    parse_client: tuple[TestClient, Engine],
) -> None:
    client, engine = parse_client
    text_id = upload(client, "source.txt", b"parse me", "text/plain")
    pdf_id = upload(client, "source.pdf", b"%PDF-1.7\ncontent", "application/pdf")

    stale = request_parse(client, text_id, expected_revision=2)
    unconfirmed = request_parse(client, pdf_id)

    assert stale.status_code == 409
    assert stale.json()["code"] == "REVISION_CONFLICT"
    assert unconfirmed.status_code == 409
    assert unconfirmed.json()["code"] == "MINERU_CLOUD_CONSENT_REQUIRED"
    with engine.connect() as connection:
        version_count = connection.scalar(text("SELECT count(*) FROM parsed_source_versions"))
    assert version_count == 0


def test_failed_mineru_version_resumes_original_provider_checkpoint(
    parse_client: tuple[TestClient, Engine],
) -> None:
    client, engine = parse_client
    source_id = upload(client, "source.txt", b"parse me", "text/plain")
    created = request_parse(client, source_id)
    version_id = created.json()["parsedSourceVersion"]["id"]
    original_operation_id = created.json()["parsedSourceVersion"]["operationId"]
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE parsed_source_versions
                SET parser_code = 'mineru_precision_api', status = 'failed',
                    error_code = 'MINERU_TIMEOUT', retryable = true,
                    provider_batch_id = 'batch-resume-001',
                    provider_data_id = CAST(id AS text), finished_at = now()
                WHERE id = :version_id
                """
            ),
            {"version_id": version_id},
        )
        connection.execute(
            text(
                "UPDATE operations SET status = 'failed', retryable = true, "
                "finished_at = now() WHERE id = :operation_id"
            ),
            {"operation_id": original_operation_id},
        )

    resumed = client.post(
        f"/api/v1/parsed-source-versions/{version_id}:resume-provider-query",
        headers=csrf(client),
    )

    assert resumed.status_code == 202, resumed.json()
    assert resumed.json()["targetType"] == "parsed_source_version"
    assert resumed.json()["targetId"] == version_id
    assert resumed.json()["operationId"] != original_operation_id
    with engine.connect() as connection:
        version = connection.execute(
            text(
                """
                SELECT status, error_code, retryable, provider_batch_id,
                       provider_data_id, operation_id
                FROM parsed_source_versions WHERE id = :version_id
                """
            ),
            {"version_id": version_id},
        ).one()
        event = connection.execute(
            text("SELECT event_type, payload FROM task_outbox WHERE operation_id = :operation_id"),
            {"operation_id": resumed.json()["operationId"]},
        ).one()
    assert version.status == "provider_pending"
    assert version.error_code is None
    assert version.retryable is False
    assert version.provider_batch_id == "batch-resume-001"
    assert version.provider_data_id == version_id
    assert str(version.operation_id) == resumed.json()["operationId"]
    assert event.event_type == "parsing.source.requested"
    assert event.payload == {
        "parsedSourceVersionId": version_id,
        "resumeMode": "provider_query",
    }


def test_provider_resume_rejects_missing_checkpoint_and_explicit_upstream_failure(
    parse_client: tuple[TestClient, Engine],
) -> None:
    client, engine = parse_client
    source_id = upload(client, "source.txt", b"parse me", "text/plain")
    created = request_parse(client, source_id)
    version_id = created.json()["parsedSourceVersion"]["id"]
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE parsed_source_versions
                SET parser_code = 'mineru_precision_api', status = 'failed',
                    error_code = 'MINERU_POLL_FAILED', retryable = false,
                    finished_at = now()
                WHERE id = :version_id
                """
            ),
            {"version_id": version_id},
        )

    rejected = client.post(
        f"/api/v1/parsed-source-versions/{version_id}:resume-provider-query",
        headers=csrf(client),
    )

    assert rejected.status_code == 409
    assert rejected.json()["code"] == "INVALID_STATE_TRANSITION"


def test_create_reparse_always_creates_a_new_version_and_preserves_the_original(
    parse_client: tuple[TestClient, Engine],
) -> None:
    client, engine = parse_client
    source_id = upload(client, "source.txt", b"parse me", "text/plain")
    created = request_parse(client, source_id)
    original = created.json()["parsedSourceVersion"]

    reparsed = client.post(
        f"/api/v1/parsed-source-versions/{original['id']}:create-reparse",
        headers=csrf(client),
        json={"expectedRevision": 1, "config": config()},
    )

    assert reparsed.status_code == 201, reparsed.json()
    body = reparsed.json()
    assert body["reused"] is False
    assert body["parsedSourceVersion"]["id"] != original["id"]
    assert body["parsedSourceVersion"]["versionNumber"] == 2
    assert body["parsedSourceVersion"]["configSnapshot"]["executionIntent"] == {
        "reusePolicy": "force_new",
        "noCache": True,
    }
    with engine.connect() as connection:
        original_row = connection.execute(
            text(
                "SELECT status, operation_id, config_snapshot "
                "FROM parsed_source_versions WHERE id = :version_id"
            ),
            {"version_id": original["id"]},
        ).one()
    assert original_row.status == original["status"]
    assert str(original_row.operation_id) == original["operationId"]
    assert original_row.config_snapshot == original["configSnapshot"]


def test_version_references_are_explicit_and_unreferenced_delete_is_async(
    parse_client: tuple[TestClient, Engine],
) -> None:
    client, engine = parse_client
    source_id = upload(client, "source.txt", b"parse me", "text/plain")
    created = request_parse(client, source_id)
    version_id = created.json()["parsedSourceVersion"]["id"]
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE parsed_source_versions SET status = 'cancelled' WHERE id = :version_id"),
            {"version_id": version_id},
        )

    references = client.get(f"/api/v1/parsed-source-versions/{version_id}/references")
    deleted = client.delete(
        f"/api/v1/parsed-source-versions/{version_id}",
        headers=csrf(client),
    )
    hidden = client.get(f"/api/v1/parsed-source-versions/{version_id}")

    assert references.status_code == 200
    assert references.json() == []
    assert deleted.status_code == 202, deleted.json()
    assert deleted.json()["targetType"] == "parsed_source_version"
    assert deleted.json()["targetId"] == version_id
    assert hidden.status_code == 404
    with engine.connect() as connection:
        operation = connection.execute(
            text("SELECT task_type FROM operations WHERE id = :operation_id"),
            {"operation_id": deleted.json()["operationId"]},
        ).one()
    assert operation.task_type == "parsing_cleanup"


def test_source_delete_soft_deletes_and_releases_blob_only_through_cleanup_operation(
    parse_client: tuple[TestClient, Engine],
) -> None:
    client, engine = parse_client
    source_id = upload(client, "source.txt", b"delete me", "text/plain")

    deleted = client.delete(
        f"/api/v1/data-sources/{source_id}",
        params={"expectedRevision": 1},
        headers=csrf(client),
    )
    operation = client.get(f"/api/v1/operations/{deleted.json()['operationId']}")
    cancelled = client.post(
        f"/api/v1/operations/{deleted.json()['operationId']}:cancel",
        headers=csrf(client),
    )
    hidden = client.get(f"/api/v1/data-sources/{source_id}")

    assert deleted.status_code == 202, deleted.json()
    assert deleted.json()["targetType"] == "data_source"
    assert "cancel" not in operation.json()["allowedActions"]
    assert cancelled.status_code == 409
    assert cancelled.json()["code"] == "OPERATION_NOT_CANCELLABLE"
    assert hidden.status_code == 404
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT ds.deleted_at, ds.revision, sb.reference_count, sb.purge_after
                FROM data_sources ds
                JOIN source_blobs sb ON sb.id = ds.source_blob_id
                WHERE ds.id = :source_id
                """
            ),
            {"source_id": source_id},
        ).one()
    assert row.deleted_at is not None
    assert row.revision == 2
    assert row.reference_count == 0
    assert row.purge_after is not None


def test_delete_returns_reference_details_instead_of_hiding_the_action(
    parse_client: tuple[TestClient, Engine],
) -> None:
    client, _engine = parse_client
    source_id = upload(client, "source.txt", b"referenced", "text/plain")
    reference = ParsingReference(
        knowledge_base_id=uuid4(),
        knowledge_base_name="客服知识库",
        config_revision_id=uuid4(),
        active=True,
    )
    client.app.state.dependencies.data_source_service._references = StaticReferences(reference)

    response = client.delete(
        f"/api/v1/data-sources/{source_id}",
        params={"expectedRevision": 1},
        headers=csrf(client),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "SOURCE_IN_USE"
    assert response.json()["details"]["references"] == [
        {
            "type": "knowledge_base_config_revision",
            "id": str(reference.config_revision_id),
            "name": "客服知识库",
        }
    ]


class StaticReferences:
    def __init__(self, reference: ParsingReference) -> None:
        self._reference = reference

    def for_data_source(
        self,
        _session: object,
        _data_source_id: UUID,
    ) -> tuple[ParsingReference, ...]:
        return (self._reference,)

    def for_parsed_version(
        self,
        _session: object,
        _parsed_source_version_id: UUID,
    ) -> tuple[ParsingReference, ...]:
        return (self._reference,)
