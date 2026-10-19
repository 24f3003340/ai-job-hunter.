from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .db import get_db
from .models import User
from .security import resolve_session

_bearer = HTTPBearer(auto_error=False)


def current_session(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer), db: Session = Depends(get_db)
):
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    session = resolve_session(db, creds.credentials)
    if session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired session")
    return session


def current_user(session=Depends(current_session), db: Session = Depends(get_db)) -> User:
    """Identity always comes from the validated session, never from request bodies."""
    user = db.get(User, session.user_id)
    if user is None or user.account_status != "active":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account unavailable")
    return user
