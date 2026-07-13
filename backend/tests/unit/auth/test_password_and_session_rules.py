from datetime import UTC, datetime, timedelta

from app.infrastructure.redis.login_rate_limit import RedisLoginRateLimiter
from redis.exceptions import RedisError


class FailingRedis:
    def eval(self, *_args: object) -> object:
        raise RedisError("redis unavailable")

    def delete(self, *_keys: str) -> int:
        raise RedisError("redis unavailable")


class RecordingRedis:
    def __init__(self) -> None:
        self.keys: list[str] = []

    def eval(self, _script: str, _key_count: int, key: str, *_args: object) -> list[int]:
        self.keys.append(key)
        return [1, 0]

    def delete(self, *_keys: str) -> int:
        return 1


def test_redis_failure_uses_process_local_conservative_limiter() -> None:
    limiter = RedisLoginRateLimiter(FailingRedis())
    now = datetime(2026, 7, 14, 8, 0, tzinfo=UTC)

    for attempt in range(1, 10):
        decision = limiter.record_failure("Admin", "127.0.0.1", now + timedelta(seconds=attempt))
        assert decision.limited is False

    limited = limiter.record_failure("Admin", "127.0.0.1", now + timedelta(seconds=10))

    assert limited.limited is True
    assert limited.retry_after_seconds > 0
    assert limiter.check("Admin", "127.0.0.1", now + timedelta(seconds=11)).limited is True


def test_redis_rate_limit_key_never_contains_username() -> None:
    redis_client = RecordingRedis()
    limiter = RedisLoginRateLimiter(redis_client)

    limiter.check("SensitiveAdminName", "127.0.0.1", datetime.now(UTC))

    assert len(redis_client.keys) == 1
    assert "sensitiveadminname" not in redis_client.keys[0].casefold()
    assert redis_client.keys[0].endswith(":127.0.0.1")
