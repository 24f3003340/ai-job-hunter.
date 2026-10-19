import hashlib
import secrets
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import AuthSession, utcnow

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, user_id) -> str:
    token = secrets.token_urlsafe(32)
    db.add(AuthSession(
        user_id=user_id,
        token_hash=_digest(token),
        expires_at=utcnow() + timedelta(hours=settings.session_ttl_hours),
    ))
    db.commit()
    return token


def resolve_session(db: Session, token: str) -> AuthSession | None:
    row = db.scalar(select(AuthSession).where(AuthSession.token_hash == _digest(token)))
    if row is None:
        return None
    expires = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=utcnow().tzinfo)
    if expires <= utcnow():
        db.delete(row)
        db.commit()
        return None
    return row
