import hashlib
import ipaddress
import math
import threading
from collections import OrderedDict, deque
from datetime import datetime
from typing import Protocol
from uuid import uuid4

from redis.exceptions import RedisError

from app.core.logging import get_logger
from app.modules.auth.ports import RateLimitDecision

WINDOW_SECONDS = 15 * 60
MAX_FAILURES = 10
MAX_LOCAL_KEYS = 10_000

CHECK_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local cutoff = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local window = tonumber(ARGV[4])
redis.call('ZREMRANGEBYSCORE', key, '-inf', cutoff)
local count = redis.call('ZCARD', key)
if count >= limit then
  local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
  local retry = math.max(1, math.ceil(window - (now - tonumber(oldest[2]))))
  return {1, retry}
end
return {0, 0}
"""

RECORD_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local cutoff = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local window = tonumber(ARGV[4])
local member = ARGV[5]
redis.call('ZREMRANGEBYSCORE', key, '-inf', cutoff)
redis.call('ZADD', key, now, member)
redis.call('EXPIRE', key, window)
local count = redis.call('ZCARD', key)
if count >= limit then
  local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
  local retry = math.max(1, math.ceil(window - (now - tonumber(oldest[2]))))
  return {1, retry}
end
return {0, 0}
"""


class RedisClient(Protocol):
    def eval(self, script: str, numkeys: int, *keys_and_args: str) -> object: ...

    def delete(self, *names: str) -> object: ...


class RedisLoginRateLimiter:
    def __init__(self, redis_client: RedisClient) -> None:
        self._redis = redis_client
        self._local: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    def check(self, username: str, source_ip: str, now: datetime) -> RateLimitDecision:
        key = self._key(username, source_ip)
        timestamp = now.timestamp()
        try:
            result = self._redis.eval(
                CHECK_SCRIPT,
                1,
                key,
                str(timestamp),
                str(timestamp - WINDOW_SECONDS),
                str(MAX_FAILURES),
                str(WINDOW_SECONDS),
            )
            return self._parse_result(result)
        except RedisError:
            self._log_degraded()
            return self._local_check(key, timestamp)

    def record_failure(
        self,
        username: str,
        source_ip: str,
        now: datetime,
    ) -> RateLimitDecision:
        key = self._key(username, source_ip)
        timestamp = now.timestamp()
        try:
            result = self._redis.eval(
                RECORD_SCRIPT,
                1,
                key,
                str(timestamp),
                str(timestamp - WINDOW_SECONDS),
                str(MAX_FAILURES),
                str(WINDOW_SECONDS),
                str(uuid4()),
            )
            return self._parse_result(result)
        except RedisError:
            self._log_degraded()
            return self._local_record(key, timestamp)

    def clear(self, username: str, source_ip: str) -> None:
        key = self._key(username, source_ip)
        try:
            self._redis.delete(key)
        except RedisError:
            self._log_degraded()
        with self._lock:
            self._local.pop(key, None)

    @staticmethod
    def _key(username: str, source_ip: str) -> str:
        username_hash = hashlib.sha256(username.casefold().encode("utf-8")).hexdigest()
        try:
            normalized_ip = ipaddress.ip_address(source_ip).compressed
        except ValueError:
            normalized_ip = "unknown"
        return f"login-failures:{username_hash}:{normalized_ip}"

    @staticmethod
    def _parse_result(value: object) -> RateLimitDecision:
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise RedisError("unexpected rate limiter response")
        return RateLimitDecision(limited=bool(int(value[0])), retry_after_seconds=int(value[1]))

    def _local_check(self, key: str, timestamp: float) -> RateLimitDecision:
        with self._lock:
            failures = self._active_failures(key, timestamp)
            return self._decision(failures, timestamp)

    def _local_record(self, key: str, timestamp: float) -> RateLimitDecision:
        with self._lock:
            failures = self._active_failures(key, timestamp)
            if key not in self._local and len(self._local) >= MAX_LOCAL_KEYS:
                self._local.popitem(last=False)
            failures.append(timestamp)
            self._local[key] = failures
            self._local.move_to_end(key)
            return self._decision(failures, timestamp)

    def _active_failures(self, key: str, timestamp: float) -> deque[float]:
        failures = self._local.get(key, deque())
        cutoff = timestamp - WINDOW_SECONDS
        while failures and failures[0] <= cutoff:
            failures.popleft()
        if failures:
            self._local[key] = failures
            self._local.move_to_end(key)
        else:
            self._local.pop(key, None)
        return failures

    @staticmethod
    def _decision(failures: deque[float], timestamp: float) -> RateLimitDecision:
        if len(failures) < MAX_FAILURES:
            return RateLimitDecision(limited=False)
        retry_after = max(1, math.ceil(WINDOW_SECONDS - (timestamp - failures[0])))
        return RateLimitDecision(limited=True, retry_after_seconds=retry_after)

    @staticmethod
    def _log_degraded() -> None:
        get_logger().warning("login_rate_limit_dependency_degraded", dependency="redis")
