from datetime import datetime

from app.modules.tasks.ports import (
    OutboxDispatchStore,
    TaskDispatchRegistry,
    TaskPublisher,
    TaskSchemaUnsupportedError,
)


class OutboxDispatcher:
    def __init__(
        self,
        outbox: OutboxDispatchStore,
        publisher: TaskPublisher,
        registry: TaskDispatchRegistry,
    ) -> None:
        self._outbox = outbox
        self._publisher = publisher
        self._registry = registry

    def dispatch_once(self, now: datetime) -> int:
        dispatched = 0
        for event in self._outbox.claim_batch(now, 50):
            try:
                definition = self._registry.resolve(event.event_type, event.schema_version)
            except TaskSchemaUnsupportedError:
                self._outbox.mark_schema_failed(event, now)
                continue
            try:
                self._publisher.publish(
                    definition.celery_task_name,
                    definition.queue,
                    {
                        "operationId": str(event.operation_id),
                        "eventType": event.event_type,
                        "schemaVersion": event.schema_version,
                    },
                )
            except Exception as error:
                backoff = min(300, 2**event.publish_attempts)
                self._outbox.mark_retry(event.id, backoff, type(error).__name__, now)
                continue
            self._outbox.mark_published(event.id, now)
            dispatched += 1
        return dispatched

    def reconcile(self, now: datetime) -> int:
        return self._outbox.reconcile(now)
