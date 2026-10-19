"""Real SMTP protocol tests against a local aiosmtpd server (STARTTLS / SMTPS / AUTH, self-signed cert).
No external network. Run with: pytest -m integration tests/integration/test_smtp.py
These prove the smtplib path works end-to-end; they do NOT prove delivery through a production provider
(see docs/REPORT.md)."""
import datetime
import email
import ipaddress
import logging
import re
import socket
import ssl

import pytest

aiosmtpd = pytest.importorskip("aiosmtpd")
from aiosmtpd.controller import Controller  # noqa: E402
from aiosmtpd.smtp import AuthResult, LoginPassword  # noqa: E402
from cryptography import x509  # noqa: E402
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from cryptography.x509.oid import NameOID  # noqa: E402

from app.config import settings  # noqa: E402
from app.mailer import MailError, send_email  # noqa: E402
from conftest import register  # noqa: E402

pytestmark = pytest.mark.integration
P = "/api/v1"
USER, PW = "mailer", "smtp-test-password"


def make_cert(tmp_path, san):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-smtp")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName(san), critical=False).sign(key, hashes.SHA256()))
    crt, k = tmp_path / "cert.pem", tmp_path / "key.pem"
    crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    k.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                    serialization.NoEncryption()))
    return str(crt), str(k)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Inbox:
    def __init__(self):
        self.messages, self.auth_attempts = [], 0


    async def handle_DATA(self, server, session, envelope):
        self.messages.append(email.message_from_bytes(envelope.content))
        return "250 OK"

    def authenticator(self, server, session, envelope, mechanism, auth_data):
        self.auth_attempts += 1
        ok = isinstance(auth_data, LoginPassword) and auth_data.login == USER.encode() and auth_data.password == PW.encode()
        return AuthResult(success=ok, handled=False if not ok else True)


def start(inbox, tmp_path, *, mode="starttls", san=None):
    crt, key = make_cert(tmp_path, san or [x509.IPAddress(ipaddress.ip_address("127.0.0.1")), x509.DNSName("localhost")])
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(crt, key)
    port = free_port()
    kw = dict(authenticator=inbox.authenticator, auth_required=True)
    if mode == "starttls":
        c = Controller(inbox, hostname="127.0.0.1", port=port, tls_context=ctx, require_starttls=True, **kw)
    elif mode == "ssl":
        c = Controller(inbox, hostname="127.0.0.1", port=port, ssl_context=ctx, auth_require_tls=False, **kw)  # channel is already TLS
    else:  # plain, no TLS offered
        c = Controller(inbox, hostname="127.0.0.1", port=port)
    c.start()
    return c, port, crt


@pytest.fixture()
def server(tmp_path, monkeypatch):
    started = []

    def make(mode="starttls", san=None, trust=True, user=USER, password=PW):
        inbox = Inbox()
        c, port, crt = start(inbox, tmp_path, mode=mode, san=san)
        started.append(c)
        monkeypatch.setattr(settings, "email_backend", "smtp")
        monkeypatch.setattr(settings, "smtp_host", "127.0.0.1")
        monkeypatch.setattr(settings, "smtp_port", port)
        monkeypatch.setattr(settings, "smtp_user", user)
        monkeypatch.setattr(settings, "smtp_password", password)
        monkeypatch.setattr(settings, "smtp_security", "ssl" if mode == "ssl" else "starttls")
        monkeypatch.setattr(settings, "smtp_ca_file", crt if trust else "")
        monkeypatch.setattr(settings, "smtp_timeout_seconds", 5.0)
        return inbox

    yield make
    for c in started:
        c.stop()


def token_of(msg) -> str:
    return re.search(r"token=(\S+)", msg.get_payload(decode=True).decode()).group(1)


def test_starttls_with_auth_delivers_message(server):
    inbox = server()
    send_email("user@example.com", "Verify your email", "Confirm: https://app.example/verify-email?token=abc")
    assert len(inbox.messages) == 1
    m = inbox.messages[0]
    assert m["To"] == "user@example.com" and m["Subject"] == "Verify your email" and m["From"] == settings.email_from


def test_implicit_tls_delivers_message(server):
    inbox = server(mode="ssl")
    send_email("user@example.com", "Hi", "body")
    assert len(inbox.messages) == 1


def test_wrong_password_fails_without_retry_or_delivery(server):
    inbox = server(password="wrong")
    with pytest.raises(MailError, match="authentication"):
        send_email("user@example.com", "Hi", "body")
    # smtplib itself tries PLAIN then LOGIN inside one login() (<=2 attempts); a mailer retry would show 3-4
    assert inbox.messages == [] and 1 <= inbox.auth_attempts <= 2


def test_untrusted_certificate_aborts_before_credentials_are_sent(server):
    inbox = server(trust=False)  # self-signed cert, not in the system store
    with pytest.raises(MailError):
        send_email("user@example.com", "Hi", "body")
    assert inbox.messages == [] and inbox.auth_attempts == 0


def test_certificate_hostname_mismatch_is_rejected(server):
    inbox = server(san=[x509.DNSName("mail.other-host.test")])  # trusted CA, but cert is for another host
    with pytest.raises(MailError):
        send_email("user@example.com", "Hi", "body")
    assert inbox.messages == [] and inbox.auth_attempts == 0


def test_server_without_starttls_is_refused_and_no_credentials_leak(server):
    inbox = server(mode="plain")
    with pytest.raises(MailError, match="STARTTLS"):
        send_email("user@example.com", "Hi", "body")
    assert inbox.messages == [] and inbox.auth_attempts == 0


# ---- whole flows over real SMTP -------------------------------------------------------------

def test_verification_and_reset_links_delivered_and_work_once(client, server):
    inbox = server()
    h = register(client)
    assert len(inbox.messages) == 1
    token = token_of(inbox.messages[0])
    assert client.post(f"{P}/auth/verify-email", json={"token": token}).status_code == 204
    assert client.get(f"{P}/auth/me", headers=h).json()["email_verified"] is True
    assert client.post(f"{P}/auth/verify-email", json={"token": token}).status_code == 400  # single use

    client.post(f"{P}/auth/password-reset/request", json={"email": "a@example.com"})
    assert len(inbox.messages) == 2 and inbox.messages[1]["Subject"] == "Reset your password"
    rt = token_of(inbox.messages[1])
    body = {"token": rt, "new_password": "brand-new-password-1"}
    assert client.post(f"{P}/auth/password-reset/confirm", json=body).status_code == 204
    assert client.post(f"{P}/auth/password-reset/confirm", json=body).status_code == 400


def test_unknown_email_sends_nothing_over_smtp(client, server):
    inbox = server()
    r = client.post(f"{P}/auth/password-reset/request", json={"email": "nobody@example.com"})
    assert r.status_code == 202 and inbox.messages == []


def test_resend_throttle_limits_real_mail_volume(client, server, monkeypatch):
    inbox = server()
    h = register(client)
    assert client.post(f"{P}/auth/resend-verification", headers=h).status_code == 429  # cooldown
    monkeypatch.setattr(settings, "verify_resend_cooldown_seconds", 0)
    monkeypatch.setattr(settings, "verify_resends_per_hour", 3)
    codes = [client.post(f"{P}/auth/resend-verification", headers=h).status_code for _ in range(4)]
    assert codes == [202, 202, 429, 429] and len(inbox.messages) == 3  # signup + 2 resends


def test_newest_token_wins_and_expired_token_is_rejected(client, server, monkeypatch):
    inbox = server()
    h = register(client)
    monkeypatch.setattr(settings, "verify_resend_cooldown_seconds", 0)
    client.post(f"{P}/auth/resend-verification", headers=h)
    old, new = token_of(inbox.messages[0]), token_of(inbox.messages[1])
    assert client.post(f"{P}/auth/verify-email", json={"token": old}).status_code == 400  # voided by resend
    assert client.post(f"{P}/auth/verify-email", json={"token": new}).status_code == 204

    monkeypatch.setattr(settings, "password_reset_ttl_minutes", -1)
    client.post(f"{P}/auth/password-reset/request", json={"email": "a@example.com"})
    expired = token_of(inbox.messages[-1])
    r = client.post(f"{P}/auth/password-reset/confirm", json={"token": expired, "new_password": "brand-new-password-1"})
    assert r.status_code == 400


def test_smtp_outage_does_not_break_signup_or_leak_tokens(client, monkeypatch, caplog):
    monkeypatch.setattr(settings, "email_backend", "smtp")
    monkeypatch.setattr(settings, "smtp_host", "127.0.0.1")
    monkeypatch.setattr(settings, "smtp_port", free_port())  # nothing listening
    monkeypatch.setattr(settings, "smtp_user", "")
    monkeypatch.setattr(settings, "smtp_security", "none")
    monkeypatch.setattr(settings, "smtp_timeout_seconds", 1.0)
    monkeypatch.setattr("app.mailer.time.sleep", lambda s: None)
    with caplog.at_level(logging.DEBUG):
        h = register(client)
        known = client.post(f"{P}/auth/password-reset/request", json={"email": "a@example.com"})
        unknown = client.post(f"{P}/auth/password-reset/request", json={"email": "zz@example.com"})
    assert known.status_code == unknown.status_code == 202 and known.json() == unknown.json()
    assert client.get(f"{P}/auth/me", headers=h).status_code == 200
    assert "delivery failed" in caplog.text and "token=" not in caplog.text and "a@example.com" not in caplog.text
