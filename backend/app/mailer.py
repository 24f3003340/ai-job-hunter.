"""Outbound e-mail.

Backends: file (dev: writes .eml files), console (logs recipient domain + subject only), outbox (tests),
smtp (production). Message bodies contain single-use tokens, so NO backend logs a body, and failures log only
the exception class.
"""
import logging
import secrets
import smtplib
import socket
import ssl
import time
from dataclasses import dataclass
from email.message import EmailMessage

from .config import secret, settings

log = logging.getLogger(__name__)


class MailError(Exception):
    """Delivery failed. The message never contains addresses, bodies or credentials."""


@dataclass
class Mail:
    to: str
    subject: str
    body: str


OUTBOX: list[Mail] = []  # only used by the "outbox" backend


def _build(to: str, subject: str, body: str) -> EmailMessage:
    msg = EmailMessage()  # raises ValueError on CR/LF in headers (header-injection guard)
    msg["From"], msg["To"], msg["Subject"] = settings.email_from, to, subject
    msg.set_content(body)
    return msg


def _smtp_send(msg: EmailMessage) -> None:
    host, port, timeout = settings.smtp_host, settings.smtp_port, settings.smtp_timeout_seconds
    mode = settings.smtp_security
    user, password = settings.smtp_user, secret(settings.smtp_password)
    if mode not in ("starttls", "ssl", "none"):
        raise MailError(f"unknown smtp_security {mode!r}")
    if mode == "none" and (user or settings.env == "production"):
        raise MailError("refusing to use SMTP without TLS (credentials configured or production)")
    ctx = ssl.create_default_context(cafile=settings.smtp_ca_file or None)  # verifies cert chain AND hostname
    if mode == "ssl":
        client = smtplib.SMTP_SSL(host, port, timeout=timeout, context=ctx)
    else:
        client = smtplib.SMTP(host, port, timeout=timeout)
    with client as smtp:
        if mode == "starttls":
            smtp.ehlo()
            if not smtp.has_extn("starttls"):
                raise MailError("server does not offer STARTTLS")
            smtp.starttls(context=ctx)
            smtp.ehlo()
        if user:
            smtp.login(user, password)
        smtp.send_message(msg)


def send_email(to: str, subject: str, body: str, *, attempts: int = 2) -> None:
    """Deliver or raise MailError. Transient failures get one retry."""
    backend = settings.email_backend
    try:
        msg = _build(to, subject, body)
    except ValueError as exc:
        raise MailError("invalid message headers") from exc
    if backend == "outbox":
        OUTBOX.append(Mail(to, subject, body))
    elif backend == "file":
        settings.mail_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = settings.mail_dir / f"{int(time.time())}-{secrets.token_hex(4)}.eml"
        path.write_bytes(bytes(msg))
        path.chmod(0o600)
    elif backend == "console":
        log.info("email queued domain=%s subject=%r", to.rsplit("@", 1)[-1], subject)  # body deliberately omitted
    elif backend == "smtp":
        for attempt in range(1, attempts + 1):
            try:
                _smtp_send(msg)
                return
            except MailError:
                raise
            except (smtplib.SMTPAuthenticationError, smtplib.SMTPNotSupportedError) as exc:
                # permanent (bad credentials, or AUTH withdrawn after a rejected attempt): never retry, so a
                # wrong password cannot hammer the account
                raise MailError("SMTP authentication failed or is not supported") from exc
            except (smtplib.SMTPException, OSError, ssl.SSLError, socket.timeout) as exc:
                permanent = isinstance(exc, smtplib.SMTPResponseException) and 500 <= exc.smtp_code < 600
                tls_problem = isinstance(exc, ssl.SSLError)
                if attempt == attempts or permanent or tls_problem:
                    raise MailError(f"SMTP delivery failed ({type(exc).__name__})") from exc
                time.sleep(0.5 * attempt)
    else:
        raise MailError(f"unknown email backend {backend!r}")


def deliver(to: str, subject: str, body: str) -> None:
    """Background-task entry point: never raises, never logs the body or address."""
    try:
        send_email(to, subject, body)
    except MailError as exc:
        log.error("email delivery failed: %s", exc)
