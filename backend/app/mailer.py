"""Outbound e-mail. Backends: console (dev), outbox (tests), smtp (production)."""
import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

from .config import settings

log = logging.getLogger(__name__)


@dataclass
class Mail:
    to: str
    subject: str
    body: str


OUTBOX: list[Mail] = []  # only used by the "outbox" backend


def send_email(to: str, subject: str, body: str) -> None:
    backend = settings.email_backend
    if backend == "outbox":
        OUTBOX.append(Mail(to, subject, body))
    elif backend == "console":
        # Development only: production config validation rejects this backend.
        log.info("EMAIL to=%s subject=%s\n%s", to, subject, body)
    elif backend == "smtp":
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = settings.email_from, to, subject
        msg.set_content(body)
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            smtp.starttls()
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(msg)
    else:
        raise ValueError(f"Unknown email backend {backend!r}")
