# Staging deployment guide

Target: one Linux host (or VM) running Docker, serving the app over HTTPS. Everything is defined in `deploy/`.
**Status:** the stack definition is exercised by CI (see *What has been verified*); no real host, DNS name or public
certificate has been used. Treat the first real deployment as the final test of §A–§B.

```
Internet ──443──> Caddy (TLS, SPA, /api proxy, security headers)
                    └──> FastAPI (2 workers)  ──> PostgreSQL 16   (named volume, private network)
                              │            └──> Redis 7 (password, rate-limit counters only)
                              └──> uploads volume (private; mounted ONLY in the backend)
                              └──> SMTP provider (TLS)         [optional: ClamAV, Anthropic]
```

## What is code in this repository vs. what you must do by hand

| In the repository (reviewed, tested) | Manual infrastructure work (not automated here) |
|---|---|
| `deploy/Dockerfile.backend`, `Dockerfile.web`, `Caddyfile`, `docker-compose.staging.yml`, `.env.staging.example` | Provision the host, install Docker, open ports 80/443 only |
| Production config validation (app refuses unsafe settings) | Create the DNS A/AAAA record for `SITE_ADDRESS` |
| `deploy/scripts/backup.sh`, `restore.sh`, `verify_restore.sh`, `backend/scripts/verify_storage.py` | Choose backup destination, schedule (cron/systemd timer), off-site copy, retention |
| `scripts/staging_smoke.py` (HTTP smoke test), Playwright E2E | Obtain SMTP credentials; set SPF/DKIM/DMARC for the sender domain |
| CI job that boots this very stack (`.github/workflows/ci.yml`, job `staging-compose`) | Secrets management, host patching, firewall, monitoring/alerting, log shipping |

## A. One-time host setup (manual)
1. Host: 2 vCPU / 4 GB RAM / 40 GB disk is enough for a personal pilot. Ubuntu LTS + Docker Engine + Compose v2.
2. Firewall: allow inbound **80** and **443** (and SSH from your IP). PostgreSQL (5432), Redis (6379) and the backend (8000) are
   **not** published by the compose file; keep them closed.
3. DNS: point `staging.example.com` at the host *before* first start (Caddy needs it to obtain a Let's Encrypt certificate).
4. Outbound mail: create credentials at your SMTP provider (submission port 587/STARTTLS or 465/TLS). Add SPF + DKIM + DMARC DNS
   records for the `EMAIL_FROM` domain, otherwise verification/reset mail will land in spam.

## B. Configure and start
```bash
git clone <repo> && cd ai-job-hunter.
cp deploy/.env.staging.example deploy/.env.staging
chmod 600 deploy/.env.staging
$EDITOR deploy/.env.staging          # replace every CHANGE_ME; generate secrets with: openssl rand -base64 33 | tr -d '/+='
export COMPOSE="docker compose -f deploy/docker-compose.staging.yml --env-file deploy/.env.staging"
$COMPOSE config --quiet              # validates interpolation (fails on missing variables)
$COMPOSE up -d --build               # builds images, runs `migrate` once, then starts backend + web
$COMPOSE ps                          # backend must become "healthy"
curl -fsS https://staging.example.com/health          # {"status":"ok"}
```
`migrate` applies `alembic upgrade head` as a one-shot service before the backend starts; app replicas never migrate implicitly.
`JOBHUNTER_ENV=production` is used for staging on purpose: if the configuration is unsafe the backend **refuses to start**
(non-HTTPS URLs, wildcard CORS, plaintext SMTP, missing Redis limiter, unscanned uploads without an explicit override…).
Read `docker compose logs backend` if it exits.

### The decisions encoded in the environment file
| Topic | Setting | Why |
|---|---|---|
| HTTPS | `SITE_ADDRESS=<dns name>` | Caddy obtains and renews the certificate; HTTP redirects to HTTPS; HSTS sent |
| CORS | `JOBHUNTER_CORS_ORIGINS=["https://<SITE_ADDRESS>"]` | Same-origin deployment: the SPA calls `/api/v1` on its own host. The list must still be explicit https |
| CSP | set in `Caddyfile` | `default-src 'self'`, no inline scripts/styles, `frame-ancestors 'none'`. A test (`test_deploy_artifacts.py`) keeps it equal to the policy baked into the frontend build |
| Secrets | `deploy/.env.staging` (git-ignored, mode 600) | Never in images or the repo. Passwords for PostgreSQL/Redis/SMTP; AI key only if `AI_PROVIDER=anthropic` |
| Client IP / rate limits | `TRUST_PROXY_HEADERS=true` | Safe **only because Caddy overwrites** `X-Forwarded-For`. Never enable it without such a proxy |
| Rate limits | Redis backend, production defaults (10/min auth, 10/h uploads, 20/h generation) | Shared by both workers; if Redis is down, auth/upload/generation fail closed (503) |
| Verified e-mail | `REQUIRE_VERIFIED_EMAIL=true` | Approve/submit/generate need a verified address |
| Malware scanning | `docker compose --profile clamav up -d` + `CLAMAV_HOST=clamav`, **or** `ALLOW_UNSCANNED_UPLOADS=true` | Fail-closed by default. Unscanned mode is reported in the UI and `/health/ready` |
| Health | container healthchecks use `/health` and `/health/ready`; Caddy hides `/health/ready` from the internet | Readiness reveals internal state |
| Private storage | named volume `uploads`, mounted only into `backend` | Caddy cannot read stored CVs; no URL maps to the volume; downloads go through authenticated endpoints |
| Access logs | Caddy JSON logs with `?token=` redacted and Authorization/Cookie removed | E-mailed links carry single-use tokens in the *frontend* URL |

## C. Smoke-test the deployment
```bash
# HTTP-level end-to-end (33 checks: register -> e-mail verification over SMTP -> CV -> resume -> claim review -> export -> match -> tracking)
STAGING_URL=https://staging.example.com STAGING_TOKEN_FROM=prompt python scripts/staging_smoke.py   # paste the e-mailed token when asked
```
With a real mailbox the script cannot read `.eml` files; either point `STAGING_MAIL_DIR` at a mail sink, or run the stack with the
Mailpit profile (`docker compose --profile mail-test up -d`, UI on `127.0.0.1:8025` via an SSH tunnel) while testing.
Browser E2E (Chromium/Firefox/WebKit) can be pointed at any deployment:
```bash
cd frontend && E2E_EXTERNAL=1 E2E_BASE_URL=https://staging.example.com E2E_MAIL_DIR=<dir with .eml files> npx playwright test
```
Both need a readable mail sink; against a real provider, use the manual checklist in `docs/FRONTEND.md`.

## D. Backups and restore verification (do this before storing real CVs)
```bash
export PGHOST=127.0.0.1 PGPORT=5432 PGUSER=jobhunter PGPASSWORD=... PGDATABASE=jobhunter
export STORAGE_DIR=/var/lib/docker/volumes/jobhunter-staging_uploads/_data BACKUP_DIR=/srv/backups
export BACKUP_PASSPHRASE=...        # AES-256; store it OUTSIDE the backup location (password manager)
B=$(deploy/scripts/backup.sh)       # db.dump + storage.tgz (+ .enc), rowcounts, alembic revision, sha256 manifest
BACKUP=$B deploy/scripts/verify_restore.sh   # restores into a scratch DB + dir and CHECKS it, then drops the scratch DB
```
(To reach PostgreSQL from the host temporarily, publish it on loopback with the CI override or `docker compose exec`; see
`deploy/docker-compose.ci.yml` for a worked example of host-side access.)
`verify_restore.sh` fails if: the manifest checksum differs, the Alembic revision differs, any table's row count differs from the
count recorded at backup time, or any stored file's size/SHA-256 does not match its database record or has no record.
Run it after every backup change and **monthly as a drill**; a backup that has never been restored is not a backup.
Restoring into production: stop the backend, restore into an *empty* database and storage dir with `restore.sh`, run
`alembic upgrade head`, start, then run the smoke test. `restore.sh` refuses to overwrite a non-empty target.

## E. Updates and rollback
```bash
git pull && $COMPOSE up -d --build        # `migrate` runs first; backend restarts when healthy
```
Take a backup **before** any release that changes the schema. Migrations are reversible (`alembic downgrade -1`, run as
`$COMPOSE run --rm migrate alembic downgrade -1`) but data-dropping downgrades are not: restore from backup instead.

## F. What has been verified (and what has not)
Verified (see `docs/REPORT.md` Phase H for evidence):
* The same E2E suite and a 33-step HTTP smoke test pass against a production-configured, HTTPS-terminated, multi-worker stack
  (PostgreSQL 16, password-protected Redis, STARTTLS+AUTH SMTP) started natively by `scripts/staging_local.sh`.
* Backup, encrypted backup, restore verification, and detection of a tampered dump / wrong passphrase / lost upload file.
* The compose stack and Caddyfile are built and tested in GitHub Actions (job `staging-compose`) — see the report for the last result.

Not verified: Let's Encrypt issuance on a public DNS name, a real SMTP provider (deliverability/SPF/DKIM), a real ClamAV,
the live Anthropic API, long-running behaviour (log growth, memory), load, Redis/PostgreSQL failure recovery on real hardware,
and off-site backup transport. Do not describe the system as production-ready until these are done (`docs/BETA_ROADMAP.md`).
