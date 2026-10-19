"""Guards for the deployment tooling: restore verification, the staging gateway stand-in, and config drift."""
import hashlib
import importlib.util
import re
from pathlib import Path

import httpx
import pytest
from sqlalchemy.orm import Session

from app.config import settings
from helpers import make_pdf, upload

ROOT = Path(__file__).resolve().parents[2]


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---- storage verification (used by deploy/scripts/verify_restore.sh) ----------------------------

@pytest.fixture()
def vs():
    return load(ROOT / "backend/scripts/verify_storage.py", "verify_storage")


def test_verify_storage_accepts_consistent_state(client, auth, session_factory, vs):
    upload(client, auth, make_pdf(), "cv.pdf")
    with session_factory() as s:
        assert vs.verify(s, settings.storage_dir / "objects") == {"checked": 1, "problems": []}


def test_verify_storage_detects_corruption_loss_and_orphans(client, auth, session_factory, vs):
    upload(client, auth, make_pdf(), "a.pdf")
    upload(client, auth, make_pdf("Second CV\n" * 20), "b.pdf")
    objects = settings.storage_dir / "objects"
    files = sorted(objects.iterdir())
    files[0].write_bytes(files[0].read_bytes() + b"tampered")       # corrupted
    files[1].unlink()                                               # lost
    (objects / "deadbeef").write_bytes(b"no row points here")        # orphan
    with session_factory() as s:
        text = " | ".join(vs.verify(s, objects)["problems"])
    assert "mismatch" in text and "missing file" in text and "orphan file" in text


def test_verify_storage_checksum_matches_what_upload_recorded(client, auth, session_factory, vs):
    data = make_pdf()
    doc = upload(client, auth, data, "cv.pdf").json()
    assert doc["checksum"] == hashlib.sha256(data).hexdigest()


# ---- gateway stand-in --------------------------------------------------------------------------

@pytest.fixture()
def gateway(monkeypatch, tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<div id=root></div>")
    (tmp_path / "assets" / "app.js").write_text("x")
    monkeypatch.setenv("DIST", str(tmp_path))
    mod = load(ROOT / "scripts/staging_gateway.py", "staging_gateway")
    seen = {}

    def handler(request: httpx.Request):
        seen["headers"], seen["path"] = dict(request.headers), request.url.path
        return httpx.Response(200, json={"ok": True})

    mod.client = httpx.AsyncClient(base_url="http://upstream", transport=httpx.MockTransport(handler))
    transport = httpx.ASGITransport(app=mod.app, client=("198.51.100.7", 5555))
    return mod, httpx.AsyncClient(transport=transport, base_url="https://app.test"), seen


@pytest.mark.anyio
async def test_gateway_overwrites_client_supplied_forwarded_for(gateway):
    _, c, seen = gateway
    await c.get("/api/v1/auth/me", headers={"X-Forwarded-For": "1.2.3.4, 5.6.7.8", "X-Real-IP": "9.9.9.9"})
    assert seen["headers"]["x-forwarded-for"] == "198.51.100.7"      # the real peer, never the spoofed list
    assert "x-real-ip" not in seen["headers"]


@pytest.mark.anyio
async def test_gateway_hides_readiness_and_sets_security_headers(gateway):
    _, c, _ = gateway
    assert (await c.get("/health/ready")).status_code == 404
    r = await c.get("/some/spa/route")
    assert r.status_code == 200 and "root" in r.text and r.headers["cache-control"] == "no-store"
    for h in ("content-security-policy", "strict-transport-security", "x-content-type-options", "x-frame-options"):
        assert h in r.headers
    assert (await c.get("/assets/app.js")).headers["cache-control"].startswith("public, max-age=31536000")


@pytest.mark.anyio
async def test_gateway_never_serves_files_outside_dist(gateway):
    _, c, _ = gateway
    r = await c.get("/%2e%2e/%2e%2e/etc/passwd")
    assert "root:" not in r.text


@pytest.mark.anyio
async def test_gateway_enforces_body_limit(gateway):
    _, c, _ = gateway
    assert (await c.post("/api/v1/documents/upload", content=b"0" * (6 * 1024 * 1024 + 1))).status_code == 413


@pytest.fixture(params=["asyncio"])
def anyio_backend(request):
    return request.param


# ---- configuration drift ------------------------------------------------------------------------

def directives(policy: str) -> dict[str, str]:
    return {d.split()[0]: " ".join(d.split()[1:]) for d in (x.strip() for x in policy.split(";")) if d}


def test_caddy_csp_matches_the_frontend_build_policy():
    caddy = re.search(r'Content-Security-Policy "([^"]+)"', (ROOT / "deploy/Caddyfile").read_text()).group(1)
    vite = (ROOT / "frontend/vite.config.ts").read_text()
    body = vite[vite.index("const policy = ["):vite.index("].join('; ')")]
    meta = "; ".join(re.findall(r'["`]([^"`]+)["`]', body)).replace("${apiOrigin}", "").strip()
    meta_d = directives(meta)
    caddy_d = directives(caddy)
    caddy_d.pop("frame-ancestors")              # only meaningful as an HTTP header
    assert {k: v.strip() for k, v in meta_d.items()} == {k: v.strip() for k, v in caddy_d.items()}


def test_caddyfile_has_the_security_critical_directives():
    c = (ROOT / "deploy/Caddyfile").read_text()
    assert "header_up X-Forwarded-For {remote_host}" in c      # overwrite, not append
    assert "replace token REDACTED" in c                        # e-mailed tokens never land in access logs
    assert "request>headers>Authorization delete" in c
    assert "max_size 6MB" in c and "respond @ready 404" in c
    assert "frame-ancestors 'none'" in c and "Strict-Transport-Security" in c


def test_compose_publishes_only_the_web_ports_and_keeps_uploads_private():
    import yaml
    d = yaml.safe_load((ROOT / "deploy/docker-compose.staging.yml").read_text())
    published = {n for n, s in d["services"].items() if s.get("ports")}
    assert published == {"web", "mailpit"}                      # mailpit is opt-in and bound to 127.0.0.1
    assert d["services"]["mailpit"]["ports"] == ["127.0.0.1:8025:8025"]
    mounts = [n for n, s in d["services"].items() if any("uploads" in str(v) for v in s.get("volumes", []))]
    assert mounts == ["backend"]                                # the web tier cannot read stored CVs
    env = d["x-backend-env"]
    assert env["JOBHUNTER_ENV"] == "production" and env["JOBHUNTER_RATE_LIMIT_BACKEND"] == "redis"
    assert env["JOBHUNTER_REQUIRE_VERIFIED_EMAIL"] == "true"
    assert "command" not in d["services"]["backend"] and d["services"]["migrate"]["command"][:2] == ["alembic", "upgrade"]
    assert "CHANGE_ME" in (ROOT / "deploy/.env.staging.example").read_text()


def test_example_env_files_contain_placeholders_only():
    for f in ("deploy/.env.staging.example", "backend/.env.example", "frontend/.env.example"):
        text = (ROOT / f).read_text()
        assert not re.search(r"(sk-ant|BEGIN [A-Z ]*PRIVATE KEY|AKIA[0-9A-Z]{12,})", text), f


def test_production_config_validates_with_the_compose_environment(monkeypatch):
    """The exact environment the staging compose file builds must pass the app's production safety checks."""
    from app.config import Settings
    s = Settings(_env_file=None, env="production", database_url="postgresql+psycopg://u:p@postgres:5432/jobhunter",
                 public_base_url="https://staging.example.com", cors_origins=["https://staging.example.com"],
                 trust_proxy_headers=True, require_verified_email=True, rate_limit_backend="redis",
                 redis_url="redis://:pw@redis:6379/0", email_backend="smtp", smtp_host="smtp.example.com",
                 smtp_security="starttls", allow_unscanned_uploads=True, ai_provider="rule_based")
    assert s.env == "production"


# ---- deletion ledger / re-apply after restore -----------------------------------------------

def test_account_deletion_is_logged_without_personal_data(client, auth, caplog):
    import logging
    with caplog.at_level(logging.WARNING):
        assert client.delete("/api/v1/account", headers=auth).status_code == 204
    lines = [r.getMessage() for r in caplog.records if "account_deleted" in r.getMessage()]
    assert len(lines) == 1 and re.fullmatch(r"account_deleted user_id=[0-9a-f-]{36}", lines[0])
    assert "@" not in lines[0]


def test_reapply_deletions_removes_users_and_files_and_is_idempotent(client, auth, session_factory):
    from sqlalchemy import select
    from app.models import Document, User
    ra = load(ROOT / "backend/scripts/reapply_deletions.py", "reapply_deletions")
    upload(client, auth, make_pdf(), "cv.pdf")
    with session_factory() as s:
        uid = s.scalar(select(User.id))
        key = s.scalar(select(Document.storage_key))
    objects = settings.storage_dir / "objects"
    assert (objects / key).exists()
    with session_factory() as s:                     # dry run changes nothing
        assert ra.apply(s, {uid}, objects, dry_run=True)["users"] == 1
        assert s.get(User, uid) is not None and (objects / key).exists()
    with session_factory() as s:
        assert ra.apply(s, {uid}, objects, dry_run=False) == {"users": 1, "files": 1, "already_absent": 0, "dry_run": False}
    with session_factory() as s:
        assert s.get(User, uid) is None and not s.scalars(select(Document)).all()
    assert not (objects / key).exists()
    with session_factory() as s:                     # second run: nothing left, no error
        assert ra.apply(s, {uid}, objects, dry_run=False)["already_absent"] == 1


def test_reapply_pattern_extracts_ids_from_log_noise():
    ra = load(ROOT / "backend/scripts/reapply_deletions.py", "reapply_deletions2")
    text = "x WARNING app.routers.auth account_deleted user_id=11111111-2222-3333-4444-555555555555 more\nnoise\n"
    assert ra.PATTERN.findall(text) == ["11111111-2222-3333-4444-555555555555"]
