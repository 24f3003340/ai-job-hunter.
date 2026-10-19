import uuid
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext

from app import models  # noqa: F401
from app.db import Base

BACKEND = Path(__file__).resolve().parent.parent


def cfg(url: str) -> Config:
    c = Config(str(BACKEND / "alembic.ini"))
    c.set_main_option("script_location", str(BACKEND / "migrations"))
    c.set_main_option("sqlalchemy.url", url)
    return c


def test_fresh_database_matches_models(tmp_path):
    url = f"sqlite:///{tmp_path / 'fresh.db'}"
    command.upgrade(cfg(url), "head")
    eng = sa.create_engine(url)
    tables = set(sa.inspect(eng).get_table_names())
    assert set(Base.metadata.tables) <= tables
    with eng.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == [], f"models and migrations have drifted: {diff}"


def test_upgrade_preserves_existing_data_and_backfills(tmp_path):
    url = f"sqlite:///{tmp_path / 'old.db'}"
    command.upgrade(cfg(url), "0001")
    eng = sa.create_engine(url)
    uid, jid, r1, r2 = (str(uuid.uuid4()) for _ in range(4))
    with eng.begin() as c:
        c.execute(sa.text("INSERT INTO users (id,email,password_hash,account_status,failed_logins,created_at,updated_at)"
                          " VALUES (:i,'old@example.com','h','active',0,'2025-01-01','2025-01-01')"), {"i": uid.replace("-", "")})
        c.execute(sa.text("INSERT INTO candidate_profiles (id,user_id,full_name,phone,education_json,experience_json,"
                          "projects_json,skills_json,preferences_json,profile_version,updated_at) VALUES "
                          "(:i,:u,'Old User','', '[]','[]','[]','[]','{}',3,'2025-01-01')"),
                  {"i": uuid.uuid4().hex, "u": uid.replace("-", "")})
        c.execute(sa.text("INSERT INTO jobs (id,user_id,source,title,company,location,description,required_skills_json,"
                          "preferred_skills_json,first_seen_at,status,content_hash) VALUES "
                          "(:i,:u,'manual','Eng','Co','', '', '[]','[]','2025-01-01','active','x')"),
                  {"i": jid.replace("-", ""), "u": uid.replace("-", "")})
        for rid, ts in ((r1, "2025-02-01"), (r2, "2025-03-01")):
            c.execute(sa.text("INSERT INTO resume_versions (id,user_id,job_id,source_profile_version,content_json,"
                              "factual_review_status,created_at) VALUES (:i,:u,:j,1,:c,'pending',:t)"),
                      {"c": '{"a":1}', "i": rid.replace("-", ""), "u": uid.replace("-", ""), "j": jid.replace("-", ""), "t": ts})

    command.upgrade(cfg(url), "head")

    with eng.connect() as c:
        assert c.execute(sa.text("SELECT email FROM users")).scalar() == "old@example.com"
        assert c.execute(sa.text("SELECT full_name, profile_version, certifications_json FROM candidate_profiles")).one() \
            == ("Old User", 3, "[]")
        rows = c.execute(sa.text("SELECT version_number, generation_source, content_json FROM resume_versions "
                                 "ORDER BY created_at")).fetchall()
        assert [r[0] for r in rows] == [1, 2]
        assert all(r[1] == "legacy" and r[2] == '{"a":1}' for r in rows)
        assert c.execute(sa.text("SELECT count(*) FROM jobs")).scalar() == 1

    command.downgrade(cfg(url), "0001")  # reversible
    with eng.connect() as c:
        assert c.execute(sa.text("SELECT count(*) FROM resume_versions")).scalar() == 2
