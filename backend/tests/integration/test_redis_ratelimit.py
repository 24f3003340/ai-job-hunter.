"""Shared rate limiting against a REAL Redis. Needs JOBHUNTER_TEST_REDIS_URL (a throwaway instance/db:
keys under jh:rl:* are deleted). Run: pytest -m integration tests/integration/test_redis_ratelimit.py"""
import multiprocessing as mp
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest

from app.config import settings

REDIS_URL = os.environ.get("JOBHUNTER_TEST_REDIS_URL", "")
pytestmark = [pytest.mark.integration, pytest.mark.skipif(not REDIS_URL, reason="JOBHUNTER_TEST_REDIS_URL not set")]
BACKEND = Path(__file__).resolve().parents[2]


@pytest.fixture()
def rl():
    from app.ratelimit import RedisRateLimiter
    r = RedisRateLimiter(REDIS_URL, timeout=2.0)
    r.reset()
    yield r
    r.reset()


def test_sliding_window_blocks_then_releases(rl):
    assert [rl.check("k1", "3/second") for _ in range(3)] == [None, None, None]
    retry = rl.check("k1", "3/second")
    assert retry is not None and 1 <= retry <= 2
    assert rl.check("other-key", "3/second") is None  # keys are independent
    time.sleep(1.2)
    assert rl.check("k1", "3/second") is None


def test_atomic_under_thread_contention(rl):
    allowed, lock, barrier = [], threading.Lock(), threading.Barrier(40)

    def hit():
        barrier.wait()
        ok = rl.check("contended", "10/minute") is None
        with lock:
            allowed.append(ok)

    ts = [threading.Thread(target=hit) for _ in range(40)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sum(allowed) == 10  # exactly the limit, never more


def _proc_hits(url, n, q):
    from app.ratelimit import RedisRateLimiter
    r = RedisRateLimiter(url, timeout=2.0)
    q.put(sum(1 for _ in range(n) if r.check("multi-proc", "15/minute") is None))


def test_limit_is_shared_across_separate_processes(rl):
    ctx = mp.get_context("spawn")
    q = ctx.Queue()
    procs = [ctx.Process(target=_proc_hits, args=(REDIS_URL, 10, q)) for _ in range(4)]
    [p.start() for p in procs]
    [p.join(30) for p in procs]
    assert sum(q.get(timeout=5) for _ in procs) == 15  # 40 attempts across 4 processes -> exactly 15 allowed


def test_redis_down_is_detected_not_ignored(monkeypatch):
    from app.ratelimit import RedisRateLimiter
    dead = RedisRateLimiter("redis://127.0.0.1:1/0", timeout=0.2)
    with pytest.raises(Exception):
        dead.check("k", "1/minute")


# ---- real multi-worker uvicorn ----------------------------------------------------------------

def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run_workers(tmp_path, backend: str, workers: int = 3):
    port = free_port()
    env = {**os.environ, "JOBHUNTER_DATABASE_URL": f"sqlite:///{tmp_path / 'w.db'}",
           "JOBHUNTER_STORAGE_DIR": str(tmp_path / "st"), "JOBHUNTER_EMAIL_BACKEND": "outbox",
           "JOBHUNTER_RATE_LIMIT_BACKEND": backend, "JOBHUNTER_REDIS_URL": REDIS_URL,
           "JOBHUNTER_RATE_LIMIT_AUTH": "10/minute", "JOBHUNTER_RATE_LIMIT_DEFAULT": "1000/minute"}
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env, check=True,
                   capture_output=True)
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port),
                             "--workers", str(workers), "--log-level", "warning"], cwd=BACKEND, env=env)
    for _ in range(100):
        try:
            if httpx.get(f"http://127.0.0.1:{port}/health", timeout=1).status_code == 200:
                return proc, port
        except httpx.HTTPError:
            time.sleep(0.2)
    proc.kill()
    raise RuntimeError("uvicorn did not start")


def hammer_login(port, n=30):
    codes = []
    for _ in range(n):  # a fresh connection each time so the kernel spreads them over workers
        r = httpx.post(f"http://127.0.0.1:{port}/api/v1/auth/login", timeout=5,
                       json={"email": "nobody@example.com", "password": "wrong-password-1"},
                       headers={"Connection": "close"})
        codes.append(r.status_code)
    return codes


@pytest.mark.parametrize("backend,check", [("redis", "exact"), ("memory", "leaky")])
def test_limit_across_real_uvicorn_workers(tmp_path, backend, check):
    from app.ratelimit import RedisRateLimiter
    RedisRateLimiter(REDIS_URL).reset()
    proc, port = run_workers(tmp_path, backend)
    try:
        codes = hammer_login(port)
    finally:
        proc.terminate()
        proc.wait(10)
    passed = codes.count(401)
    if check == "exact":
        assert passed == 10 and codes.count(429) == 20, codes  # shared: exactly the configured limit
    else:
        # documents WHY the shared backend is needed: per-process counters let >10 through across 3 workers
        assert passed > 10, codes
