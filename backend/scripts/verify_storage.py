"""Verify that stored uploads match the database: every Document row has its file, with the recorded size and SHA-256,
and no file exists without a row. Used by the restore-verification procedure (deploy/scripts/verify_restore.sh).

    JOBHUNTER_DATABASE_URL=postgresql+psycopg://... python scripts/verify_storage.py --storage-dir /path/to/storage
Exit status 0 = consistent, 1 = problems found (listed), 2 = could not run.
"""
import argparse
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # runnable as a plain script from any directory

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Document


def verify(db: Session, objects: Path) -> dict:
    problems: list[str] = []
    known: set[str] = set()
    checked = 0
    for d in db.scalars(select(Document)):
        known.add(d.storage_key)
        f = objects / d.storage_key
        checked += 1
        if not f.is_file():
            problems.append(f"missing file for document {d.id}")
            continue
        data = f.read_bytes()
        if len(data) != d.size_bytes:
            problems.append(f"size mismatch for document {d.id}")
        if hashlib.sha256(data).hexdigest() != d.checksum:
            problems.append(f"checksum mismatch for document {d.id}")
    orphans = sorted(p.name for p in objects.iterdir() if p.is_file() and p.name not in known) if objects.is_dir() else []
    for o in orphans:
        problems.append(f"orphan file without a database row: {o}")
    return {"checked": checked, "problems": problems}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--storage-dir", default=str(settings.storage_dir))
    ap.add_argument("--database-url", default=settings.database_url)
    a = ap.parse_args()
    objects = Path(a.storage_dir) / "objects"
    try:
        engine = create_engine(a.database_url)
        with Session(engine) as db:
            result = verify(db, objects)
    except Exception as exc:  # noqa: BLE001
        print(f"cannot verify: {type(exc).__name__}", file=sys.stderr)
        return 2
    print(f"documents checked: {result['checked']}")
    for p in result["problems"]:
        print(f"PROBLEM: {p}")
    print("OK" if not result["problems"] else f"{len(result['problems'])} problem(s)")
    return 0 if not result["problems"] else 1


if __name__ == "__main__":
    sys.exit(main())
