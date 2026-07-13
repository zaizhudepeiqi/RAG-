import os

from celery import Celery  # type: ignore[import-untyped]

celery_app = Celery(
    "enterprise_rag",
    broker=os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"),
    include=["app.modules.tasks.tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    timezone="UTC",
    enable_utc=True,
    task_routes={
        "app.tasks.parsing.*": {"queue": "parsing"},
        "app.tasks.indexing.*": {"queue": "indexing"},
        "app.tasks.chat.*": {"queue": "chat"},
        "app.tasks.maintenance.*": {"queue": "maintenance"},
    },
    beat_schedule={
        "dispatch-outbox": {
            "task": "app.tasks.maintenance.dispatch_outbox",
            "schedule": 5.0,
        },
        "reconcile-outbox": {
            "task": "app.tasks.maintenance.reconcile_outbox",
            "schedule": 60.0,
        },
        "worker-heartbeat": {
            "task": "app.tasks.maintenance.worker_heartbeat",
            "schedule": 15.0,
        },
    },
)
