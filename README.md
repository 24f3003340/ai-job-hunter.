# AI Job Hunter & Application Copilot

FastAPI + SQLAlchemy modular monolith. This repo currently contains the **backend only**
(CV upload → parsing → confirmation → tailored resume → approval-gated application draft).
See [`docs/API.md`](docs/API.md) for endpoints and [`docs/REPORT.md`](docs/REPORT.md) for status and limitations.

## Local setup
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
No network access, paid API, SMTP or antivirus is needed; the AI provider and ClamAV are mocked/faked.

    cd backend
    .venv/bin/python -m pytest -q               # full suite (136 tests)
    .venv/bin/python -m pytest -q tests/test_migrations.py    # migration checks only

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
requirement, rate limiting, and a ClamAV host (or an explicit `ALLOW_UNSCANNED_UPLOADS=true`) are configured.
The rate limiter is in-process (per worker); use a shared store before running multiple workers.
