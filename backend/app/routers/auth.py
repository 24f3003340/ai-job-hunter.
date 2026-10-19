from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import audit
from ..config import settings
from ..db import get_db
from ..deps import current_session, current_user
from ..mailer import deliver
from ..models import AuthSession, CandidateProfile, User, utcnow
from ..ratelimit import limit_ip
from ..schemas import Credentials, EmailOnly, ResetConfirm, TokenBody, TokenOut
from ..security import create_session, hash_password, verify_password
from ..services import tokens

router = APIRouter(tags=["auth"])
_auth_limit = limit_ip("auth", "rate_limit_auth", critical=True)

# Verified against on unknown emails so response timing doesn't reveal account existence.
_DUMMY_HASH = hash_password("not-a-real-password")


def _queue_verification(db: Session, user: User, bg: BackgroundTasks) -> None:
    """Token is stored now; the e-mail goes out after the response (and after commit), so an SMTP outage or
    slow server can neither fail the request nor leak account existence through timing."""
    token = tokens.issue(db, user.id, "email_verify", timedelta(hours=settings.email_verify_ttl_hours))
    bg.add_task(deliver, user.email, "Verify your email",
               f"Confirm your address: {settings.public_base_url}/verify-email?token={token}\n"
               f"This link expires in {settings.email_verify_ttl_hours} hours.")


@router.post("/auth/register", response_model=TokenOut, status_code=201, dependencies=[_auth_limit])
def register(body: Credentials, bg: BackgroundTasks, db: Session = Depends(get_db)):
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
    _queue_verification(db, user, bg)
    db.commit()
    return TokenOut(access_token=create_session(db, user.id))


@router.post("/auth/login", response_model=TokenOut, dependencies=[_auth_limit])
def login(body: Credentials, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    fail = HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    if user is None:
        verify_password(_DUMMY_HASH, body.password)
        raise fail
    locked = user.locked_until
    if locked is not None and tokens.aware(locked) > utcnow():
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed attempts; try again later")
    if user.account_status != "active" or not verify_password(user.password_hash, body.password):
        user.failed_logins += 1
        if user.failed_logins >= settings.login_max_failures:
            user.locked_until = utcnow() + timedelta(minutes=settings.login_lockout_minutes)
            user.failed_logins = 0
            audit(db, user.id, "account_locked", "user", user.id)
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


@router.get("/auth/me")
def me(user: User = Depends(current_user)):
    return {"id": user.id, "email": user.email, "email_verified": user.email_verified_at is not None,
            "ai_consent": user.ai_consent_at is not None}


# ---- password reset -------------------------------------------------------------------------

@router.post("/auth/password-reset/request", status_code=202, dependencies=[_auth_limit])
def request_password_reset(body: EmailOnly, bg: BackgroundTasks, db: Session = Depends(get_db)):
    """Always answers identically, so it cannot be used to discover which e-mails have accounts."""
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is not None and user.account_status == "active" and \
            tokens.recent_count(db, user.id, "password_reset", timedelta(hours=1)) < settings.reset_requests_per_hour:
        token = tokens.issue(db, user.id, "password_reset", timedelta(minutes=settings.password_reset_ttl_minutes))
        bg.add_task(deliver, user.email, "Reset your password",
                   f"Reset link: {settings.public_base_url}/reset-password?token={token}\n"
                   f"It expires in {settings.password_reset_ttl_minutes} minutes and works once. "
                   "If you did not ask for this, ignore this message.")
        audit(db, user.id, "password_reset_requested", "user", user.id)
        db.commit()
    return {"detail": "If that account exists, a reset email has been sent."}


@router.post("/auth/password-reset/confirm", status_code=204, dependencies=[_auth_limit])
def confirm_password_reset(body: ResetConfirm, db: Session = Depends(get_db)):
    row = tokens.consume(db, body.token, "password_reset")
    if row is None:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired token")
    user = db.get(User, row.user_id)
    user.password_hash = hash_password(body.new_password)
    user.failed_logins, user.locked_until = 0, None
    # Every existing session is revoked: a reset implies the old credentials may be compromised.
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    audit(db, user.id, "password_reset_completed", "user", user.id)
    db.commit()


# ---- e-mail verification --------------------------------------------------------------------

@router.post("/auth/verify-email", status_code=204, dependencies=[_auth_limit])
def verify_email(body: TokenBody, db: Session = Depends(get_db)):
    row = tokens.consume(db, body.token, "email_verify")
    if row is None:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired token")
    user = db.get(User, row.user_id)
    user.email_verified_at = user.email_verified_at or utcnow()
    audit(db, user.id, "email_verified", "user", user.id)
    db.commit()


@router.post("/auth/resend-verification", status_code=202, dependencies=[_auth_limit])
def resend_verification(bg: BackgroundTasks, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.email_verified_at is not None:
        return {"detail": "Email already verified."}
    last = tokens.last_issued(db, user.id, "email_verify")
    if last and (utcnow() - last).total_seconds() < settings.verify_resend_cooldown_seconds:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Please wait before requesting another email",
                            headers={"Retry-After": str(settings.verify_resend_cooldown_seconds)})
    if tokens.recent_count(db, user.id, "email_verify", timedelta(hours=1)) >= settings.verify_resends_per_hour:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many verification emails requested; try later")
    _queue_verification(db, user, bg)
    audit(db, user.id, "verification_resent", "user", user.id)
    db.commit()
    return {"detail": "Verification email sent."}


# ---- consent / account ----------------------------------------------------------------------

@router.post("/account/ai-consent", status_code=204)
def grant_ai_consent(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Explicit consent to process CV/profile data with an external AI provider."""
    user.ai_consent_at = user.ai_consent_at or utcnow()
    audit(db, user.id, "ai_consent_granted", "user", user.id)
    db.commit()


@router.delete("/account/ai-consent", status_code=204)
def revoke_ai_consent(user: User = Depends(current_user), db: Session = Depends(get_db)):
    user.ai_consent_at = None
    audit(db, user.id, "ai_consent_revoked", "user", user.id)
    db.commit()


@router.delete("/account", status_code=204)
def delete_account(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Hard-deletes the user and all owned records (cascade); keeps an audit marker with no content.
    Stored upload files are removed too."""
    from ..services.storage import delete_user_files  # noqa: PLC0415

    delete_user_files(db, user.id)
    audit(db, user.id, "account_deleted", "user", user.id)
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    db.delete(user)
    db.commit()
