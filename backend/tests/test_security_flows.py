import re
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.config import Settings, settings
from app.mailer import OUTBOX
from app.models import AuditEvent, AuthToken
from conftest import register
from test_applications import setup_app

P = "/api/v1"
EMAIL, PW = "a@example.com", "correct-horse-battery"


def token_from_mail(index=-1) -> str:
    return re.search(r"token=(\S+)", OUTBOX[index].body).group(1)


def reset_request(client, email=EMAIL):
    return client.post(f"{P}/auth/password-reset/request", json={"email": email})


# ---- password reset -------------------------------------------------------------------------

def test_reset_request_is_uniform_and_silent_for_unknown_email(client, auth):
    OUTBOX.clear()
    known, unknown = reset_request(client), reset_request(client, "nobody@example.com")
    assert known.status_code == unknown.status_code == 202 and known.json() == unknown.json()
    assert [m.to for m in OUTBOX] == [EMAIL]


def test_reset_flow_changes_password_and_revokes_sessions(client, auth):
    reset_request(client)
    token = token_from_mail()
    r = client.post(f"{P}/auth/password-reset/confirm", json={"token": token, "new_password": "brand-new-password-1"})
    assert r.status_code == 204
    assert client.get(f"{P}/profile", headers=auth).status_code == 401  # old session revoked
    assert client.post(f"{P}/auth/login", json={"email": EMAIL, "password": PW}).status_code == 401
    assert client.post(f"{P}/auth/login", json={"email": EMAIL, "password": "brand-new-password-1"}).status_code == 200


def test_reset_token_is_single_use(client, auth):
    reset_request(client)
    token = token_from_mail()
    body = {"token": token, "new_password": "brand-new-password-1"}
    assert client.post(f"{P}/auth/password-reset/confirm", json=body).status_code == 204
    again = client.post(f"{P}/auth/password-reset/confirm", json={**body, "new_password": "another-password-22"})
    assert again.status_code == 400


def test_reset_token_expires(client, auth, monkeypatch):
    monkeypatch.setattr(settings, "password_reset_ttl_minutes", -1)  # already expired when issued
    reset_request(client)
    r = client.post(f"{P}/auth/password-reset/confirm",
                    json={"token": token_from_mail(), "new_password": "brand-new-password-1"})
    assert r.status_code == 400
    assert client.post(f"{P}/auth/login", json={"email": EMAIL, "password": PW}).status_code == 200


def test_new_reset_request_voids_older_token(client, auth):
    reset_request(client)
    old = token_from_mail()
    reset_request(client)
    body = {"new_password": "brand-new-password-1"}
    assert client.post(f"{P}/auth/password-reset/confirm", json={"token": old, **body}).status_code == 400
    assert client.post(f"{P}/auth/password-reset/confirm", json={"token": token_from_mail(), **body}).status_code == 204


def test_reset_tokens_stored_hashed_and_garbage_rejected(client, auth, session_factory):
    reset_request(client)
    token = token_from_mail()
    with session_factory() as s:
        rows = s.scalars(select(AuthToken).where(AuthToken.purpose == "password_reset")).all()
        assert rows and all(token not in r.token_hash and len(r.token_hash) == 64 for r in rows)
    r = client.post(f"{P}/auth/password-reset/confirm", json={"token": "x" * 40, "new_password": "brand-new-password-1"})
    assert r.status_code == 400


def test_reset_requests_are_throttled_per_account(client, auth):
    OUTBOX.clear()
    for _ in range(5):
        assert reset_request(client).status_code == 202
    assert len(OUTBOX) == settings.reset_requests_per_hour


def test_reset_clears_lockout_and_audits(client, auth, session_factory):
    for _ in range(5):
        client.post(f"{P}/auth/login", json={"email": EMAIL, "password": "wrong-password-1"})
    assert client.post(f"{P}/auth/login", json={"email": EMAIL, "password": PW}).status_code == 429
    reset_request(client)
    client.post(f"{P}/auth/password-reset/confirm", json={"token": token_from_mail(), "new_password": "brand-new-password-1"})
    assert client.post(f"{P}/auth/login", json={"email": EMAIL, "password": "brand-new-password-1"}).status_code == 200
    with session_factory() as s:
        actions = {a.action for a in s.scalars(select(AuditEvent))}
    assert {"password_reset_requested", "password_reset_completed", "account_locked"} <= actions


# ---- e-mail verification --------------------------------------------------------------------

def test_registration_sends_verification_and_token_verifies_once(client):
    h = register(client)
    assert client.get(f"{P}/auth/me", headers=h).json()["email_verified"] is False
    token = token_from_mail()
    assert client.post(f"{P}/auth/verify-email", json={"token": token}).status_code == 204
    assert client.get(f"{P}/auth/me", headers=h).json()["email_verified"] is True
    assert client.post(f"{P}/auth/verify-email", json={"token": token}).status_code == 400


def test_verification_token_expires(client, monkeypatch):
    monkeypatch.setattr(settings, "email_verify_ttl_hours", -1)
    register(client)
    assert client.post(f"{P}/auth/verify-email", json={"token": token_from_mail()}).status_code == 400


def test_resend_has_cooldown_and_hourly_cap(client, monkeypatch):
    h = register(client)
    assert client.post(f"{P}/auth/resend-verification", headers=h).status_code == 429  # cooldown after signup mail
    monkeypatch.setattr(settings, "verify_resend_cooldown_seconds", 0)
    monkeypatch.setattr(settings, "verify_resends_per_hour", 3)  # signup mail counts as the first
    assert client.post(f"{P}/auth/resend-verification", headers=h).status_code == 202
    assert client.post(f"{P}/auth/resend-verification", headers=h).status_code == 202
    assert client.post(f"{P}/auth/resend-verification", headers=h).status_code == 429


def test_unverified_user_blocked_from_sensitive_actions_when_required(client, auth, session_factory, monkeypatch):
    _, app = setup_app(client, auth, session_factory)
    monkeypatch.setattr(settings, "require_verified_email", True)
    assert client.post(f"{P}/applications/{app['id']}/approve", headers=auth).status_code == 403
    client.post(f"{P}/auth/verify-email", json={"token": token_from_mail(0)})
    assert client.post(f"{P}/applications/{app['id']}/approve", headers=auth).status_code == 200


# ---- rate limiting --------------------------------------------------------------------------

def test_auth_endpoints_rate_limited(client, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_auth", "3/minute")
    codes = [client.post(f"{P}/auth/login", json={"email": "x@example.com", "password": "wrong-password-1"}).status_code
             for _ in range(5)]
    assert codes[:3] == [401] * 3 and codes[3:] == [429] * 2
    r = client.post(f"{P}/auth/password-reset/request", json={"email": "x@example.com"})
    assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1


def test_global_default_limit(client, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_default", "4/minute")
    assert [client.get("/health").status_code for _ in range(6)] == [200] * 4 + [429] * 2


def test_rate_limit_can_be_disabled_in_dev(client, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    monkeypatch.setattr(settings, "rate_limit_default", "1/minute")
    assert all(client.get("/health").status_code == 200 for _ in range(3))


# ---- configuration --------------------------------------------------------------------------

GOOD = dict(env="production", database_url="postgresql+psycopg://u:p@db/app", public_base_url="https://app.example.com",
            cors_origins=["https://app.example.com"], email_backend="smtp", smtp_host="smtp.example.com",
            require_verified_email=True, clamav_host="clamav",
            rate_limit_backend="redis", redis_url="rediss://:pw@redis.example.com:6379/0")


def test_production_config_accepts_safe_values():
    Settings(_env_file=None, **GOOD)


@pytest.mark.parametrize("override,needle", [
    ({"database_url": "sqlite:///x.db"}, "PostgreSQL"),
    ({"public_base_url": "http://app.example.com"}, "https"),
    ({"cors_origins": ["*"]}, "CORS"),
    ({"email_backend": "console"}, "EMAIL_BACKEND"),
    ({"require_verified_email": False}, "VERIFIED_EMAIL"),
    ({"rate_limit_enabled": False}, "rate limiting"),
    ({"clamav_host": ""}, "CLAMAV"),
    ({"ai_provider": "anthropic"}, "ANTHROPIC_API_KEY"),
    ({"env": "staging"}, "ENV"),
    ({"rate_limit_backend": "memory"}, "RATE_LIMIT_BACKEND"),
    ({"redis_url": ""}, "REDIS_URL"),
    ({"smtp_security": "none"}, "SMTP_SECURITY"),
    ({"rate_limit_critical_fail_mode": "open"}, "FAIL_MODE"),
])
def test_production_config_rejects_unsafe_values(override, needle):
    with pytest.raises(ValueError, match=needle):
        Settings(_env_file=None, **{**GOOD, **override})


def test_unscanned_uploads_must_be_explicitly_allowed():
    Settings(_env_file=None, **{**GOOD, "clamav_host": "", "allow_unscanned_uploads": True})


def test_single_worker_process_local_limiter_must_be_explicit():
    Settings(_env_file=None, **{**GOOD, "rate_limit_backend": "memory", "allow_process_local_rate_limit": True})
