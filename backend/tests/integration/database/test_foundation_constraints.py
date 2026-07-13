from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import IntegrityError


def business_key() -> str:
    return uuid4().hex * 2


def insert_operation(
    connection: Connection,
    *,
    operation_id: UUID,
    idempotency_key: str,
    status: str = "queued",
    progress_current: int = 0,
) -> None:
    connection.execute(
        text(
            """
            INSERT INTO operations (
                id, task_type, target_type, target_id, status,
                progress_current, business_idempotency_key, expires_at
            )
            VALUES (
                :id, 'test_task', 'test_target', :target_id, :status,
                :progress_current, :business_key, :expires_at
            )
            """
        ),
        {
            "id": operation_id,
            "target_id": uuid4(),
            "status": status,
            "progress_current": progress_current,
            "business_key": idempotency_key,
            "expires_at": datetime.now(UTC) + timedelta(days=90),
        },
    )


@pytest.mark.integration
def test_pg_trgm_extension_is_installed(database_engine: Engine) -> None:
    with database_engine.connect() as connection:
        installed = connection.scalar(
            text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm')")
        )

    assert installed is True


@pytest.mark.integration
def test_administrator_username_is_unique_case_insensitively(database_engine: Engine) -> None:
    with pytest.raises(IntegrityError):
        with database_engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO administrators (id, username, password_hash)
                    VALUES (:id, 'Admin', 'hash')
                    """
                ),
                {"id": uuid4()},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO administrators (id, username, password_hash)
                    VALUES (:id, 'admin', 'hash')
                    """
                ),
                {"id": uuid4()},
            )


@pytest.mark.integration
def test_operation_business_idempotency_key_is_globally_unique(database_engine: Engine) -> None:
    idempotency_key = business_key()
    with pytest.raises(IntegrityError):
        with database_engine.begin() as connection:
            insert_operation(connection, operation_id=uuid4(), idempotency_key=idempotency_key)
            insert_operation(connection, operation_id=uuid4(), idempotency_key=idempotency_key)


@pytest.mark.integration
def test_operation_rejects_unknown_status(database_engine: Engine) -> None:
    with pytest.raises(IntegrityError):
        with database_engine.begin() as connection:
            insert_operation(
                connection,
                operation_id=uuid4(),
                idempotency_key=business_key(),
                status="unknown",
            )


@pytest.mark.integration
def test_operation_rejects_negative_progress(database_engine: Engine) -> None:
    with pytest.raises(IntegrityError):
        with database_engine.begin() as connection:
            insert_operation(
                connection,
                operation_id=uuid4(),
                idempotency_key=business_key(),
                progress_current=-1,
            )


@pytest.mark.integration
def test_outbox_event_is_unique_per_operation(database_engine: Engine) -> None:
    operation_id = uuid4()
    with pytest.raises(IntegrityError):
        with database_engine.begin() as connection:
            insert_operation(
                connection,
                operation_id=operation_id,
                idempotency_key=business_key(),
            )
            parameters = {
                "operation_id": operation_id,
                "event_type": "test.requested",
            }
            connection.execute(
                text(
                    """
                    INSERT INTO task_outbox (
                        id, operation_id, event_type, schema_version, payload
                    )
                    VALUES (:id, :operation_id, :event_type, '1', '{}'::jsonb)
                    """
                ),
                {"id": uuid4(), **parameters},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO task_outbox (
                        id, operation_id, event_type, schema_version, payload
                    )
                    VALUES (:id, :operation_id, :event_type, '1', '{}'::jsonb)
                    """
                ),
                {"id": uuid4(), **parameters},
            )
