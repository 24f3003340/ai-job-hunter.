import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app import db as dbmod
from app.db import Base, get_db, make_engine
from app.main import app


@pytest.fixture(autouse=True)
def _isolated_runtime(tmp_path, monkeypatch):
    """Fresh limiter, outbox and private storage dir for every test; no network, no real e-mail."""
    from app.config import settings
    from app.mailer import OUTBOX
    from app.ratelimit import limiter

    monkeypatch.setattr(settings, "email_backend", "outbox")
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "storage")
    monkeypatch.setattr(settings, "clamav_host", "")
    OUTBOX.clear()
    limiter.reset()
    yield


TEST_DB_URL = os.environ.get("JOBHUNTER_TEST_DATABASE_URL", "")  # set => run the whole suite on PostgreSQL


@pytest.fixture(scope="session")
def _pg_migrated():
    """Build the schema ONCE with Alembic (so the suite also exercises the migration-built schema)."""
    if not TEST_DB_URL:
        yield None
        return
    from alembic import command
    from alembic.config import Config
    from pathlib import Path
    import sqlalchemy as sa

    eng = make_engine(TEST_DB_URL)
    with eng.begin() as c:
        c.execute(sa.text("DROP SCHEMA public CASCADE"))
        c.execute(sa.text("CREATE SCHEMA public"))
    backend = Path(__file__).resolve().parent.parent
    cfg = Config(str(backend / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend / "migrations"))
    cfg.set_main_option("sqlalchemy.url", TEST_DB_URL)
    command.upgrade(cfg, "head")
    yield eng
    eng.dispose()


@pytest.fixture()
def engine(_pg_migrated):
    if _pg_migrated is not None:
        import sqlalchemy as sa
        names = ", ".join(f'"{t}"' for t in Base.metadata.tables)
        with _pg_migrated.begin() as c:
            c.execute(sa.text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
        return _pg_migrated
    eng = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture()
def session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture()
def client(session_factory):
    def override():
        with session_factory() as s:
            yield s

    app.dependency_overrides[get_db] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


def register(client, email="a@example.com"):
    r = client.post("/api/v1/auth/register", json={"email": email, "password": "correct-horse-battery"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def auth(client):
    return register(client)
