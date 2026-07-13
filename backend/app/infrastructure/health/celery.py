from redis import Redis
from redis.exceptions import RedisError

from app.modules.observability.ports import DependencyCode, DependencyStatus


class CeleryHealthProbe:
    code: DependencyCode = "celery"
    required_for_readiness = False

    def __init__(self, client: Redis) -> None:
        self._client = client

    def check(self) -> DependencyStatus:
        try:
            if self._client.get("celery:heartbeat") is None:
                return DependencyStatus(self.code, "degraded", "worker heartbeat not found")
            return DependencyStatus(self.code, "healthy", "worker heartbeat found")
        except RedisError:
            return DependencyStatus(self.code, "degraded", "heartbeat store unavailable")
