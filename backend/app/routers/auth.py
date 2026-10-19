from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import audit
from ..config import settings
from ..db import get_db
from ..deps import current_session, current_user
from ..models import AuthSession, CandidateProfile, User, utcnow
from ..schemas import Credentials, TokenOut
from ..security import create_session, hash_password, verify_password

router = APIRouter(tags=["auth"])

# Verified against on unknown emails so response timing doesn't reveal account existence.
_DUMMY_HASH = hash_password("not-a-real-password")


@router.post("/auth/register", response_model=TokenOut, status_code=201)
def register(body: Credentials, db: Session = Depends(get_db)):
    email = body.email.lower()
    user = User(email=email, password_hash=hash_password(body.password))
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Unable to register with these details")
    db.add(CandidateProfile(user_id=user.id))
    audit(db, user.id, "register", "user", user.id)
    db.commit()
    return TokenOut(access_token=create_session(db, user.id))


@router.post("/auth/login", response_model=TokenOut)
def login(body: Credentials, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    fail = HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    if user is None:
        verify_password(_DUMMY_HASH, body.password)
        raise fail
    locked = user.locked_until
    if locked is not None and (locked if locked.tzinfo else locked.replace(tzinfo=utcnow().tzinfo)) > utcnow():
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed attempts; try again later")
    if user.account_status != "active" or not verify_password(user.password_hash, body.password):
        user.failed_logins += 1
        if user.failed_logins >= settings.login_max_failures:
            user.locked_until = utcnow() + timedelta(minutes=settings.login_lockout_minutes)
            user.failed_logins = 0
        audit(db, user.id, "login_failed", "user", user.id)
        db.commit()
        raise fail
    user.failed_logins, user.locked_until = 0, None
    audit(db, user.id, "login", "user", user.id)
    db.commit()
    return TokenOut(access_token=create_session(db, user.id))


@router.post("/auth/logout", status_code=204)
def logout(session=Depends(current_session), db: Session = Depends(get_db)):
    db.delete(session)
    db.commit()


@router.delete("/account", status_code=204)
def delete_account(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Hard-deletes the user and all owned records (cascade); keeps an audit marker with no content."""
    audit(db, user.id, "account_deleted", "user", user.id)
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    db.delete(user)
    db.commit()
