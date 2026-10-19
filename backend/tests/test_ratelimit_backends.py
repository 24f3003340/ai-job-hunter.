"""Rate-limit failure policy with a broken Redis (deterministic; no Redis server needed)."""
import pytest
import redis

from app import ratelimit
from app.config import settings

P = "/api/v1"


class BrokenRedis:
    calls = 0

    def check(self, key, spec):
        BrokenRedis.calls += 1
        raise redis.ConnectionError("down")

    def ping(self):
        raise redis.ConnectionError("down")


@pytest.fixture()
def broken(monkeypatch):
    BrokenRedis.calls = 0
    monkeypatch.setattr(settings, "rate_limit_backend", "redis")
    monkeypatch.setattr(settings, "redis_url", "redis://127.0.0.1:1/0")
    monkeypatch.setattr(ratelimit, "redis_limiter", lambda: BrokenRedis())
    monkeypatch.setattr(ratelimit, "_breaker_until", 0.0)
    ratelimit.STATS["degraded"] = 0


def login(client):
    return client.post(f"{P}/auth/login", json={"email": "x@example.com", "password": "wrong-password-1"})


def test_critical_scope_fails_closed_when_backend_is_down(client, broken):
    r = login(client)
    assert r.status_code == 503 and r.headers["retry-after"] == "5"  # NOT silently allowed through
    assert ratelimit.STATS["degraded"] >= 1


def test_critical_scope_can_fall_back_to_local_enforcement(client, broken, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_critical_fail_mode", "local")
    monkeypatch.setattr(settings, "rate_limit_auth", "2/minute")
    assert [login(client).status_code for _ in range(4)] == [401, 401, 429, 429]  # still limited


def test_global_scope_degrades_to_per_process_limit(client, broken, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_default", "3/minute")
    assert [client.get("/health").status_code for _ in range(5)] == [200, 200, 200, 429, 429]


def test_circuit_breaker_avoids_hammering_a_dead_backend(client, broken, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_critical_fail_mode", "local")
    for _ in range(5):
        login(client)
    assert BrokenRedis.calls <= 2  # first failures trip the breaker; later requests skip Redis


def test_rate_limit_disabled_flag_still_respected(client, broken, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    assert login(client).status_code == 401


def test_readiness_reports_degraded_limiter_without_leaking_urls(client, broken):
    r = client.get("/health/ready")
    assert r.status_code == 503 and r.json()["rate_limit"]["ok"] is False
    assert "127.0.0.1" not in r.text and "redis://" not in r.text


def test_readiness_ok_in_default_dev_config(client):
    r = client.get("/health/ready")
    assert r.status_code == 200 and r.json()["rate_limit"]["backend"] == "memory"
    assert r.json()["malware_scanner"]["configured"] is False  # reported honestly


def test_unscanned_uploads_fail_closed_in_production_without_override(client, auth, monkeypatch):
    from helpers import make_pdf, upload
    monkeypatch.setattr(settings, "env", "production")
    monkeypatch.setattr(settings, "allow_unscanned_uploads", False)
    assert upload(client, auth, make_pdf(), "cv.pdf").status_code == 503
    monkeypatch.setattr(settings, "allow_unscanned_uploads", True)  # the documented, explicit override
    r = upload(client, auth, make_pdf(), "cv.pdf")
    assert r.status_code == 201 and r.json()["scan_status"] == "not_configured"


def test_scanner_outage_in_production_refuses_even_with_override(client, auth, monkeypatch):
    from helpers import make_pdf, upload
    monkeypatch.setattr(settings, "env", "production")
    monkeypatch.setattr(settings, "allow_unscanned_uploads", True)
    monkeypatch.setattr(settings, "clamav_host", "127.0.0.1")
    monkeypatch.setattr(settings, "clamav_port", 1)
    assert upload(client, auth, make_pdf(), "cv.pdf").status_code == 503
