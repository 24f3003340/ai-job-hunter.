"""PostgreSQL-specific behaviour. Run with:
    JOBHUNTER_TEST_DATABASE_URL=postgresql+psycopg://USER:PW@HOST:PORT/DB pytest -m integration tests/integration/test_postgres.py
The URL's role must be allowed to CREATE DATABASE (scratch databases are created and dropped per test).
"""
import os
import re
import threading
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app import models  # noqa: F401
from app.db import Base, get_db, make_engine
from app.main import app
from app.mailer import OUTBOX
from conftest import register

pytestmark = [pytest.mark.integration,
              pytest.mark.skipif(not os.environ.get("JOBHUNTER_TEST_DATABASE_URL"),
                                 reason="JOBHUNTER_TEST_DATABASE_URL not set")]
P = "/api/v1"
BACKEND = Path(__file__).resolve().parents[2]


def alembic_cfg(url: str) -> Config:
    c = Config(str(BACKEND / "alembic.ini"))
    c.set_main_option("script_location", str(BACKEND / "migrations"))
    c.set_main_option("sqlalchemy.url", url)
    return c


@pytest.fixture()
def scratch_url():
    base = make_url(os.environ["JOBHUNTER_TEST_DATABASE_URL"])
    name = "jh_scratch_" + uuid.uuid4().hex[:10]
    admin = sa.create_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(sa.text(f'CREATE DATABASE "{name}"'))
    url = base.set(database=name).render_as_string(hide_password=False)
    yield url
    with admin.connect() as c:
        c.execute(sa.text(f'DROP DATABASE "{name}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture()
def pg_client(scratch_url):
    """A client wired to a freshly migrated, empty PostgreSQL database."""
    from fastapi.testclient import TestClient
    command.upgrade(alembic_cfg(scratch_url), "head")
    eng = make_engine(scratch_url)
    factory = sessionmaker(bind=eng, expire_on_commit=False)

    def override():
        with factory() as s:
            yield s

    app.dependency_overrides[get_db] = override
    yield TestClient(app), factory, eng
    app.dependency_overrides.clear()
    eng.dispose()


def test_empty_database_migrates_and_matches_models(scratch_url):
    command.upgrade(alembic_cfg(scratch_url), "head")
    eng = sa.create_engine(scratch_url)
    assert set(Base.metadata.tables) <= set(sa.inspect(eng).get_table_names())
    with eng.connect() as conn:
        assert compare_metadata(MigrationContext.configure(conn), Base.metadata) == []
        assert conn.execute(sa.text("select version_num from alembic_version")).scalar() == "0002"
    # native types, not text fallbacks
    cols = {c["name"]: c["type"] for c in sa.inspect(eng).get_columns("users")}
    assert "UUID" in str(cols["id"]).upper() and getattr(cols["created_at"], "timezone", False)
    eng.dispose()


def test_upgrade_from_0001_preserves_seeded_data_and_is_reversible(scratch_url):
    cfg = alembic_cfg(scratch_url)
    command.upgrade(cfg, "0001")
    eng = sa.create_engine(scratch_url)
    uid, jid, r1, r2 = (uuid.uuid4() for _ in range(4))
    with eng.begin() as c:
        c.execute(sa.text("INSERT INTO users (id,email,password_hash,account_status,failed_logins,created_at,updated_at)"
                          " VALUES (:i,'old@example.com','h','active',0,now(),now())"), {"i": uid})
        c.execute(sa.text("INSERT INTO candidate_profiles (id,user_id,full_name,phone,education_json,experience_json,"
                          "projects_json,skills_json,preferences_json,profile_version,updated_at) VALUES "
                          "(:i,:u,'Old User','','[]','[]','[]','[]','{}',3,now())"), {"i": uuid.uuid4(), "u": uid})
        c.execute(sa.text("INSERT INTO jobs (id,user_id,source,title,company,location,description,required_skills_json,"
                          "preferred_skills_json,first_seen_at,status,content_hash) VALUES "
                          "(:i,:u,'manual','Eng','Co','','','[]','[]',now(),'active','x')"), {"i": jid, "u": uid})
        for rid, ts in ((r1, "2025-02-01"), (r2, "2025-03-01")):
            c.execute(sa.text("INSERT INTO resume_versions (id,user_id,job_id,source_profile_version,content_json,"
                              "factual_review_status,created_at) VALUES (:i,:u,:j,1,CAST(:c AS json),'pending',:t)"),
                      {"i": rid, "u": uid, "j": jid, "c": '{"a": 1}', "t": ts})
    command.upgrade(cfg, "head")
    with eng.connect() as c:
        assert c.execute(sa.text("select email from users")).scalar() == "old@example.com"
        assert c.execute(sa.text("select full_name, profile_version from candidate_profiles")).one() == ("Old User", 3)
        rows = c.execute(sa.text("select version_number, generation_source, content_json from resume_versions "
                                 "order by created_at")).fetchall()
        assert [r[0] for r in rows] == [1, 2] and all(r[1] == "legacy" and r[2] == {"a": 1} for r in rows)
        # the new unique constraint is really enforced by PostgreSQL
    with pytest.raises(sa.exc.IntegrityError):
        with eng.begin() as c:
            c.execute(sa.text("update resume_versions set version_number = 1"))
    command.downgrade(cfg, "0001")
    command.upgrade(cfg, "head")
    with eng.connect() as c:
        assert c.execute(sa.text("select count(*) from resume_versions")).scalar() == 2
    eng.dispose()


def test_full_user_journey_and_account_deletion_cascades(pg_client):
    from helpers import confirm_payload, make_pdf, upload
    from app.config import settings
    client, factory, eng = pg_client
    h = register(client)
    doc = upload(client, h, make_pdf(), "cv.pdf").json()
    prev = client.post(f"{P}/documents/{doc['id']}/parse", headers=h).json()
    assert client.post(f"{P}/documents/{doc['id']}/parse/confirm", headers=h, json=confirm_payload(prev)).status_code == 200
    job = client.post(f"{P}/jobs", headers=h, json={"title": "NLP Engineer", "company": "Acme", "application_url": "https://a.example/1",
                                                     "required_skills": ["Python"]}).json()
    client.post(f"{P}/jobs/{job['id']}/verify", headers=h)
    rv = client.post(f"{P}/jobs/{job['id']}/resume", headers=h, json={}).json()
    rv2 = client.post(f"{P}/jobs/{job['id']}/resume", headers=h, json={}).json()
    assert (rv["version_number"], rv2["version_number"]) == (1, 2)
    assert client.get(f"{P}/resumes/{rv['id']}/download?format=pdf", headers=h).content.startswith(b"%PDF")
    app_ = client.post(f"{P}/applications", headers=h, json={"job_id": job["id"], "resume_version_id": rv["id"],
                       "answers": [{"question": "Q", "answer": "A", "user_confirmed": True}]}).json()
    assert client.post(f"{P}/applications/{app_['id']}/approve", headers=h).status_code == 200
    client.put(f"{P}/applications/{app_['id']}/resume", headers=h, json={"resume_version_id": rv2["id"]})
    assert client.post(f"{P}/applications/{app_['id']}/submit", headers=h).status_code == 409
    assert list((settings.storage_dir / "objects").iterdir())

    assert client.delete(f"{P}/account", headers=h).status_code == 204
    with eng.connect() as c:
        for t in ("users", "auth_sessions", "candidate_profiles", "documents", "cv_parses", "jobs", "resume_versions",
                  "claim_reviews", "applications", "application_answers", "application_approvals",
                  "application_events", "auth_tokens"):
            assert c.execute(sa.text(f"select count(*) from {t}")).scalar() == 0, f"orphans left in {t}"
        assert c.execute(sa.text("select count(*) from audit_events where action='account_deleted'")).scalar() == 1
    assert list((settings.storage_dir / "objects").iterdir()) == []


def hammer(fn, n=8):
    results, barrier = [], threading.Barrier(n)

    def run():
        barrier.wait()
        results.append(fn())

    ts = [threading.Thread(target=run) for _ in range(n)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    return results


def test_concurrent_duplicate_registration_yields_one_account_no_500(pg_client):
    client, _, eng = pg_client
    body = {"email": "race@example.com", "password": "correct-horse-battery"}
    codes = sorted(r.status_code for r in hammer(lambda: client.post(f"{P}/auth/register", json=body)))
    assert codes.count(201) == 1 and set(codes) <= {201, 409}, codes
    with eng.connect() as c:
        assert c.execute(sa.text("select count(*) from users")).scalar() == 1


def test_password_reset_token_is_single_use_under_concurrency(pg_client):
    client, _, _ = pg_client
    register(client)
    OUTBOX.clear()
    client.post(f"{P}/auth/password-reset/request", json={"email": "a@example.com"})
    token = re.search(r"token=(\S+)", OUTBOX[-1].body).group(1)
    body = {"token": token, "new_password": "brand-new-password-1"}
    codes = sorted(r.status_code for r in hammer(lambda: client.post(f"{P}/auth/password-reset/confirm", json=body)))
    assert codes.count(204) == 1 and set(codes) <= {204, 400}, codes


def test_nul_bytes_are_rejected_not_500(pg_client):
    """PostgreSQL cannot store U+0000 in text/JSON (SQLite can). It must surface as a client error."""
    client, _, _ = pg_client
    h = register(client)
    r = client.put(f"{P}/profile", headers=h, json={"full_name": "Bad\u0000Name"})
    assert r.status_code == 422, r.text
    r = client.post(f"{P}/jobs", headers=h, json={"title": "x\u0000y", "company": "c"})
    assert r.status_code == 422, r.text
    assert client.get(f"{P}/profile", headers=h).status_code == 200  # connection/session still healthy


def test_timestamps_are_timezone_aware_and_unicode_roundtrips(pg_client):
    client, factory, _ = pg_client
    h = register(client)
    r = client.put(f"{P}/profile", headers=h, json={"full_name": "रिया शर्मा 😀", "skills": [{"name": "C++"}]})
    assert r.json()["full_name"] == "रिया शर्मा 😀"
    with factory() as s:
        u = s.scalar(sa.select(models.User))
        assert u.created_at.tzinfo is not None


def test_job_dedup_unique_constraint_enforced_by_database(pg_client):
    client, factory, _ = pg_client
    h = register(client)
    j = {"title": "A", "company": "B", "source": "feed", "external_job_id": "x1"}
    a = client.post(f"{P}/jobs", headers=h, json=j).json()
    b = client.post(f"{P}/jobs", headers=h, json=j).json()
    assert a["id"] == b["id"]
    with factory() as s:
        s.add(models.Job(user_id=s.scalar(sa.select(models.User.id)), source="feed", external_job_id="x1",
                         title="dup", company="c", content_hash="h"))
        with pytest.raises(sa.exc.IntegrityError):
            s.commit()
