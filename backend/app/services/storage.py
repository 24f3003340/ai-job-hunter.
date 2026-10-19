"""Private on-disk storage for uploaded originals.

Files live under settings.storage_dir (never inside a served/static directory), are named by random
key (not by user-supplied filename), are written atomically via a temp file in the same volume, and
are only ever returned through authenticated, ownership-checked endpoints.
"""
import contextlib
import os
import secrets
import tempfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Document


def _root() -> Path:
    root = Path(settings.storage_dir)
    (root / "tmp").mkdir(parents=True, exist_ok=True, mode=0o700)
    (root / "objects").mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


def save(data: bytes) -> str:
    """Persist bytes and return the storage key. The temp file is removed on any failure."""
    root = _root()
    key = secrets.token_hex(16)
    fd, tmp_name = tempfile.mkstemp(dir=root / "tmp", prefix="up_")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, root / "objects" / key)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)
        raise
    return key


def path_for(key: str) -> Path:
    if not key.isalnum():  # keys are hex; refuse anything path-like
        raise ValueError("invalid storage key")
    return _root() / "objects" / key


def read(key: str) -> bytes:
    return path_for(key).read_bytes()


def delete(key: str) -> None:
    with contextlib.suppress(FileNotFoundError):
        path_for(key).unlink()


def delete_user_files(db: Session, user_id) -> None:
    for key in db.scalars(select(Document.storage_key).where(Document.user_id == user_id)):
        delete(key)


def purge_stale_temp(max_age_seconds: int = 3600) -> int:
    """Remove temp files left behind by a crash. Safe to run from a periodic job."""
    import time

    removed = 0
    for f in (_root() / "tmp").iterdir():
        if time.time() - f.stat().st_mtime > max_age_seconds:
            with contextlib.suppress(FileNotFoundError):
                f.unlink()
                removed += 1
    return removed
