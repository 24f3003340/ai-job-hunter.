"""Sliding-window rate limiting with a shared (Redis) backend and an in-process fallback.

* `memory`: per process. Fine for ONE worker; N workers would allow N x the limit.
* `redis`: one atomic Lua script per check (ZSET sliding window, time taken from the Redis server so workers/hosts
  with skewed clocks agree). All workers share the same counters.

Failure policy (Redis unreachable): a limit is never silently skipped.
* critical scopes (auth, upload, generation): "closed" (default) answers 503, or "local" enforces per process;
* other scopes enforce per process.
A short circuit-breaker avoids paying the Redis timeout on every request during an outage.
"""
import logging
import threading
import time
import uuid
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, Request, status

from .config import secret, settings

log = logging.getLogger(__name__)

_UNITS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}
PREFIX = "jh:rl:"

_LUA = """
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local window = tonumber(ARGV[1]) * 1000
local limit = tonumber(ARGV[2])
redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, now - window)
if redis.call('ZCARD', KEYS[1]) >= limit then
  local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
  return math.max(1, math.ceil((tonumber(oldest[2]) + window - now) / 1000))
end
redis.call('ZADD', KEYS[1], now, ARGV[3])
redis.call('PEXPIRE', KEYS[1], window + 1000)
return 0
"""


def parse_limit(spec: str) -> tuple[int, int]:
    count, _, unit = spec.partition("/")
    return int(count), _UNITS[unit.strip()]


class RateLimiter:
    """In-process limiter (also the fallback for the Redis backend)."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()

    def check(self, key: str, spec: str) -> int | None:
        """Record a hit. Returns None if allowed, else seconds until the window frees up."""
        limit, window = parse_limit(spec)
        now = time.monotonic()
        with self._lock:
            q = self._hits[f"{key}|{spec}"]
            while q and q[0] <= now - window:
                q.popleft()
            if len(q) >= limit:
                return max(1, int(q[0] + window - now) + 1)
            q.append(now)
            return None


class RedisRateLimiter:
    def __init__(self, url: str, timeout: float | None = None):
        import redis  # imported lazily so the memory backend has no hard dependency at import time

        t = timeout if timeout is not None else settings.redis_timeout_seconds
        self._r = redis.Redis.from_url(url, socket_timeout=t, socket_connect_timeout=t, decode_responses=True)
        self._script = self._r.register_script(_LUA)

    def check(self, key: str, spec: str) -> int | None:
        limit, window = parse_limit(spec)
        redis_key = f"{PREFIX}{key}|{spec}"
        retry = int(self._script(keys=[redis_key], args=[window, limit, uuid.uuid4().hex]))
        return retry or None

    def ping(self) -> bool:
        return bool(self._r.ping())

    def reset(self) -> None:
        for k in self._r.scan_iter(f"{PREFIX}*"):
            self._r.delete(k)


limiter = RateLimiter()  # in-process instance (also used as the Redis fallback)

_redis_lock = threading.Lock()
_redis_cache: dict[str, RedisRateLimiter] = {}
_breaker_until = 0.0
STATS = {"degraded": 0}
_last_log = 0.0


def redis_limiter() -> RedisRateLimiter:
    url = secret(settings.redis_url)
    with _redis_lock:
        if url not in _redis_cache:
            _redis_cache[url] = RedisRateLimiter(url)
        return _redis_cache[url]


def _redis_failed(exc: Exception) -> None:
    global _breaker_until, _last_log
    STATS["degraded"] += 1
    _breaker_until = time.monotonic() + 5.0
    if time.monotonic() - _last_log > 5.0:  # don't flood logs during an outage
        _last_log = time.monotonic()
        log.error("rate-limit backend unavailable (%s); enforcing %s", type(exc).__name__,
                  "fail-closed for critical scopes, per-process otherwise")


def client_ip(request: Request) -> str:
    if settings.trust_proxy_headers:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check(key: str, spec: str, critical: bool) -> int | None:
    """Returns retry-after seconds if limited, None if allowed; raises 503 when failing closed."""
    if settings.rate_limit_backend != "redis":
        return limiter.check(key, spec)
    if time.monotonic() >= _breaker_until:
        try:
            return redis_limiter().check(key, spec)
        except Exception as exc:  # redis.RedisError, OSError, bad URL...
            _redis_failed(exc)
    if critical and settings.rate_limit_critical_fail_mode == "closed":
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Service temporarily unavailable",
                            headers={"Retry-After": "5"})
    return limiter.check(key, spec)  # degraded: still enforced, just per process


def _enforce(key: str, spec: str, critical: bool = False) -> None:
    if not settings.rate_limit_enabled:
        return
    retry = _check(key, spec, critical)
    if retry is not None:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Rate limit exceeded",
                            headers={"Retry-After": str(retry)})


def limit_ip(scope: str, spec_attr: str, critical: bool = False):
    """Dependency: limit by client IP. `spec_attr` names a Settings field (read at call time)."""
    def dep(request: Request) -> None:
        _enforce(f"ip:{client_ip(request)}:{scope}", getattr(settings, spec_attr), critical)
    return Depends(dep)


def limit_user(scope: str, spec_attr: str, critical: bool = True):
    """Dependency: limit by authenticated user."""
    from .deps import current_user  # local import: deps imports this module's siblings

    def dep(request: Request, user=Depends(current_user)) -> None:
        _enforce(f"user:{user.id}:{scope}", getattr(settings, spec_attr), critical)
    return Depends(dep)


def backend_status() -> dict:
    """For /health/ready: never includes URLs or credentials."""
    if settings.rate_limit_backend != "redis":
        return {"backend": "memory", "ok": True, "note": "per-process; not safe for multiple workers"}
    try:
        return {"backend": "redis", "ok": redis_limiter().ping(), "degraded_events": STATS["degraded"]}
    except Exception as exc:
        return {"backend": "redis", "ok": False, "error": type(exc).__name__, "degraded_events": STATS["degraded"]}
