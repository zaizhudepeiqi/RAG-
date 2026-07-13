import base64
import json
import os
from collections.abc import Iterator
from uuid import uuid4

import pytest
from app.bootstrap.celery_app import celery_app
from app.modules.tasks.tasks import CeleryTaskPublisher
from redis import Redis


@pytest.fixture
def redis_client() -> Iterator[Redis]:
    client = Redis.from_url(os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"))
    client.delete("parsing")
    try:
        yield client
    finally:
        client.delete("parsing")
        client.close()


@pytest.mark.integration
def test_celery_publisher_writes_json_message_to_redis(redis_client: Redis) -> None:
    operation_id = uuid4()
    kwargs = {
        "operationId": str(operation_id),
        "eventType": "source.parse",
        "schemaVersion": "1",
    }

    CeleryTaskPublisher(celery_app).publish(
        "app.tasks.parsing.source",
        "parsing",
        kwargs,
    )

    queued = redis_client.blpop("parsing", timeout=5)
    assert queued is not None
    envelope = json.loads(queued[1])
    assert envelope["content-type"] == "application/json"
    body = json.loads(base64.b64decode(envelope["body"]))
    assert body[1] == kwargs
