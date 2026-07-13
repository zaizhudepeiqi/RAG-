from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.infrastructure.database.repositories.tasks import SqlAlchemyAdminIdempotencyRepository
from app.infrastructure.database.session import create_session_factory, transaction
from app.modules.tasks.errors import IdempotencyKeyReusedError
from app.modules.tasks.idempotency import AdminIdempotencyService
from sqlalchemy import Engine, text


@pytest.mark.integration
def test_admin_idempotency_reuses_same_request_and_rejects_different_request(
    database_engine: Engine,
) -> None:
    administrator_id = uuid4()
    operation_id = uuid4()
    now = datetime.now(UTC)
    with database_engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE api_idempotency_records, task_outbox, operations, administrators CASCADE"
            )
        )
        connection.execute(
            text(
                "INSERT INTO administrators (id, username, password_hash) "
                "VALUES (:id, 'idempotency-admin', 'test-hash')"
            ),
            {"id": administrator_id},
        )
        connection.execute(
            text(
                """
                INSERT INTO operations (
                    id, task_type, target_type, target_id,
                    business_idempotency_key, queued_at, created_at, expires_at
                ) VALUES (
                    :id, 'test_task', 'test_target', :target_id,
                    :business_key, :now, :now, :expires_at
                )
                """
            ),
            {
                "id": operation_id,
                "target_id": uuid4(),
                "business_key": uuid4().hex * 2,
                "now": now,
                "expires_at": now + timedelta(days=90),
            },
        )
    service = AdminIdempotencyService(SqlAlchemyAdminIdempotencyRepository())
    session_factory = create_session_factory(database_engine)

    with transaction(session_factory) as session:
        first = service.reserve(
            session,
            administrator_id=administrator_id,
            endpoint_code="operation.retry",
            idempotency_key="idempotency-key-0001",
            request_body={"operationId": str(operation_id)},
            operation_id=operation_id,
            now=datetime.now(UTC),
        )
        repeated = service.reserve(
            session,
            administrator_id=administrator_id,
            endpoint_code="operation.retry",
            idempotency_key="idempotency-key-0001",
            request_body={"operationId": str(operation_id)},
            operation_id=operation_id,
            now=datetime.now(UTC),
        )
        assert repeated.id == first.id

        with pytest.raises(IdempotencyKeyReusedError):
            service.reserve(
                session,
                administrator_id=administrator_id,
                endpoint_code="operation.retry",
                idempotency_key="idempotency-key-0001",
                request_body={"operationId": str(uuid4())},
                operation_id=uuid4(),
                now=datetime.now(UTC),
            )

    with database_engine.connect() as connection:
        stored_key = connection.scalar(
            text("SELECT idempotency_key_hash FROM api_idempotency_records")
        )
    assert stored_key != "idempotency-key-0001"
    assert len(stored_key) == 64
