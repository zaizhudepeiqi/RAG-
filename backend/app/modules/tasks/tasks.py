from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from celery import Celery  # type: ignore[import-untyped]

from app.bootstrap.celery_app import celery_app
from app.bootstrap.dependencies import build_application_dependencies
from app.core.config import get_settings
from app.modules.parsing.tasks import SOURCE_PARSE_TASK
from app.modules.tasks.dispatcher import OutboxDispatcher
from app.modules.tasks.ports import OperationExecutionStore
from app.modules.tasks.worker import execute_operation


class CeleryTaskPublisher:
    def __init__(self, app: Celery) -> None:
        self._app = app

    def publish(self, task_name: str, queue: str, kwargs: dict[str, str]) -> None:
        self._app.send_task(task_name, kwargs=kwargs, queue=queue)


@dataclass
class ExecutionDependencies:
    operations: OperationExecutionStore


@celery_app.task(name="app.tasks.maintenance.dispatch_outbox")
def dispatch_outbox() -> int:
    dependencies = build_application_dependencies(get_settings())
    try:
        dispatcher = OutboxDispatcher(
            dependencies.outbox_dispatch_store,
            CeleryTaskPublisher(celery_app),
            dependencies.task_dispatch_registry,
        )
        return dispatcher.dispatch_once(datetime.now(UTC))
    finally:
        dependencies.close()


@celery_app.task(name="app.tasks.maintenance.reconcile_outbox")
def reconcile_outbox() -> int:
    dependencies = build_application_dependencies(get_settings())
    try:
        return dependencies.outbox_dispatch_store.reconcile(datetime.now(UTC))
    finally:
        dependencies.close()


@celery_app.task(name="app.tasks.maintenance.worker_heartbeat")
def worker_heartbeat() -> None:
    settings = get_settings()
    dependencies = build_application_dependencies(settings)
    try:
        dependencies.redis_client.set("celery:heartbeat", datetime.now(UTC).isoformat(), ex=45)
    finally:
        dependencies.close()


@celery_app.task(name="app.tasks.maintenance.test_model_provider")
def test_model_provider(operationId: str, eventType: str, schemaVersion: str) -> None:
    dependencies = build_application_dependencies(get_settings())
    try:
        execute_operation(
            UUID(operationId),
            "model_provider_test",
            dependencies.provider_test_handler,
            ExecutionDependencies(dependencies.operation_execution_store),
        )
    finally:
        dependencies.close()


@celery_app.task(name="app.tasks.maintenance.discover_provider_models")
def discover_provider_models(operationId: str, eventType: str, schemaVersion: str) -> None:
    dependencies = build_application_dependencies(get_settings())
    try:
        execute_operation(
            UUID(operationId),
            "model_provider_discovery",
            dependencies.provider_discovery_handler,
            ExecutionDependencies(dependencies.operation_execution_store),
        )
    finally:
        dependencies.close()


@celery_app.task(name="app.tasks.maintenance.verify_model")
def verify_model(operationId: str, eventType: str, schemaVersion: str) -> None:
    dependencies = build_application_dependencies(get_settings())
    try:
        execute_operation(
            UUID(operationId),
            "model_verification",
            dependencies.model_verification_handler,
            ExecutionDependencies(dependencies.operation_execution_store),
        )
    finally:
        dependencies.close()


@celery_app.task(name="app.tasks.parsing.parse_source")
def parse_source(operationId: str, eventType: str, schemaVersion: str) -> None:
    dependencies = build_application_dependencies(get_settings())
    try:
        execute_operation(
            UUID(operationId),
            SOURCE_PARSE_TASK,
            dependencies.source_parse_handler,
            ExecutionDependencies(dependencies.operation_execution_store),
        )
    finally:
        dependencies.close()
