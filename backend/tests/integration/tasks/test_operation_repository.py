from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from app.infrastructure.database.models.tasks import OperationModel, TaskOutboxModel
from app.infrastructure.database.repositories.tasks import (
    SqlAlchemyOperationRepository,
    SqlAlchemyOutboxRepository,
)
from app.infrastructure.database.session import create_session_factory, transaction
from app.modules.tasks.domain import Operation
from app.modules.tasks.service import TaskService
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session


class RacingOperationRepository(SqlAlchemyOperationRepository):
    def __init__(self, barrier: Barrier) -> None:
        self._barrier = barrier

    def find_by_business_key(self, session: Session, key: str) -> Operation | None:
        existing = super().find_by_business_key(session, key)
        if existing is None:
            self._barrier.wait(timeout=10)
        return existing


@pytest.fixture(autouse=True)
def empty_task_tables(database_engine: Engine) -> None:
    with database_engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE api_idempotency_records, task_outbox, operation_items, operations CASCADE"
            )
        )


@pytest.mark.integration
def test_same_business_key_creates_one_operation_and_one_outbox(database_engine: Engine) -> None:
    session_factory = create_session_factory(database_engine)
    service = TaskService(SqlAlchemyOperationRepository(), SqlAlchemyOutboxRepository())
    now = datetime.now(UTC)

    with transaction(session_factory) as session:
        first = service.create_operation(
            session,
            task_type="test_task",
            target_type="test_target",
            target_id=uuid4(),
            target_revision=None,
            business_key="same-command",
            event_type="test.requested",
            payload={"revision": 1},
            now=now,
            expires_at=now + timedelta(days=90),
        )
        second = service.create_operation(
            session,
            task_type="test_task",
            target_type="test_target",
            target_id=uuid4(),
            target_revision=None,
            business_key="same-command",
            event_type="test.requested",
            payload={"revision": 1},
            now=now,
            expires_at=now + timedelta(days=90),
        )

    with database_engine.connect() as connection:
        operation_count = connection.scalar(select(func.count()).select_from(OperationModel))
        outbox_count = connection.scalar(select(func.count()).select_from(TaskOutboxModel))
    assert first.id == second.id
    assert operation_count == 1
    assert outbox_count == 1


@pytest.mark.integration
def test_concurrent_same_business_key_returns_one_operation_and_one_outbox(
    database_engine: Engine,
) -> None:
    session_factory = create_session_factory(database_engine)
    service = TaskService(
        RacingOperationRepository(Barrier(2)),
        SqlAlchemyOutboxRepository(),
    )
    now = datetime.now(UTC)
    target_id = uuid4()

    def create() -> object:
        with transaction(session_factory) as session:
            return service.create_operation(
                session,
                task_type="test_task",
                target_type="test_target",
                target_id=target_id,
                target_revision=None,
                business_key="concurrent-command",
                event_type="test.requested",
                payload={"revision": 1},
                now=now,
                expires_at=now + timedelta(days=90),
            ).id

    with ThreadPoolExecutor(max_workers=2) as executor:
        operation_ids = list(executor.map(lambda _: create(), range(2)))

    with database_engine.connect() as connection:
        operation_count = connection.scalar(select(func.count()).select_from(OperationModel))
        outbox_count = connection.scalar(select(func.count()).select_from(TaskOutboxModel))
    assert operation_ids[0] == operation_ids[1]
    assert operation_count == 1
    assert outbox_count == 1
