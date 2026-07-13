import shutil
import subprocess
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from app.infrastructure.database.models.tasks import OperationModel, TaskOutboxModel
from app.infrastructure.database.repositories.tasks import (
    SqlAlchemyOperationExecutionStore,
    SqlAlchemyOperationRepository,
    SqlAlchemyOutboxDispatchStore,
    SqlAlchemyOutboxRepository,
)
from app.infrastructure.database.session import create_session_factory, transaction
from app.modules.tasks.dispatcher import OutboxDispatcher
from app.modules.tasks.domain import OperationStatus
from app.modules.tasks.ports import TaskDispatchDefinition, TaskDispatchRegistry
from app.modules.tasks.service import TaskService
from app.modules.tasks.tasks import CeleryTaskPublisher
from app.modules.tasks.worker import execute_operation
from celery import Celery  # type: ignore[import-untyped]
from redis import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import Engine, select, text, update
from tests.support.task_handlers import CountingTaskHandler

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
COMPOSE_FILE = REPOSITORY_ROOT / "deploy" / "compose" / "compose.deps.yml"
COMPOSE_ENV_FILE = REPOSITORY_ROOT / "deploy" / "env" / ".env.development"


@pytest.fixture(autouse=True)
def empty_task_state(database_engine: Engine) -> Iterator[None]:
    redis_client = Redis.from_url("redis://127.0.0.1:6379/0")
    redis_client.delete("maintenance")
    with database_engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE api_idempotency_records, task_outbox, operation_items, operations CASCADE"
            )
        )
    try:
        yield
    finally:
        redis_client.delete("maintenance")
        redis_client.close()


def create_queued_operation(database_engine: Engine, now: datetime) -> UUID:
    service = TaskService(SqlAlchemyOperationRepository(), SqlAlchemyOutboxRepository())
    session_factory = create_session_factory(database_engine)
    with transaction(session_factory) as session:
        operation = service.create_operation(
            session,
            task_type="test_task",
            target_type="test_target",
            target_id=uuid4(),
            target_revision=1,
            business_key=str(uuid4()),
            event_type="test.requested",
            payload={"documentBody": "must not be published"},
            now=now,
            expires_at=now + timedelta(days=1),
        )
    return operation.id


def registry() -> TaskDispatchRegistry:
    value = TaskDispatchRegistry()
    value.register(
        TaskDispatchDefinition(
            event_type="test.requested",
            schema_version="1",
            celery_task_name="tests.tasks.execute",
            queue="maintenance",
        )
    )
    return value


def celery_for_broker(url: str) -> Celery:
    app = Celery("outbox-integration", broker=url)
    app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        task_publish_retry=False,
        broker_transport_options={
            "socket_connect_timeout": 1,
            "socket_timeout": 1,
        },
    )
    return app


def compose(*arguments: str) -> None:
    docker = shutil.which("docker")
    if docker is None:
        pytest.fail("Docker CLI is required for Redis recovery integration tests")
    subprocess.run(  # noqa: S603 - command and compose file are repository-controlled.
        [
            docker,
            "compose",
            "--env-file",
            str(COMPOSE_ENV_FILE),
            "-f",
            str(COMPOSE_FILE),
            *arguments,
        ],
        cwd=REPOSITORY_ROOT,
        check=True,
        timeout=60,
    )


def wait_for_redis() -> None:
    client = Redis.from_url("redis://127.0.0.1:6379/0")
    try:
        for _ in range(30):
            try:
                if client.ping():
                    return
            except (RedisConnectionError, OSError):
                pass
            time.sleep(1)
    finally:
        client.close()
    raise AssertionError("Redis did not recover within 30 seconds")


@pytest.mark.integration
def test_outbox_is_recoverable_after_redis_returns(database_engine: Engine) -> None:
    now = datetime.now(UTC)
    operation_id = create_queued_operation(database_engine, now)
    store = SqlAlchemyOutboxDispatchStore(create_session_factory(database_engine))
    app = celery_for_broker("redis://127.0.0.1:6379/0")
    dispatcher = OutboxDispatcher(store, CeleryTaskPublisher(app), registry())

    stopped = False
    try:
        compose("stop", "redis")
        stopped = True
        assert dispatcher.dispatch_once(now) == 0
        with create_session_factory(database_engine)() as session:
            failed = session.scalar(
                select(TaskOutboxModel).where(TaskOutboxModel.operation_id == operation_id)
            )
            assert failed is not None
            assert failed.status == "pending"
            assert failed.publish_attempts == 1
            assert failed.last_error is not None
    finally:
        if stopped:
            compose("start", "redis")
            wait_for_redis()

    assert dispatcher.dispatch_once(now + timedelta(seconds=2)) == 1
    with create_session_factory(database_engine)() as session:
        recovered = session.scalar(
            select(TaskOutboxModel).where(TaskOutboxModel.operation_id == operation_id)
        )
        assert recovered is not None
        assert recovered.status == "published"
        assert recovered.publish_attempts == 2


@pytest.mark.integration
def test_queued_operation_without_published_event_is_reconciled_after_one_minute(
    database_engine: Engine,
) -> None:
    now = datetime.now(UTC)
    operation_id = create_queued_operation(database_engine, now - timedelta(minutes=2))
    with database_engine.begin() as connection:
        connection.execute(
            update(TaskOutboxModel)
            .where(TaskOutboxModel.operation_id == operation_id)
            .values(status="publishing", next_attempt_at=now + timedelta(hours=1))
        )
    store = SqlAlchemyOutboxDispatchStore(create_session_factory(database_engine))

    assert store.reconcile(now) == 1

    with create_session_factory(database_engine)() as session:
        outbox = session.scalar(
            select(TaskOutboxModel).where(TaskOutboxModel.operation_id == operation_id)
        )
        assert outbox is not None
        assert outbox.status == "pending"
        assert outbox.next_attempt_at == now


@pytest.mark.integration
def test_unsupported_schema_is_never_automatically_reclaimed(database_engine: Engine) -> None:
    now = datetime.now(UTC)
    operation_id = create_queued_operation(database_engine, now)
    store = SqlAlchemyOutboxDispatchStore(create_session_factory(database_engine))

    assert (
        OutboxDispatcher(
            store, CeleryTaskPublisher(celery_for_broker("memory://")), TaskDispatchRegistry()
        ).dispatch_once(now)
        == 0
    )

    with create_session_factory(database_engine)() as session:
        operation = session.get(OperationModel, operation_id)
        outbox = session.scalar(
            select(TaskOutboxModel).where(TaskOutboxModel.operation_id == operation_id)
        )
        assert operation is not None
        assert operation.status == OperationStatus.FAILED.value
        assert operation.error_code == "TASK_SCHEMA_UNSUPPORTED"
        assert outbox is not None
        assert outbox.status == "failed"
        assert outbox.last_error == "TASK_SCHEMA_UNSUPPORTED"

    assert store.claim_batch(now + timedelta(days=3651), 50) == []


@pytest.mark.integration
def test_duplicate_delivery_runs_test_handler_side_effect_once(database_engine: Engine) -> None:
    operation_id = create_queued_operation(database_engine, datetime.now(UTC))
    operations = SqlAlchemyOperationExecutionStore(create_session_factory(database_engine))
    dependencies = type("Dependencies", (), {"operations": operations})()
    handler = CountingTaskHandler()

    execute_operation(operation_id, "test_task", handler, dependencies)
    execute_operation(operation_id, "test_task", handler, dependencies)

    assert handler.side_effect_count == 1
    with database_engine.connect() as connection:
        status = connection.scalar(
            select(OperationModel.status).where(OperationModel.id == operation_id)
        )
    assert status == OperationStatus.SUCCEEDED.value
