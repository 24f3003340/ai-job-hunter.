"""Mailer behaviour with smtplib mocked. Real-protocol tests live in tests/integration/test_smtp.py."""
import logging
import re
import smtplib
import ssl

import pytest

from app import mailer
from app.config import settings
from app.mailer import MailError, OUTBOX, deliver, send_email
from conftest import register

P = "/api/v1"


class FakeSMTP:
    instances: list = []
    starttls_offered = True
    login_error: Exception | None = None
    send_errors: list = []  # popped per send attempt

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port, self.timeout, self.context = host, port, timeout, context
        self.calls = []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def ehlo(self):
        self.calls.append("ehlo")

    def has_extn(self, name):
        return FakeSMTP.starttls_offered

    def starttls(self, context=None):
        self.calls.append("starttls")
        self.tls_context = context

    def login(self, u, p):
        self.calls.append(("login", u, p))
        if FakeSMTP.login_error:
            raise FakeSMTP.login_error

    def send_message(self, msg):
        if FakeSMTP.send_errors:
            raise FakeSMTP.send_errors.pop(0)
        self.calls.append(("send", msg["To"], msg["Subject"]))


@pytest.fixture()
def smtp(monkeypatch):
    FakeSMTP.instances, FakeSMTP.starttls_offered, FakeSMTP.login_error, FakeSMTP.send_errors = [], True, None, []
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setattr(mailer.time, "sleep", lambda s: None)
    monkeypatch.setattr(settings, "email_backend", "smtp")
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.test")
    monkeypatch.setattr(settings, "smtp_user", "mailer")
    monkeypatch.setattr(settings, "smtp_password", "pw-canary-123")
    monkeypatch.setattr(settings, "smtp_security", "starttls")
    return FakeSMTP


def test_starttls_verifies_certificates_and_hostnames(smtp):
    send_email("u@example.com", "Hi", "body")
    inst = smtp.instances[0]
    assert inst.calls[:2] == ["ehlo", "starttls"] and ("send", "u@example.com", "Hi") in inst.calls
    ctx = inst.tls_context
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname is True
    assert inst.calls.index("starttls") < inst.calls.index(("login", "mailer", "pw-canary-123"))  # TLS before login


def test_implicit_tls_mode_uses_verifying_context(smtp, monkeypatch):
    monkeypatch.setattr(settings, "smtp_security", "ssl")
    send_email("u@example.com", "Hi", "b")
    assert smtp.instances[0].context.verify_mode == ssl.CERT_REQUIRED and "starttls" not in smtp.instances[0].calls


def test_never_sends_credentials_when_starttls_missing(smtp):
    smtp.starttls_offered = False
    with pytest.raises(MailError, match="STARTTLS"):
        send_email("u@example.com", "Hi", "b")
    assert not any(isinstance(c, tuple) and c[0] == "login" for c in smtp.instances[0].calls)


def test_plaintext_smtp_refused_with_credentials_or_in_production(smtp, monkeypatch):
    monkeypatch.setattr(settings, "smtp_security", "none")
    with pytest.raises(MailError, match="without TLS"):
        send_email("u@example.com", "Hi", "b")
    monkeypatch.setattr(settings, "smtp_user", "")
    send_email("u@example.com", "Hi", "b")  # dev, no credentials: allowed
    monkeypatch.setattr(settings, "env", "production")
    with pytest.raises(MailError, match="without TLS"):
        send_email("u@example.com", "Hi", "b")


def test_auth_failure_is_not_retried_and_hides_credentials(smtp):
    smtp.login_error = smtplib.SMTPAuthenticationError(535, b"bad creds pw-canary-123")
    with pytest.raises(MailError) as e:
        send_email("u@example.com", "Hi", "b")
    assert len(smtp.instances) == 1 and "pw-canary-123" not in str(e.value) and "u@example.com" not in str(e.value)


def test_auth_withdrawn_after_rejection_is_permanent_too(smtp):
    smtp.login_error = smtplib.SMTPNotSupportedError("SMTP AUTH extension not supported by server.")
    with pytest.raises(MailError, match="authentication"):
        send_email("u@example.com", "Hi", "b")
    assert len(smtp.instances) == 1


def test_transient_failure_retried_once_permanent_not(smtp):
    smtp.send_errors = [smtplib.SMTPServerDisconnected("gone")]
    send_email("u@example.com", "Hi", "b")
    assert len(smtp.instances) == 2
    smtp.instances.clear()
    smtp.send_errors = [smtplib.SMTPResponseException(550, b"mailbox unavailable")]
    with pytest.raises(MailError):
        send_email("u@example.com", "Hi", "b")
    assert len(smtp.instances) == 1
    smtp.instances.clear()
    smtp.send_errors = [TimeoutError("t"), TimeoutError("t")]
    with pytest.raises(MailError, match="TimeoutError"):
        send_email("u@example.com", "Hi", "b")
    assert len(smtp.instances) == 2


def test_tls_errors_fail_closed_without_retry(smtp):
    smtp.send_errors = [ssl.SSLCertVerificationError("self signed")]
    with pytest.raises(MailError):
        send_email("u@example.com", "Hi", "b")
    assert len(smtp.instances) == 1


def test_header_injection_rejected(smtp):
    with pytest.raises(MailError):
        send_email("a@example.com\r\nBcc: evil@example.com", "Hi", "b")
    with pytest.raises(MailError):
        send_email("a@example.com", "Hi\r\nBcc: evil@example.com", "b")
    assert smtp.instances == []


def test_file_backend_writes_private_eml(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "email_backend", "file")
    monkeypatch.setattr(settings, "mail_dir", tmp_path / "mail")
    send_email("u@example.com", "Subj", "hello body")
    files = list((tmp_path / "mail").glob("*.eml"))
    assert len(files) == 1 and oct(files[0].stat().st_mode & 0o777) == "0o600"
    assert "Subject: Subj" in files[0].read_text() and "hello body" in files[0].read_text()


def test_console_backend_logs_no_body_or_address(monkeypatch, caplog):
    monkeypatch.setattr(settings, "email_backend", "console")
    with caplog.at_level(logging.DEBUG):
        send_email("user@example.com", "Reset", "https://x/reset?token=SECRET-TOKEN-VALUE")
    assert "SECRET-TOKEN-VALUE" not in caplog.text and "user@" not in caplog.text and "Reset" in caplog.text


def test_deliver_never_raises_and_logs_only_the_error_class(smtp, caplog):
    smtp.send_errors = [smtplib.SMTPResponseException(550, b"no such user user@example.com")]
    with caplog.at_level(logging.DEBUG):
        deliver("user@example.com", "Hi", "token=SECRET-TOKEN-VALUE")
    assert "delivery failed" in caplog.text
    for secret_ in ("SECRET-TOKEN-VALUE", "user@example.com", "pw-canary-123"):
        assert secret_ not in caplog.text


# ---- through the API ------------------------------------------------------------------------

def test_signup_and_reset_survive_delivery_failure_and_stay_uniform(client, monkeypatch, caplog):
    def boom(*a, **k):
        raise MailError("SMTP delivery failed (OSError)")
    monkeypatch.setattr(mailer, "send_email", boom)
    with caplog.at_level(logging.DEBUG):
        h = register(client)  # 201 despite mail outage
        known = client.post(f"{P}/auth/password-reset/request", json={"email": "a@example.com"})
        unknown = client.post(f"{P}/auth/password-reset/request", json={"email": "zz@example.com"})
    assert known.status_code == unknown.status_code == 202 and known.json() == unknown.json()
    assert client.get(f"{P}/auth/me", headers=h).status_code == 200


def test_tokens_never_appear_in_logs(client, caplog):
    with caplog.at_level(logging.DEBUG):
        register(client)
        client.post(f"{P}/auth/password-reset/request", json={"email": "a@example.com"})
    tokens = [re.search(r"token=(\S+)", m.body).group(1) for m in OUTBOX]
    assert len(tokens) == 2
    for t in tokens:
        assert t not in caplog.text
