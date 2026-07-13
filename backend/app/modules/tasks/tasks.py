from datetime import UTC, datetime

from celery import Celery  # type: ignore[import-untyped]

from app.bootstrap.celery_app import celery_app
from app.bootstrap.dependencies import build_application_dependencies
from app.core.config import get_settings
from app.modules.tasks.dispatcher import OutboxDispatcher


class CeleryTaskPublisher:
    def __init__(self, app: Celery) -> None:
        self._app = app

    def publish(self, task_name: str, queue: str, kwargs: dict[str, str]) -> None:
        self._app.send_task(task_name, kwargs=kwargs, queue=queue)


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
