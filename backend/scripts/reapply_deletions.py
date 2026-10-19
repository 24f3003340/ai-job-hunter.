"""Re-apply account deletions after restoring an OLDER backup, so deleted users do not reappear.

The API logs one line per deletion:   account_deleted user_id=<uuid>
Feed it the (off-box) logs covering the period since the backup was taken:

    cat /var/log/jobhunter/*.log | python scripts/reapply_deletions.py --since-file - --dry-run
    ... | python scripts/reapply_deletions.py --storage-dir /var/lib/jobhunter/storage

Deletes each listed user (database rows cascade) and that user's stored upload files. Idempotent: unknown ids are skipped.
"""
import argparse
import re
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config import settings  # noqa: E402
from app.models import Document, User  # noqa: E402

PATTERN = re.compile(r"account_deleted user_id=([0-9a-fA-F-]{32,36})")


def apply(db: Session, ids: set[UUID], objects: Path, dry_run: bool) -> dict:
    deleted, skipped, files = 0, 0, 0
    for uid in sorted(ids, key=str):
        user = db.get(User, uid)
        if user is None:
            skipped += 1
            continue
        keys = list(db.scalars(select(Document.storage_key).where(Document.user_id == uid)))
        if not dry_run:
            db.delete(user)
            db.commit()
            for k in keys:
                (objects / k).unlink(missing_ok=True)
        deleted += 1
        files += len(keys)
    return {"users": deleted, "files": files, "already_absent": skipped, "dry_run": dry_run}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since-file", default="-", help="log file to read ('-' = stdin)")
    ap.add_argument("--storage-dir", default=str(settings.storage_dir))
    ap.add_argument("--database-url", default=settings.database_url)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    text = sys.stdin.read() if a.since_file == "-" else Path(a.since_file).read_text()
    ids = {UUID(m) for m in PATTERN.findall(text)}
    with Session(create_engine(a.database_url)) as db:
        result = apply(db, ids, Path(a.storage_dir) / "objects", a.dry_run)
    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
