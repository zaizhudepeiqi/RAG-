from redis import Redis
from redis.exceptions import RedisError

from app.modules.observability.ports import DependencyCode, DependencyStatus


class RedisHealthProbe:
    code: DependencyCode = "redis"
    required_for_readiness = True

    def __init__(self, client: Redis) -> None:
        self._client = client

    def check(self) -> DependencyStatus:
        try:
            if self._client.ping():
                return DependencyStatus(self.code, "healthy", "available")
            return DependencyStatus(self.code, "unhealthy", "unexpected ping response")
        except RedisError:
            return DependencyStatus(self.code, "unhealthy", "redis unavailable")
