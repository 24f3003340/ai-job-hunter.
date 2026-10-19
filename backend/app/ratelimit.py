"""Sliding-window rate limiter.

In-process and per-worker: adequate for a single-instance deployment. Behind multiple
workers/instances, swap `RateLimiter` for a Redis-backed implementation with the same interface.
"""
import threading
import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, Request, status

from .config import settings

_UNITS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}


def parse_limit(spec: str) -> tuple[int, int]:
    count, _, unit = spec.partition("/")
    return int(count), _UNITS[unit.strip()]


class RateLimiter:
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


limiter = RateLimiter()


def client_ip(request: Request) -> str:
    if settings.trust_proxy_headers:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _enforce(key: str, spec: str) -> None:
    if not settings.rate_limit_enabled:
        return
    retry = limiter.check(key, spec)
    if retry is not None:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Rate limit exceeded",
                            headers={"Retry-After": str(retry)})


def limit_ip(scope: str, spec_attr: str):
    """Dependency: limit by client IP. `spec_attr` names a Settings field (read at call time)."""
    def dep(request: Request) -> None:
        _enforce(f"ip:{client_ip(request)}:{scope}", getattr(settings, spec_attr))
    return Depends(dep)


def limit_user(scope: str, spec_attr: str):
    """Dependency: limit by authenticated user (falls back to IP if unauthenticated)."""
    from .deps import current_user  # local import: deps imports this module's siblings

    def dep(request: Request, user=Depends(current_user)) -> None:
        _enforce(f"user:{user.id}:{scope}", getattr(settings, spec_attr))
    return Depends(dep)
