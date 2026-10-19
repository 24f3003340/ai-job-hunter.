# AI Job Hunter & Application Copilot

Modular-monolith backend (FastAPI + SQLAlchemy) implementing the safety-critical core of the spec.
Frontend, workers, CV parsing and LLM generation are not built yet.

## Implemented (backend/)
- Auth: argon2 hashing, server-side sessions (logout invalidates), login lockout, account deletion (FR-01)
- Candidate profile with explicit `completed` / `in_progress` education (FR-02)
- Manual job entry, dedup (source id → canonical URL → title/company/location), stale/needs-verification status (FR-05)
- Deterministic match engine: unknown dimensions excluded and reported, hard constraints separate from score (FR-07)
- Application workflow: approval bound to a package hash (job, resume, cover letter, answers); changes revoke approval;
  submit is idempotent and never marks "submitted" without a connector or an explicit user report (FR-10/11)
- Per-user ownership checks on every resource (404 for foreign IDs)

## Not yet implemented
CV upload/parsing (FR-03), source connectors (FR-04), LLM resume/cover-letter generation (FR-08/09),
notifications, analytics, email verification, password reset, rate limiting beyond login lockout,
Alembic migrations, Redis/Celery worker, React frontend, Docker Compose.

## Run
    cd backend && python -m venv .venv && .venv/bin/pip install -e '.[dev]'
    .venv/bin/python -m pytest
    JOBHUNTER_DATABASE_URL=postgresql+psycopg://... .venv/bin/uvicorn app.main:app --reload
