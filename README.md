# AI Job Hunter & Application Copilot

FastAPI + SQLAlchemy modular monolith (`backend/`) plus a React + TypeScript frontend (`frontend/`, see [`docs/FRONTEND.md`](docs/FRONTEND.md)).
The backend covers CV upload → parsing → confirmation → tailored resume → approval-gated application draft.
See [`docs/SECURITY.md`](docs/SECURITY.md) for the security checklist and what is *not* verified.
See [`docs/API.md`](docs/API.md) for endpoints and [`docs/REPORT.md`](docs/REPORT.md) for status and limitations.

## Deploying and operating
* [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) — staging guide (Docker Compose: Caddy HTTPS, FastAPI, PostgreSQL, Redis, private uploads, backups, restore verification) and what is code vs manual work.
* [`docs/OPERATIONS.md`](docs/OPERATIONS.md) — logging, monitoring, rate limits, backups, account deletion, privacy, incident response, release checklist.
* [`docs/BETA_ROADMAP.md`](docs/BETA_ROADMAP.md) — prioritised work before a public beta (P0/P1/P2).
* Without Docker: `scripts/staging_local.sh start` boots a staging-*like* stack natively (PostgreSQL, password-protected Redis, production-config backend with 2 workers, TLS gateway stand-in, STARTTLS SMTP sink); then `scripts/staging_smoke.py` and `E2E_EXTERNAL=1 npx playwright test` test it.
* CI (`.github/workflows/ci.yml`): backend unit, backend integration (PostgreSQL+Redis), frontend lint/types/build/tests, Playwright E2E on Chromium/Firefox/WebKit, and a job that boots the real compose stack.

## Frontend quick start
    cd frontend && cp .env.example .env && npm install
    npm run dev          # http://localhost:5173, proxies /api to the backend on :8000
    npm run lint && npm run typecheck && npm run build && npm test && npx playwright test

## Local setup (backend)
Requires Python 3.11+.

    cd backend
    python3 -m venv .venv
    .venv/bin/pip install -e '.[dev]'          # or: .venv/bin/pip install -r requirements.lock
    cp .env.example .env                        # placeholders only; edit as needed
    .venv/bin/alembic upgrade head              # creates/migrates the database (SQLite by default)
    .venv/bin/uvicorn app.main:app --reload     # http://localhost:8000/docs

For PostgreSQL set `JOBHUNTER_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/DB` and run the same
`alembic upgrade head`. In development, e-mails (verification / reset links) are written to the server log.

## Tests
Three tiers. The default run needs no services, network, SMTP, antivirus or paid API (AI and ClamAV are mocked/faked).

| Tier | Command (from `backend/`) | Needs |
|---|---|---|
| Unit (default) | `.venv/bin/python -m pytest -q` | nothing; SQLite in memory (181 tests) |
| Unit suite on PostgreSQL | `JOBHUNTER_TEST_DATABASE_URL=... .venv/bin/python -m pytest -q` | PostgreSQL 16; schema built by Alembic, tables truncated per test |
| Integration | `JOBHUNTER_TEST_DATABASE_URL=... JOBHUNTER_TEST_REDIS_URL=... .venv/bin/python -m pytest -q -m integration` | PostgreSQL, Redis; SMTP uses an in-process aiosmtpd server (25 tests) |
| External (opt-in) | `... -m external` | real clamd and/or a real Anthropic key; skipped otherwise (5 tests) |

Local services without Docker: `eval "$(scripts/dev_services.sh start)"` starts throwaway PostgreSQL + Redis and prints the
two `JOBHUNTER_TEST_*` variables (`... stop` to clean up). With Docker: `docker compose up -d postgres redis`
(then use the URLs in `.env.example`). Install the extras first: `.venv/bin/pip install -e '.[dev,integration]'`.

External tests: `JOBHUNTER_TEST_CLAMAV_HOST=127.0.0.1 ... -m external` (clamd, EICAR) and
`JOBHUNTER_RUN_EXTERNAL=1 JOBHUNTER_ANTHROPIC_API_KEY=... ... -m external` (billable).

## E-mail
`JOBHUNTER_EMAIL_BACKEND`: `file` (default in dev; writes `.eml` files to `var/mail/`, mode 0600 - open the file to get the
verification/reset link), `console` (logs recipient domain + subject only), `smtp` (production). SMTP uses STARTTLS (or
`ssl`) with certificate and hostname verification; set `JOBHUNTER_SMTP_HOST/PORT/USER/PASSWORD/SECURITY`. To eyeball real
delivery locally: `docker compose up -d mailpit`, set `SMTP_HOST=127.0.0.1 SMTP_PORT=1025 SMTP_SECURITY=none` (no
credentials), register, and read the message at http://localhost:8025. Mail is sent after the response; failures are logged
(class only) and never fail signup or reveal whether an address exists.

## Rate limiting & workers
`JOBHUNTER_RATE_LIMIT_BACKEND=memory` is correct for exactly one worker. For more, use `redis` + `JOBHUNTER_REDIS_URL`; the
limit is then shared (tested with 3 uvicorn workers). If Redis is down, auth/upload/generation return 503 by default
(`RATE_LIMIT_CRITICAL_FAIL_MODE=closed`); other limits fall back to per-process. `GET /health/ready` shows the state.

## Migrations
    .venv/bin/alembic upgrade head              # apply
    .venv/bin/alembic revision --autogenerate -m "what changed"   # then review the generated file by hand
    .venv/bin/alembic downgrade -1

`tests/test_migrations.py` asserts that a fresh `upgrade head` matches the models exactly and that upgrading a
database populated at the previous revision keeps its data.

## Key safety properties
* CV-derived data is a **draft** until the user confirms it; education status is always explicit.
* Resume education, employers, titles, dates, certifications and the skills list are copied from the profile
  snapshot; model output can only supply evidence-cited statements and orderings.
* Flagged statements block approval and clean export until the user accepts (attests) or rejects them.
* Resume versions are immutable; edits and regenerations create new versions.
* Approval is bound to a hash of job + resume (+ review decisions) + cover letter + answers.
* Nothing is ever marked "submitted" by the system; there are no submission connectors.

## Production
`JOBHUNTER_ENV=production` makes startup fail unless: PostgreSQL, https URLs/CORS, SMTP e-mail, verified-email
requirement, a shared (Redis) rate limiter, SMTP with TLS, and a ClamAV host (or an explicit
`ALLOW_UNSCANNED_UPLOADS=true`) are configured. Run `alembic upgrade head` as a deploy step (the app does not auto-create
tables in production). Production readiness has **not** been established; see the report.
