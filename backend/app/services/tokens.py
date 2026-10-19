import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..models import AuthToken, utcnow


def aware(dt: datetime) -> datetime:
    """SQLite returns naive datetimes; treat them as UTC."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue(db: Session, user_id, purpose: str, ttl: timedelta) -> str:
    """Create a token; only its hash is stored. Earlier unused tokens of the same purpose are voided."""
    db.execute(update(AuthToken).where(AuthToken.user_id == user_id, AuthToken.purpose == purpose,
                                       AuthToken.used_at.is_(None)).values(used_at=utcnow()))
    token = secrets.token_urlsafe(32)
    db.add(AuthToken(user_id=user_id, purpose=purpose, token_hash=_digest(token), expires_at=utcnow() + ttl))
    db.flush()
    return token


def consume(db: Session, token: str, purpose: str) -> AuthToken | None:
    """Atomically mark the token used. Returns the row, or None if unknown/expired/already used."""
    row = db.scalar(select(AuthToken).where(AuthToken.token_hash == _digest(token), AuthToken.purpose == purpose))
    if row is None or row.used_at is not None or aware(row.expires_at) <= utcnow():
        return None
    result = db.execute(update(AuthToken).where(AuthToken.id == row.id, AuthToken.used_at.is_(None))
                        .values(used_at=utcnow()))
    if result.rowcount != 1:  # lost a race with a concurrent use
        return None
    return row


def recent_count(db: Session, user_id, purpose: str, within: timedelta) -> int:
    return db.scalar(select(func.count()).select_from(AuthToken).where(
        AuthToken.user_id == user_id, AuthToken.purpose == purpose,
        AuthToken.created_at >= utcnow() - within)) or 0


def last_issued(db: Session, user_id, purpose: str) -> datetime | None:
    ts = db.scalar(select(func.max(AuthToken.created_at)).where(
        AuthToken.user_id == user_id, AuthToken.purpose == purpose))
    return aware(ts) if ts else None
